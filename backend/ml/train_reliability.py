"""Train, evaluate and save the supplier late-delivery risk model.

Usage (from ``backend/``)::

    python -m ml.train_reliability [--output DIR]
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from ml.features import (
    CATEGORICAL_FEATURES,
    FEATURE_COLUMNS,
    KNOWLEDGE_GAP_DAYS,
    NUMERIC_FEATURES,
    RECENT_WINDOW,
    build_training_frame,
)
from ml.scms import DATASET_SHA256, load_scms, scms_orders

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "artifacts"
MODEL_FILE = "reliability_model.joblib"
METADATA_FILE = "reliability_model.json"
REPORT_FILE = "evaluation_report.md"
EXTERNAL_FULFILMENT = "Direct Drop"


@dataclass
class TrainingResult:
    pipeline: Pipeline
    metadata: dict
    report_markdown: str


def _candidates(random_state: int) -> dict[str, Pipeline]:
    def pipeline(classifier) -> Pipeline:
        preprocess = ColumnTransformer([
            ("numeric", Pipeline([("impute", SimpleImputer(strategy="median")),
                                  ("scale", StandardScaler())]), NUMERIC_FEATURES),
            ("categorical", OneHotEncoder(handle_unknown="ignore", sparse_output=False),
             CATEGORICAL_FEATURES),
        ])
        return Pipeline([("preprocess", preprocess), ("classifier", classifier)])

    return {
        "logistic_regression": pipeline(LogisticRegression(
            class_weight="balanced", max_iter=2000, random_state=random_state)),
        "random_forest": pipeline(RandomForestClassifier(
            n_estimators=300, max_depth=8, min_samples_leaf=5,
            class_weight="balanced_subsample", n_jobs=-1, random_state=random_state)),
        "hist_gradient_boosting": pipeline(HistGradientBoostingClassifier(
            learning_rate=0.05, max_iter=300, max_depth=4, class_weight="balanced",
            random_state=random_state)),
    }


def _best_f1_threshold(y_true: np.ndarray, scores: np.ndarray) -> float:
    precision, recall, thresholds = precision_recall_curve(y_true, scores)
    with np.errstate(divide="ignore", invalid="ignore"):
        f1 = np.nan_to_num(2 * precision[:-1] * recall[:-1] / (precision[:-1] + recall[:-1]))
    return float(thresholds[int(np.argmax(f1))])


def _metrics(y_true: np.ndarray, scores: np.ndarray, predicted: np.ndarray) -> dict:
    y_true = np.asarray(y_true, dtype=int)
    both_classes = len(np.unique(y_true)) == 2
    return {
        "rows": int(len(y_true)),
        "late_rate": float(y_true.mean()),
        "roc_auc": float(roc_auc_score(y_true, scores)) if both_classes else None,
        "pr_auc": float(average_precision_score(y_true, scores)) if both_classes else None,
        "macro_f1": float(f1_score(y_true, predicted, average="macro", zero_division=0)),
        "brier": float(brier_score_loss(y_true, scores, labels=[0, 1])),
        "mean_score": float(np.mean(scores)),
        "confusion_matrix": confusion_matrix(y_true, predicted, labels=[0, 1]).tolist(),
    }


def _with_external(y_true, scores, predicted, external_mask) -> dict:
    result = _metrics(y_true, scores, predicted)
    result["external_vendors"] = _metrics(
        y_true[external_mask], scores[external_mask], predicted[external_mask])
    return result


def _period(dates: pd.Series) -> dict:
    return {"start": dates.min().date().isoformat(), "end": dates.max().date().isoformat()}


def train_and_evaluate(orders: pd.DataFrame, *, train_end_year: int = 2013,
                       cv_folds: int = 5, random_state: int = 42) -> TrainingResult:
    frame = build_training_frame(orders)
    is_train = frame["scheduled_date"].dt.year <= train_end_year
    train, test = frame[is_train], frame[~is_train]
    if train.empty or test.empty:
        raise ValueError("time split left the training or test period empty")
    x_train, y_train = train[FEATURE_COLUMNS], train["late"].to_numpy(dtype=int)
    x_test, y_test = test[FEATURE_COLUMNS], test["late"].to_numpy(dtype=int)

    # Model selection: cross-validated PR-AUC on the training period only.
    folds = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=random_state)
    candidates = _candidates(random_state)
    cv_scores: dict[str, dict] = {}
    out_of_fold: dict[str, np.ndarray] = {}
    for name, candidate in candidates.items():
        oof = np.zeros(len(train))
        roc, pr = [], []
        for fit_index, val_index in folds.split(x_train, y_train):
            model = clone(candidate).fit(x_train.iloc[fit_index], y_train[fit_index])
            scores = model.predict_proba(x_train.iloc[val_index])[:, 1]
            oof[val_index] = scores
            roc.append(roc_auc_score(y_train[val_index], scores))
            pr.append(average_precision_score(y_train[val_index], scores))
        cv_scores[name] = {"roc_auc": float(np.mean(roc)), "pr_auc": float(np.mean(pr))}
        out_of_fold[name] = oof
    model_name = max(cv_scores, key=lambda name: cv_scores[name]["pr_auc"])
    threshold = _best_f1_threshold(y_train, out_of_fold[model_name])
    pipeline = clone(candidates[model_name]).fit(x_train, y_train)

    # Test period.
    external = (test["fulfil_via"] == EXTERNAL_FULFILMENT).to_numpy()
    test_scores = pipeline.predict_proba(x_test)[:, 1]
    test_metrics = _with_external(y_test, test_scores, (test_scores >= threshold).astype(int),
                                  external)

    base_late_rate = float(y_train.mean())
    zeros = np.zeros(len(test))
    prior_train = 1.0 - train["prior_on_time_rate"].fillna(1.0 - base_late_rate).to_numpy()
    prior_test = 1.0 - test["prior_on_time_rate"].fillna(1.0 - base_late_rate).to_numpy()
    prior_threshold = _best_f1_threshold(y_train, prior_train)
    baselines = {
        "always_on_time": _with_external(y_test, zeros, zeros.astype(int), external),
        "prior_on_time_rate": {
            **_with_external(y_test, prior_test, (prior_test >= prior_threshold).astype(int),
                             external),
            "decision_threshold": prior_threshold,
        },
    }

    importance = permutation_importance(pipeline, x_test, y_test, scoring="average_precision",
                                        n_repeats=10, random_state=random_state)
    importances = {feature: float(value)
                   for feature, value in zip(FEATURE_COLUMNS, importance.importances_mean)}

    trained_at = datetime.now(timezone.utc)
    train_period, test_period = _period(train["scheduled_date"]), _period(test["scheduled_date"])
    metadata = {
        "model_version": f"reliability-scms-{trained_at:%Y%m%d}",
        "model_name": model_name,
        "trained_at": trained_at.isoformat(timespec="seconds"),
        "trained_on": (f"USAID SCMS delivery history {train_period['start'][:4]}-"
                       f"{train_period['end'][:4]} ({len(train):,} shipments)"),
        "dataset_sha256": DATASET_SHA256,
        "label": "late = delivered_date > scheduled_date",
        "feature_columns": list(FEATURE_COLUMNS),
        "knowledge_gap_days": KNOWLEDGE_GAP_DAYS,
        "recent_window": RECENT_WINDOW,
        "decision_threshold": threshold,
        "base_late_rate": base_late_rate,
        "sklearn_version": sklearn.__version__,
        "random_state": random_state,
        "cv_folds": cv_folds,
        "train_rows": int(len(train)),
        "test_rows": int(len(test)),
        "train_period": train_period,
        "test_period": test_period,
        "cv": cv_scores,
        "test": test_metrics,
        "baselines": baselines,
        "risk_bands": {"medium": threshold / 2, "high": threshold},
        "permutation_importance": importances,
    }
    return TrainingResult(pipeline, metadata, _report(metadata, train, test))


def _number(value, digits: int = 4) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _metric_row(label: str, metrics: dict) -> str:
    return (f"| {label} | {metrics['rows']:,} | {metrics['late_rate']:.1%} | "
            f"{_number(metrics['roc_auc'])} | {_number(metrics['pr_auc'])} | "
            f"{_number(metrics['macro_f1'])} | {_number(metrics['brier'])} |")


_METRIC_HEADER = ("| Scorer | Rows | Late rate | ROC-AUC | PR-AUC | Macro-F1 | Brier |\n"
                  "|---|---:|---:|---:|---:|---:|---:|")


def results_table(metadata: dict) -> str:
    """Markdown table: model and baselines, all test-period rows and external vendors only."""
    test, baselines = metadata["test"], metadata["baselines"]
    rows = [_METRIC_HEADER]
    for subset, pick in [("all shipments", lambda m: m),
                         ("external vendors", lambda m: m["external_vendors"])]:
        rows.append(_metric_row(f"{metadata['model_name']} ({subset})", pick(test)))
        rows.append(_metric_row(f"baseline: always on time ({subset})",
                                pick(baselines["always_on_time"])))
        rows.append(_metric_row(f"baseline: prior on-time rate ({subset})",
                                pick(baselines["prior_on_time_rate"])))
    return "\n".join(rows)


def _report(meta: dict, train: pd.DataFrame, test: pd.DataFrame) -> str:
    test_metrics = meta["test"]
    external = test_metrics["external_vendors"]
    (tn, fp), (fn, tp) = test_metrics["confusion_matrix"]
    cv_rows = "\n".join(
        f"| {name}{' (selected)' if name == meta['model_name'] else ''} | "
        f"{_number(scores['roc_auc'])} | {_number(scores['pr_auc'])} |"
        for name, scores in meta["cv"].items()
    )
    importance_rows = "\n".join(
        f"| {feature} | {value:.4f} |"
        for feature, value in sorted(meta["permutation_importance"].items(),
                                     key=lambda item: item[1], reverse=True)
    )
    train_external = (train["fulfil_via"] == EXTERNAL_FULFILMENT)
    yearly = test.groupby(test["scheduled_date"].dt.year)["late"].agg(["size", "mean"])
    yearly_train = train.groupby(train["scheduled_date"].dt.year)["late"].mean()
    tree_note = (
        "Tree models give flat scores outside the range they were trained on, so a supplier "
        "that is late far more often than any SCMS supplier is not scored as riskier than a "
        "moderately unreliable one, and may not reach the high band."
        if meta["model_name"] != "logistic_regression"
        else "Scores for suppliers far outside that range are extrapolations."
    )
    return f"""# Supplier late-delivery risk model

Model version `{meta['model_version']}`, trained {meta['trained_at']} with scikit-learn
{meta['sklearn_version']}. Selected model: **{meta['model_name']}**.

## Dataset

- Source: USAID Supply Chain Management System (SCMS) Delivery History, 10,324 shipments
  (SHA-256 `{meta['dataset_sha256']}`); see `ml/data/README.md`.
- Label: {meta['label']}.
- Training period (scheduled delivery date): {meta['train_period']['start']} to
  {meta['train_period']['end']}, {meta['train_rows']:,} shipments, late rate
  {meta['base_late_rate']:.2%} ({int(train_external.sum()):,} external-vendor shipments, late rate
  {train.loc[train_external, 'late'].mean():.2%}).
- Test period: {meta['test_period']['start']} to {meta['test_period']['end']},
  {meta['test_rows']:,} shipments, late rate {test_metrics['late_rate']:.2%}
  ({external['rows']:,} external-vendor shipments, late rate {external['late_rate']:.2%}).
- Late rate by training year: {', '.join(f'{year}: {rate:.1%}' for year, rate in yearly_train.items())}.
  By test year: {', '.join(f'{year}: {row["mean"]:.1%} of {int(row["size"]):,}' for year, row in yearly.iterrows())}.
- "External vendors" means `Fulfill Via = Direct Drop`; the other shipments come from
  SCMS's own regional distribution centres (one supplier key, "SCMS from RDC").

## Leakage controls

- Time-ordered split: the model is fitted only on shipments scheduled up to
  {meta['train_period']['end'][:4]} and evaluated on later ones.
- Each shipment's features use only the same supplier's shipments **delivered** before a
  knowledge cutoff of scheduled date minus {meta['knowledge_gap_days']} days, so outcomes that
  were not yet known are never used, and the shipment's own outcome never is.
- Features: {', '.join(f'`{name}`' for name in meta['feature_columns'])}.
  Excluded: actual and recorded delivery dates, freight and insurance (known only
  afterwards), country and product (domain-specific).
- Model selection and the decision threshold use the training period only
  ({meta['cv_folds']}-fold stratified cross-validation, `random_state={meta['random_state']}`).
  The test period was used once, for the numbers below.

## Model selection (cross-validation)

Mean over {meta['cv_folds']} folds of the training period; the model with the highest PR-AUC is
selected and refitted on the whole training period.

| Model | ROC-AUC | PR-AUC |
|---|---:|---:|
{cv_rows}

Decision threshold (maximises F1 on the selected model's out-of-fold predictions):
{meta['decision_threshold']:.4f}. Risk bands: medium from {meta['risk_bands']['medium']:.4f},
high from {meta['risk_bands']['high']:.4f}.

## Test period results

| Subset | Rows | Late rate | ROC-AUC | PR-AUC | Macro-F1 | Brier | Mean score |
|---|---:|---:|---:|---:|---:|---:|---:|
| All shipments | {test_metrics['rows']:,} | {test_metrics['late_rate']:.2%} | {_number(test_metrics['roc_auc'])} | {_number(test_metrics['pr_auc'])} | {_number(test_metrics['macro_f1'])} | {_number(test_metrics['brier'])} | {_number(test_metrics['mean_score'])} |
| External vendors | {external['rows']:,} | {external['late_rate']:.2%} | {_number(external['roc_auc'])} | {_number(external['pr_auc'])} | {_number(external['macro_f1'])} | {_number(external['brier'])} | {_number(external['mean_score'])} |

Confusion matrix, all test shipments, at threshold {meta['decision_threshold']:.4f}:

| | Predicted on time | Predicted late |
|---|---:|---:|
| Actually on time | {tn:,} | {fp:,} |
| Actually late | {fn:,} | {tp:,} |

"Mean score" is the average predicted late probability. The candidates are trained with
balanced class weights, so their scores are risk scores rather than calibrated
probabilities; compare the mean score with the observed late rate.

## Baselines

Same test period. "Always on time" scores every shipment 0. "Prior on-time rate" scores a
shipment as 1 - the supplier's prior on-time rate (training late rate when the supplier has
no history), with its own F1-maximising threshold from the training period
({meta['baselines']['prior_on_time_rate']['decision_threshold']:.4f}).

{results_table(meta)}

## Feature importance

Permutation importance of the selected model on the test period (mean drop in PR-AUC over
10 shuffles; values near zero or negative mean the model does not rely on the feature).

| Feature | Importance |
|---|---:|
{importance_rows}

## Limitations

- Health-commodity domain: SCMS shipped HIV/AIDS and malaria medicines and test kits to
  public health programmes. Delivery behaviour of other suppliers and industries may differ,
  so scores for an organisation's own suppliers are indicative only.
- Year-to-year drift: the late rate moves a lot between years (see Dataset), so a model
  fitted on 2006-{meta['train_period']['end'][:4]} is tested on a period with a different base rate.
- Low positive rate: about {meta['base_late_rate']:.0%} of training shipments are late, and
  {external['late_rate']:.1%} of external-vendor test shipments, so PR-AUC and F1 are more
  informative than accuracy, and small subsets give noisy estimates.
- Features intentionally exclude country and product so the model transfers to any
  organisation's purchase-order history; this costs accuracy that SCMS-specific features
  might add.
- Shuffled cross-validation mixes years, so the cross-validated scores above are more
  optimistic than the time-ordered test ({meta['model_name']}: CV PR-AUC
  {_number(meta['cv'][meta['model_name']]['pr_auc'])}, test PR-AUC {_number(test_metrics['pr_auc'])}).
- Scores are not calibrated probabilities: balanced class weights push them up (mean test
  score {_number(test_metrics['mean_score'])} against an observed late rate of
  {test_metrics['late_rate']:.2%}), which is why the Brier score can be worse than a baseline's.
  Use them to rank suppliers and with the risk bands, not as literal chances.
- Narrow training range: the lowest prior on-time rate of any training shipment's supplier is
  {train['prior_on_time_rate'].min():.0%}. {tree_note}
- More than half of all shipments share one supplier key ("SCMS from RDC"). For those rows
  the history features describe SCMS's whole warehouse network, and `prior_count` grows
  steadily with calendar time, so the model can partly use it as a proxy for the period.
"""


def save_artifacts(result: TrainingResult, output_dir: Path) -> None:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(result.pipeline, output_dir / MODEL_FILE, compress=3)
    (output_dir / METADATA_FILE).write_text(json.dumps(result.metadata, indent=2),
                                            encoding="utf-8")
    (output_dir / REPORT_FILE).write_text(result.report_markdown, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train the supplier late-delivery risk model.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR,
                        help="directory for the model, metadata and report")
    args = parser.parse_args(argv)
    result = train_and_evaluate(scms_orders(load_scms()))
    save_artifacts(result, args.output)
    print(f"Selected model: {result.metadata['model_name']} "
          f"(threshold {result.metadata['decision_threshold']:.4f})")
    print(results_table(result.metadata))
    print(f"Artifacts written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
