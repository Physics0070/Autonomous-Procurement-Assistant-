"""Re-measure the project's headline ML numbers with uncertainty, so the figures quoted anywhere can be trusted.

Usage (from backend/):  python -m ml.validate_numbers      Writes ml/artifacts/validation_numbers.json

What it adds to the single-number reports:
  * late-delivery risk: bootstrap confidence intervals, the paired gain over the baseline, stability by test year and by
    supplier group, calibration error, and precision/recall at both thresholds;
  * price errors: bootstrap intervals, the detection rate as the size of the error grows, and the false-alarm rate on
    every correct quote;
  * forecast: the chosen method against fixed alternatives at several different cut-off months, not one.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, precision_score, recall_score, roc_auc_score

from ml.anomaly import assess_price
from ml.features import FEATURE_COLUMNS
from ml.forecast import _METHODS, SEASON, forecast_demand, monthly_series, wape
from ml.reliability_model import ARTIFACT_DIR, METADATA_FILE, MODEL_FILE
from ml.scms import load_scms, scms_orders
from ml.train_reliability import build_training_frame

OUT = Path(__file__).resolve().parent / "artifacts" / "validation_numbers.json"
DATA = Path(__file__).resolve().parent / "data" / "india"
RNG = np.random.default_rng(7)
BOOT = 2000


def ci(values: np.ndarray) -> list[float]:
    return [round(float(np.percentile(values, 2.5)), 4), round(float(np.percentile(values, 97.5)), 4)]


def bootstrap(y, scores, baseline) -> dict:
    n = len(y)
    auc, pr, base_auc, delta = [], [], [], []
    for _ in range(BOOT):
        idx = RNG.integers(0, n, n)
        if len(np.unique(y[idx])) < 2:
            continue
        a, b = roc_auc_score(y[idx], scores[idx]), roc_auc_score(y[idx], baseline[idx])
        auc.append(a), base_auc.append(b), delta.append(a - b)
        pr.append(average_precision_score(y[idx], scores[idx]))
    return {"roc_auc": round(float(roc_auc_score(y, scores)), 4), "roc_auc_ci95": ci(np.array(auc)),
            "pr_auc": round(float(average_precision_score(y, scores)), 4), "pr_auc_ci95": ci(np.array(pr)),
            "baseline_roc_auc": round(float(roc_auc_score(y, baseline)), 4), "baseline_roc_auc_ci95": ci(np.array(base_auc)),
            "gain_over_baseline": round(float(np.mean(delta)), 4), "gain_ci95": ci(np.array(delta)),
            "gain_is_positive_share": round(float(np.mean(np.array(delta) > 0)), 4)}


def risk() -> dict:
    import joblib  # loads this repository's own trained model file, not untrusted input

    frame = build_training_frame(scms_orders(load_scms()))
    meta = json.loads((ARTIFACT_DIR / METADATA_FILE).read_text(encoding="utf-8"))
    model = joblib.load(ARTIFACT_DIR / MODEL_FILE)
    test = frame[frame["scheduled_date"].dt.year >= 2014].copy()
    x = test[meta["feature_columns"]]
    y = test["late"].to_numpy(dtype=int)
    scores = model.predict_proba(x)[:, 1]
    # no history: the training late rate, as in the shipped baseline
    baseline = 1.0 - test["prior_on_time_rate"].fillna(1.0 - 0.1067).to_numpy(dtype=float)
    result = {"test_rows": int(len(y)), "late_rate": round(float(y.mean()), 4), "overall": bootstrap(y, scores, baseline)}
    for name, mask in (("external_vendors", (test["fulfil_via"] == "Direct Drop").to_numpy()),
                       ("rdc_shipments", (test["fulfil_via"] != "Direct Drop").to_numpy())):
        if len(np.unique(y[mask])) == 2:
            result[name] = {"rows": int(mask.sum()), "late_rate": round(float(y[mask].mean()), 4),
                            "roc_auc": round(float(roc_auc_score(y[mask], scores[mask])), 4)}
    result["by_year"] = {int(year): {"rows": int(m.sum()), "late_rate": round(float(y[m].mean()), 4),
                                     "roc_auc": round(float(roc_auc_score(y[m], scores[m])), 4)}
                         for year in sorted(test["scheduled_date"].dt.year.unique())
                         for m in [(test["scheduled_date"].dt.year == year).to_numpy()] if len(np.unique(y[m])) == 2}
    # Calibration: mean predicted against observed in ten equal-count bins, and the expected calibration error.
    bins = pd.qcut(pd.Series(scores), 10, duplicates="drop")
    table = pd.DataFrame({"p": scores, "y": y, "bin": bins}).groupby("bin", observed=True).agg(p=("p", "mean"), y=("y", "mean"), n=("y", "size"))
    result["calibration_ece"] = round(float((table["n"] * (table["p"] - table["y"]).abs()).sum() / table["n"].sum()), 4)
    result["calibration_bins"] = [[round(float(r.p), 3), round(float(r.y), 3), int(r.n)] for r in table.itertuples()]
    for label, threshold in (("shipped", meta["decision_threshold"]), ("screening", meta.get("screening_threshold"))):
        if threshold is None:
            continue
        flagged = (scores >= threshold).astype(int)
        boots_p, boots_r = [], []
        for _ in range(BOOT):
            idx = RNG.integers(0, len(y), len(y))
            if flagged[idx].sum() and y[idx].sum():
                boots_p.append(precision_score(y[idx], flagged[idx])), boots_r.append(recall_score(y[idx], flagged[idx]))
        result[f"threshold_{label}"] = {"threshold": round(float(threshold), 4), "share_flagged": round(float(flagged.mean()), 4),
                                        "precision": round(float(precision_score(y, flagged)), 4), "precision_ci95": ci(np.array(boots_p)),
                                        "recall": round(float(recall_score(y, flagged)), 4), "recall_ci95": ci(np.array(boots_r))}
    return result


def price_errors() -> dict:
    history = pd.read_csv(DATA / "price_history.csv")
    quotes = pd.read_csv(DATA / "price_quotes_labelled.csv", parse_dates=["quote_date"]).sort_values("quote_date").reset_index(drop=True)
    past = {key: group["unit_price_inr"].to_numpy() for key, group in history.groupby("item_key")}
    status = [assess_price(r.quoted_unit_price_inr, past[r.item_key])["status"] for r in quotes.itertuples()]
    quotes["flag"] = [int(s != "NORMAL") for s in status]
    quotes["high"] = [int(s == "HIGH_ANOMALY") for s in status]
    test = quotes.iloc[150:]

    def pr(frame, column) -> dict:
        y, f = frame["is_wrong"].to_numpy(), frame[column].to_numpy()
        ps, rs = [], []
        for _ in range(BOOT):
            idx = RNG.integers(0, len(y), len(y))
            if f[idx].sum() and y[idx].sum():
                ps.append(precision_score(y[idx], f[idx])), rs.append(recall_score(y[idx], f[idx]))
        return {"precision": round(float(precision_score(y, f)), 3), "precision_ci95": ci(np.array(ps)),
                "recall": round(float(recall_score(y, f)), 3), "recall_ci95": ci(np.array(rs))}

    ratio = quotes["quoted_unit_price_inr"] / quotes["item_key"].map({k: float(np.median(v)) for k, v in past.items()})
    off = (ratio - 1).abs()
    curve = {}
    for lo, hi in ((0, 0.1), (0.1, 0.2), (0.2, 0.35), (0.35, 0.6), (0.6, 1.0), (1.0, 100)):
        m = (quotes["is_wrong"] == 1) & (off >= lo) & (off < hi)
        if m.sum():
            curve[f"{int(lo * 100)}-{int(hi * 100) if hi < 100 else 'up'}% off the item's median"] = {"wrong_quotes": int(m.sum()), "flagged": round(float(quotes.loc[m, "flag"].mean()), 3)}
    clean = quotes[quotes["is_wrong"] == 0]
    return {"history_rows": int(len(history)), "quotes": int(len(quotes)), "wrong": int(quotes["is_wrong"].sum()),
            "later_half_any_flag": pr(test, "flag"), "later_half_high_only": pr(test, "high"),
            "all_any_flag": pr(quotes, "flag"),
            "false_alarm_rate_on_correct_quotes": round(float(clean["flag"].mean()), 3),
            "recall_by_error_type": quotes[quotes["is_wrong"] == 1].groupby("error_type")["flag"].mean().round(3).to_dict(),
            "detection_by_size_of_error": curve}


def forecasts() -> dict:
    """Twelve cut-off months per series, three-month totals, on the months before SCMS stops recording shipments."""
    scms = load_scms()
    scms = scms[scms["scheduled_date"] < "2015-09-01"]
    series = {f"{g} quantity": monthly_series(rows["scheduled_date"], rows["quantity"]).to_numpy(float)
              for g, rows in scms.groupby("product_group") if rows["product_group"].nunique() and g in ("ARV", "HRDT")}
    series["all shipments, order value"] = monthly_series(scms["scheduled_date"], scms["order_value"]).to_numpy(float)
    series["all shipments, count"] = monthly_series(scms["scheduled_date"], np.ones(len(scms))).to_numpy(float)
    out = {}
    for name, values in series.items():
        errors = {m: [] for m in _METHODS}
        errors["chosen by the app"] = []
        inside, ranked = [], {}
        for end in range(len(values) - 36, len(values) - 2, 3):
            train, actual = values[:end], values[end:end + 3]
            for method in _METHODS:
                if method != "seasonal_naive" or len(train) >= SEASON + 3:
                    errors[method].append(wape(actual, _METHODS[method](train, 3)))
            result = forecast_demand(pd.Series(train, index=pd.date_range("2000-01-01", periods=len(train), freq="MS")), horizon=3)
            predicted = np.array([p["quantity"] for p in result["forecast"]])
            errors["chosen by the app"].append(wape(actual, predicted))
            inside.extend(float(l <= a <= h) for a, (l, h) in zip(actual, [(p["low"], p["high"]) for p in result["forecast"]]))
            ranked.setdefault(result["confidence"], []).append(errors["chosen by the app"][-1])
        out[name] = {"cutoffs": len(errors["chosen by the app"]),
                     "mean_error_pct": {m: round(100 * float(np.mean(v)), 1) for m, v in errors.items() if v},
                     "actual_months_inside_the_range": round(float(np.mean(inside)), 2),
                     "error_when_labelled": {label: round(100 * float(np.mean(v)), 1) for label, v in ranked.items()}}
    return out


def main() -> int:
    result = {"risk": risk(), "price_errors": price_errors(), "forecast": forecasts()}
    OUT.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
