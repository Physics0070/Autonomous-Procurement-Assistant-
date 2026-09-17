"""Offline SCMS evaluation of the price-anomaly and demand-forecast helpers.

Usage (from ``backend/``)::

    python -m ml.evaluate_analytics [--output FILE] [--jobs N]
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

from ml.anomaly import MIN_SAMPLES, assess_price
from ml.forecast import forecast_demand, monthly_series
from ml.scms import load_scms

REPORT_PATH = Path(__file__).resolve().parent / "artifacts" / "analytics_evaluation.md"
FORECAST_GROUPS = ["ARV", "HRDT"]
FORECAST_HORIZON = 3
CHUNK_SIZE = 50
FLAGS = ["POSSIBLE_ANOMALY", "HIGH_ANOMALY"]


def _assess_chunk(product: str, prices: np.ndarray, positions: np.ndarray) -> list[dict]:
    rows = []
    for position in positions:
        result = assess_price(prices[position], np.delete(prices, position))
        if result is not None:
            rows.append({"product": product, "price": float(prices[position]),
                         "status": result["status"], "score": result["score"],
                         "median": result["median"], "ratio": result["deviation_ratio"]})
    return rows


def evaluate_anomaly(scms: pd.DataFrame, jobs: int = -1) -> tuple[pd.DataFrame, int]:
    """Leave-one-out ``assess_price`` for every positive unit price of eligible products.

    Returns one row per assessed price and the number of non-positive prices skipped.
    """
    positive = scms[scms["unit_price"] > 0]
    skipped = int(len(scms) - len(positive))
    tasks = []
    for product, group in positive.groupby("product", sort=True):
        prices = group["unit_price"].to_numpy(dtype=float)
        if len(prices) < MIN_SAMPLES:
            continue
        for start in range(0, len(prices), CHUNK_SIZE):
            positions = np.arange(start, min(start + CHUNK_SIZE, len(prices)))
            tasks.append(delayed(_assess_chunk)(product, prices, positions))
    chunks = Parallel(n_jobs=jobs)(tasks)
    rows = [row for chunk in chunks for row in chunk]
    return pd.DataFrame(rows, columns=["product", "price", "status", "score", "median", "ratio"]), skipped


def evaluate_forecasts(scms: pd.DataFrame) -> dict[str, dict]:
    results = {}
    for group in FORECAST_GROUPS:
        rows = scms[scms["product_group"] == group]
        series = monthly_series(rows["scheduled_date"], rows["quantity"])
        result = forecast_demand(series, horizon=FORECAST_HORIZON)
        result["first_month"] = series.index[0].strftime("%Y-%m")
        result["last_month"] = series.index[-1].strftime("%Y-%m")
        result["zero_months"] = int((series == 0).sum())
        result["shipments"] = int(len(rows))
        results[group] = result
    return results


def _share(frame: pd.DataFrame, status: str) -> str:
    return f"{(frame['status'] == status).mean():.1%}"


def build_report(anomalies: pd.DataFrame, skipped: int, forecasts: dict[str, dict]) -> str:
    per_product = (
        anomalies.groupby("product")
        .agg(prices=("status", "size"),
             median=("median", "median"),
             possible=("status", lambda s: (s == "POSSIBLE_ANOMALY").mean()),
             high=("status", lambda s: (s == "HIGH_ANOMALY").mean()))
        .sort_values("prices", ascending=False)
    )
    product_rows = "\n".join(
        f"| {row.Index} | {int(row.prices):,} | {row.possible:.1%} | {row.high:.1%} |"
        for row in per_product.itertuples()
    )
    flagged = anomalies[anomalies["status"].isin(FLAGS)].copy()
    flagged["distance"] = np.abs(np.log(flagged["ratio"]))
    extreme = flagged.sort_values(["distance", "product", "price"],
                                  ascending=[False, True, True]).head(10)
    extreme_rows = "\n".join(
        f"| {row.product} | {row.price:,.4g} | {row.median:,.4g} | {row.ratio:,.2f}x | {row.status} |"
        for row in extreme.itertuples()
    )

    forecast_rows = []
    for group, result in forecasts.items():
        scores = result["backtest_smape"]
        forecast_rows.append(
            f"| {group} | {result['shipments']:,} | {result['first_month']} to {result['last_month']} "
            f"({result['history_months']} months, {result['zero_months']} with no shipments) | "
            f"{result['holdout_months']} | {scores.get('linear_trend', float('nan')):.1f} | "
            f"{scores.get('seasonal_naive', float('nan')):.1f} | {result['method']} | "
            + ", ".join(f"{p['month']}: {p['quantity']:,.0f}" for p in result["forecast"])
            + " |"
        )
    forecast_table = "\n".join(forecast_rows)
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")

    return f"""# Analytics evaluation (USAID SCMS)

Generated {generated} by `python -m ml.evaluate_analytics` from the verified SCMS file
(see `ml/data/README.md`).

## Price anomaly detection

**There are no ground-truth labels.** SCMS does not say which prices were wrong, so this
section reports how often prices are flagged and shows examples, not an accuracy figure.

Method: for every product (`Molecule/Test Type`) with at least {MIN_SAMPLES} positive unit prices,
each price is assessed with `assess_price` against all the product's other prices
(leave-one-out). A price is only assessed when those other prices number at least
{MIN_SAMPLES}. {skipped:,} shipments with a unit price of zero or below are excluded.

The thresholds are the 10th and 2nd percentiles of the past prices' own anomaly scores, so
roughly one price in ten is expected to be flagged even when nothing is wrong. Treat the flags
as "worth a second look", not as errors.

| Scope | Products | Prices assessed | Flagged POSSIBLE_ANOMALY | Flagged HIGH_ANOMALY | Flagged either |
|---|---:|---:|---:|---:|---:|
| All eligible products | {anomalies['product'].nunique()} | {len(anomalies):,} | {_share(anomalies, 'POSSIBLE_ANOMALY')} | {_share(anomalies, 'HIGH_ANOMALY')} | {anomalies['status'].isin(FLAGS).mean():.1%} |

### By product

| Product | Prices assessed | POSSIBLE_ANOMALY | HIGH_ANOMALY |
|---|---:|---:|---:|
{product_rows}

### Ten most extreme flagged prices

Ranked by how far the price is from the product's median (ratio above or below 1).

| Product | Unit price (USD) | Median of other prices | Ratio | Status |
|---|---:|---:|---:|---|
{extreme_rows}

Unit prices are per unit of the product's pack (tablet, test, bottle...), and one product name
can cover several strengths, dosage forms and pack sizes, which can explain large ratios.

## Demand forecasting

Monthly quantity (`Line Item Quantity`, summed by scheduled delivery month) for the two
largest product groups. Each method is backtested once on the last `holdout` months
(min(6, months // 4)); the method with the lower sMAPE (percent, 0-200) is chosen and
refitted on the full series to forecast the next {FORECAST_HORIZON} months.

| Product group | Shipments | Series | Holdout months | sMAPE linear_trend | sMAPE seasonal_naive | Chosen | Forecast |
|---|---:|---|---:|---:|---:|---|---|
{forecast_table}

Limitations: a single holdout of a few months is a small test; monthly shipment quantities
are lumpy (large one-off orders), which neither a trend line nor last year's value can
anticipate; the series end in {' and '.join(sorted({r['last_month'] for r in forecasts.values()}))},
so the forecast months are historical, not current demand.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate price anomaly and forecast helpers on SCMS.")
    parser.add_argument("--output", type=Path, default=REPORT_PATH)
    parser.add_argument("--jobs", type=int, default=-1, help="parallel worker processes")
    args = parser.parse_args(argv)

    scms = load_scms()
    anomalies, skipped = evaluate_anomaly(scms, jobs=args.jobs)
    forecasts = evaluate_forecasts(scms)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build_report(anomalies, skipped, forecasts), encoding="utf-8")

    print(f"Prices assessed: {len(anomalies):,} across {anomalies['product'].nunique()} products; "
          f"POSSIBLE {_share(anomalies, 'POSSIBLE_ANOMALY')}, HIGH {_share(anomalies, 'HIGH_ANOMALY')}")
    for group, result in forecasts.items():
        print(f"{group}: sMAPE {result['backtest_smape']} -> {result['method']}")
    print(f"Report written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
