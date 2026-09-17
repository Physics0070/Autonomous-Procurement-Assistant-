# Phase 6 ML Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use anthropic-skills:test-driven-development and anthropic-skills:verification-before-completion. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Train and ship a supplier late-delivery risk model, a price-anomaly detector and a demand forecaster from the real USAID SCMS delivery dataset, as a self-contained `ml` package the backend can import.

**Architecture:** A pure-Python package at `backend/ml/` (no database, no web code). `scms.py` loads and cleans the dataset; `features.py` turns any order history into leakage-safe features; `train_reliability.py` trains, evaluates and saves the model; `reliability_model.py` loads it and predicts for one supplier; `anomaly.py` and `forecast.py` are small analytic helpers with an offline evaluation script. The backend (built separately) calls only the public functions listed under **Interfaces**.

**Tech Stack:** Python 3.12, pandas 2.2.3, numpy 2.5.2, scikit-learn 1.9.1, joblib 1.6.0, pytest 8.3.4 (all already installed in `backend/.venv`).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-09-17-phases-3-6-design.md`, §6.
- **Only create or change files under `backend/ml/` and files named `backend/tests/test_ml_*.py`.** Do not edit `backend/app/`, `backend/requirements.txt`, `backend/pytest.ini`, `backend/tests/conftest.py`, the frontend or other docs — another engineer is editing those in parallel.
- **Do not install packages.** Everything listed in Tech Stack is installed. If you believe another package is required, stop and report it.
- **Do not run git commands.** The team commits once at the end.
- Python: `backend/.venv/Scripts/python.exe` (Windows, Git Bash). Run commands from `backend/`.
- Run tests with: `./.venv/Scripts/python.exe -m pytest tests/test_ml_*.py -q -p no:cacheprovider --noconftest`
  (`--noconftest` keeps the parallel engineer's database fixtures out of your runs).
- Dataset: `backend/ml/data/SCMS_Delivery_History_Dataset.csv`, SHA-256
  `918b992dd3e8d4b64d2a727b2c4ea607603d0c58f19484e73f7b78528c6a8673`. Read with
  `encoding="utf-8-sig"`, falling back to `"latin-1"` on `UnicodeDecodeError`; strip any `﻿` from column names.
- **Label:** `late = delivered_date > scheduled_date`. It must never be an input feature, directly or indirectly.
- **Leakage rule:** a feature for an order may only use other orders of the same supplier whose `delivered_date` is strictly before that order's knowledge cutoff.
- **Never weaken a test to make it pass.** If `test_a_consistently_late_supplier_scores_riskier_than_a_punctual_one` fails, investigate the model (e.g. `HistGradientBoostingClassifier(monotonic_cst=...)` on `prior_on_time_rate` = −1 and `recent_late_rate` = +1) and report what you found.
- Report metrics exactly as measured, including if they are weak. No cherry-picking of splits or seeds.
- `random_state=42` everywhere randomness exists.
- Keep `ml/artifacts/reliability_model.joblib` under 10 MB.

---

## File map

| File | Responsibility |
|---|---|
| `ml/__init__.py` | Package marker (empty docstring only) |
| `ml/data/README.md` | Dataset provenance, checksum, verification, licence note |
| `ml/scms.py` | Load, verify and clean SCMS; map it to the generic orders schema |
| `ml/features.py` | Leakage-safe feature engineering for any supplier order history |
| `ml/train_reliability.py` | Train candidates, evaluate, pick winner, save artifact + report (CLI) |
| `ml/reliability_model.py` | Load artifact; predict late-delivery risk for one supplier |
| `ml/anomaly.py` | Isolation Forest price assessment for one product |
| `ml/forecast.py` | Monthly demand series, backtest, forecast |
| `ml/evaluate_analytics.py` | Offline SCMS evaluation of anomaly + forecast → report (CLI) |
| `ml/artifacts/reliability_model.joblib` | Fitted scikit-learn `Pipeline` |
| `ml/artifacts/reliability_model.json` | Model metadata |
| `ml/artifacts/evaluation_report.md` | Reliability evaluation report |
| `ml/artifacts/analytics_evaluation.md` | Anomaly + forecast evaluation report |
| `tests/test_ml_scms.py`, `test_ml_features.py`, `test_ml_training.py`, `test_ml_reliability_model.py`, `test_ml_anomaly.py`, `test_ml_forecast.py` | Tests below, verbatim |

## Interfaces (the backend depends on these exact names)

```python
# ml/scms.py
DATASET_PATH: pathlib.Path        # backend/ml/data/SCMS_Delivery_History_Dataset.csv
DATASET_SHA256: str               # "918b992d...6c8a8673" (full value above)
def load_scms(path: pathlib.Path = DATASET_PATH, verify_checksum: bool = True) -> pandas.DataFrame
def scms_orders(scms: pandas.DataFrame) -> pandas.DataFrame   # -> ORDER_COLUMNS schema

# ml/features.py
ORDER_COLUMNS = ["supplier_key", "scheduled_date", "delivered_date",
                 "order_value", "quantity", "shipment_mode", "fulfil_via"]
NUMERIC_FEATURES = ["has_history", "prior_count", "prior_on_time_rate",
                    "prior_mean_delay_days", "recent_late_rate", "days_since_previous",
                    "log_order_value", "log_quantity"]
CATEGORICAL_FEATURES = ["shipment_mode", "fulfil_via"]
FEATURE_COLUMNS = NUMERIC_FEATURES + CATEGORICAL_FEATURES
KNOWLEDGE_GAP_DAYS = 30
RECENT_WINDOW = 10
def build_training_frame(orders: pandas.DataFrame) -> pandas.DataFrame
def features_for_order(history: pandas.DataFrame, order: dict,
                       as_of: pandas.Timestamp | None = None) -> pandas.DataFrame

# ml/train_reliability.py
@dataclass TrainingResult(pipeline, metadata: dict, report_markdown: str)
def train_and_evaluate(orders: pandas.DataFrame, *, train_end_year: int = 2013,
                       cv_folds: int = 5, random_state: int = 42) -> TrainingResult
def save_artifacts(result: TrainingResult, output_dir: pathlib.Path) -> None
def main(argv: list[str] | None = None) -> int   # python -m ml.train_reliability [--output DIR]

# ml/reliability_model.py
ARTIFACT_DIR: pathlib.Path        # backend/ml/artifacts
@dataclass ReliabilityPrediction(late_probability: float, on_time_probability: float,
    risk_level: str, model_version: str, model_name: str, trained_on: str,
    history_count: int, signals: list[dict], method: str = "ml_model")
    def as_dict(self) -> dict
class ReliabilityModel:
    @classmethod
    def load(cls, artifact_dir: pathlib.Path | None = None) -> "ReliabilityModel | None"
    metadata: dict
    def predict_for_supplier(self, history: pandas.DataFrame, order: dict,
                             as_of: pandas.Timestamp | None = None) -> ReliabilityPrediction

# ml/anomaly.py
MIN_SAMPLES = 20
def assess_price(unit_price: float, history_prices: Sequence[float]) -> dict | None

# ml/forecast.py
MIN_MONTHS = 12
def smape(actual: Sequence[float], predicted: Sequence[float]) -> float
def monthly_series(dates: Sequence, quantities: Sequence[float]) -> pandas.Series
def forecast_demand(series: pandas.Series, horizon: int = 3) -> dict
```

### Semantics the backend relies on

- `load_scms` returns one row per shipment with columns:
  `shipment_id` (int), `vendor`, `country`, `shipment_mode` (`"unknown"` when missing),
  `fulfil_via` (`"Direct Drop"` | `"From RDC"`), `product_group`, `product`
  (Molecule/Test Type), `item_description`, `dosage_form`, `scheduled_date`,
  `delivered_date` (datetime64), `quantity`, `order_value`, `unit_price`, `pack_price`,
  `weight_kg`, `freight_usd` (floats; NaN where the raw cell is text such as
  "Freight Included in Commodity"), `late` (bool), `delay_days` (int, delivered − scheduled).
  Checksum mismatch → `ValueError` whose message contains "checksum".
- `scms_orders` maps: `supplier_key=vendor`, `scheduled_date`, `delivered_date`,
  `order_value`, `quantity`, `shipment_mode`, `fulfil_via`.
- `build_training_frame(orders)` returns a frame with the same index as `orders`, columns
  `FEATURE_COLUMNS + ["late", "scheduled_date", "supplier_key"]`. For each order the
  knowledge cutoff is `scheduled_date - KNOWLEDGE_GAP_DAYS days`; known history = same
  supplier's orders with `delivered_date < cutoff`. Definitions:
  - `prior_count` = number of known orders; `has_history` = 1.0 if > 0 else 0.0
  - `prior_on_time_rate` = share of known orders not late (NaN when none)
  - `prior_mean_delay_days` = mean of `max(delay_days, 0)` over known orders (NaN when none)
  - `recent_late_rate` = share late among the `RECENT_WINDOW` most recently delivered known
    orders (NaN when none)
  - `days_since_previous` = days from the latest known `delivered_date` to the cutoff (NaN when none)
  - `log_order_value` = `log1p(max(order_value, 0))`, `log_quantity` = `log1p(max(quantity, 0))` (NaN when missing)
  - `shipment_mode`, `fulfil_via`: string, `"unknown"` when missing
  Must handle ~5,400 orders for one supplier in well under 10 seconds (sort by
  `delivered_date` and use `searchsorted` + cumulative sums, not nested Python loops).
- `features_for_order(history, order, as_of)`: `history` holds completed orders of one
  supplier in `ORDER_COLUMNS` (may be empty). `order` has `scheduled_date`, `order_value`,
  `quantity`, `shipment_mode`, `fulfil_via`. Cutoff = `as_of` when given, otherwise
  `order["scheduled_date"] - KNOWLEDGE_GAP_DAYS days`. Returns a one-row frame with
  `FEATURE_COLUMNS`, computed with the same definitions.
- `train_and_evaluate`:
  - Split by `scheduled_date.year`: train `<= train_end_year`, test `> train_end_year`.
  - Candidates, each a `Pipeline(ColumnTransformer(numeric: SimpleImputer(median) +
    StandardScaler; categorical: OneHotEncoder(handle_unknown="ignore")), classifier)`:
    `logistic_regression` = `LogisticRegression(class_weight="balanced", max_iter=2000)`;
    `random_forest` = `RandomForestClassifier(n_estimators=300, max_depth=8,
    min_samples_leaf=5, class_weight="balanced_subsample", n_jobs=-1)`;
    `hist_gradient_boosting` = `HistGradientBoostingClassifier(learning_rate=0.05,
    max_iter=300, max_depth=4, class_weight="balanced")` (monotonic constraints allowed).
  - Model selection: mean PR-AUC over `StratifiedKFold(cv_folds, shuffle=True)` on the
    training period. Winner refitted on the whole training period.
  - `decision_threshold`: the threshold maximising F1 on the winner's out-of-fold
    training predictions.
  - Test metrics on the test period: `roc_auc`, `pr_auc` (average precision), `macro_f1`
    at `decision_threshold`, `brier`, `late_rate`, `rows`, `confusion_matrix`
    (`[[tn, fp], [fn, tp]]`), plus the same metrics restricted to
    `fulfil_via == "Direct Drop"` under `test["external_vendors"]`.
  - Baselines on the test period: `always_on_time` (score 0 for every row → `roc_auc` 0.5,
    `pr_auc` = late rate, `macro_f1` computed) and `prior_on_time_rate`
    (score = `1 - prior_on_time_rate`, NaN → training base late rate).
  - `metadata` keys (all required): `model_version` (`"reliability-scms-YYYYMMDD"`),
    `model_name`, `trained_at` (ISO), `trained_on` (text containing "USAID SCMS" and the
    training years), `dataset_sha256`, `feature_columns`, `knowledge_gap_days`,
    `decision_threshold`, `base_late_rate` (training period), `sklearn_version`,
    `train_rows`, `test_rows`, `train_period` (`{"start","end"}` ISO dates),
    `test_period` (same), `cv` (per candidate `{"roc_auc","pr_auc"}` means),
    `test`, `baselines`, `risk_bands` (`{"medium": decision_threshold / 2,
    "high": decision_threshold}`), `permutation_importance` (winner, test period,
    `{feature: mean_importance}` over `FEATURE_COLUMNS`).
  - `report_markdown` sections, in order: `# Supplier late-delivery risk model`,
    `## Dataset`, `## Leakage controls`, `## Model selection (cross-validation)`,
    `## Test period results`, `## Baselines`, `## Feature importance`, `## Limitations`.
    Tables for metrics. Limitations must state: health-commodity domain; year-to-year drift;
    low positive rate; features intentionally exclude country and product.
- `save_artifacts` writes `reliability_model.joblib` (the Pipeline), `reliability_model.json`
  (metadata, `indent=2`) and `evaluation_report.md` into `output_dir` (created if missing).
- `main` loads SCMS, trains with defaults, saves to `--output` (default `ARTIFACT_DIR`),
  prints the test table, returns 0.
- `ReliabilityModel.load(dir)` returns `None` when either artifact file is missing.
  `predict_for_supplier` builds features with `features_for_order`, uses the pipeline's
  `predict_proba[:, 1]`. `risk_level`: `"high"` if p ≥ `risk_bands.high`, `"medium"` if
  p ≥ `risk_bands.medium`, else `"low"`. `history_count` = number of known history orders.
  `signals` — list of `{"text": str, "direction": "raises_risk" | "lowers_risk" | "neutral"}`
  derived only from the feature values, never contradicting them:
  - no known history → `{"text": "No delivery history with this supplier yet", "direction": "raises_risk"}`
  - `recent_late_rate >= 0.3` → `"Late on N of the last M deliveries"`, raises_risk
  - `recent_late_rate == 0` and M ≥ 3 → `"On time for all of the last M deliveries"`, lowers_risk
  - `prior_on_time_rate >= 0.9` and count ≥ 5 → `"On time for P% of N past deliveries"`, lowers_risk
  - `prior_on_time_rate < 0.7` → `"On time for only P% of N past deliveries"`, raises_risk
  - `prior_mean_delay_days >= 7` → `"Late deliveries averaged D days"`, raises_risk
  - `shipment_mode == "Ocean"` → `"Ocean freight"`, neutral
- `assess_price(unit_price, history_prices)`: returns `None` when fewer than `MIN_SAMPLES`
  positive prices. Feature = `log(price / median(history))`. Fit
  `IsolationForest(n_estimators=200, random_state=42)` on history; compare the new point's
  `score_samples` with the history's scores: below the 2nd percentile → `HIGH_ANOMALY`,
  below the 10th → `POSSIBLE_ANOMALY`, else `NORMAL`. When the history has zero spread,
  any price differing from the median by more than 1% is `POSSIBLE_ANOMALY`. Return
  `{"status", "method": "isolation_forest", "score", "sample_size", "median",
  "deviation_ratio", "reason"}`; `reason` is a sentence containing the word "median".
- `smape`: mean of `200 * |a - f| / (|a| + |f|)`, with 0/0 counted as 0.
- `monthly_series`: month-start index covering first→last month, summed quantities,
  zeros for empty months, float dtype.
- `forecast_demand(series, horizon)`: fewer than `MIN_MONTHS` months →
  `{"status": "insufficient_data", "history_months": n, "min_months": MIN_MONTHS}`.
  Otherwise holdout = `min(6, len // 4)`; backtest `linear_trend`
  (`LinearRegression` on month index) always, and `seasonal_naive` (value 12 months
  earlier) only when `len >= 12 + holdout`; choose lowest sMAPE (ties → seasonal_naive);
  refit on all data and forecast `horizon` months. Return `{"status": "ok", "method",
  "history_months", "backtest_smape": {method: value}, "forecast": [{"month": "YYYY-MM",
  "quantity": float >= 0}]}`.
- `evaluate_analytics.main()` writes `ml/artifacts/analytics_evaluation.md`:
  (a) anomaly — for every SCMS `product` with ≥ `MIN_SAMPLES` unit prices, leave-one-out
  `assess_price` on each price; table of share flagged `POSSIBLE_ANOMALY`/`HIGH_ANOMALY`
  and the 10 most extreme examples (product, price, median); state clearly there are no
  ground-truth labels. (b) forecasting — monthly quantity series for `product_group`
  `ARV` and `HRDT`; backtest sMAPE per method and the chosen method.

---

### Task 1: Dataset loader and provenance

**Files:**
- Create: `backend/ml/__init__.py`, `backend/ml/scms.py`, `backend/ml/data/README.md`
- Test: `backend/tests/test_ml_scms.py`

- [ ] **Step 1: Write the failing test**

```python
import pandas as pd
import pytest

from ml.scms import DATASET_SHA256, load_scms, scms_orders
from ml.features import ORDER_COLUMNS


@pytest.fixture(scope="module")
def scms():
    return load_scms()


def test_loads_every_shipment_with_parsed_dates(scms):
    assert len(scms) == 10324
    assert scms["scheduled_date"].notna().all()
    assert scms["delivered_date"].notna().all()
    assert pd.api.types.is_datetime64_any_dtype(scms["scheduled_date"])


def test_late_label_matches_the_verified_rate(scms):
    assert round(scms["late"].mean(), 4) == 0.1149
    assert (scms.loc[scms["late"], "delay_days"] > 0).all()
    assert (scms.loc[~scms["late"], "delay_days"] <= 0).all()


def test_text_placeholders_become_missing_values(scms):
    assert pd.api.types.is_float_dtype(scms["freight_usd"])
    assert scms["freight_usd"].isna().sum() > 1000
    assert set(scms["fulfil_via"].unique()) == {"Direct Drop", "From RDC"}
    assert (scms["shipment_mode"] == "unknown").sum() == 360
    assert scms["country"].str.contains("Ivoire").any()


def test_checksum_mismatch_is_rejected(tmp_path):
    bad = tmp_path / "scms.csv"
    bad.write_text("ID\n1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        load_scms(bad)


def test_orders_view_uses_the_generic_schema(scms):
    orders = scms_orders(scms)
    assert list(orders.columns) == ORDER_COLUMNS
    assert len(orders) == len(scms)
    assert DATASET_SHA256.startswith("918b992d")
```

Note: this test imports `ORDER_COLUMNS` from `ml.features`; create `ml/features.py` with at least the constants from **Interfaces** in this task so the import resolves.

- [ ] **Step 2: Run it and confirm it fails** — `./.venv/Scripts/python.exe -m pytest tests/test_ml_scms.py -q -p no:cacheprovider --noconftest` → `ModuleNotFoundError: No module named 'ml.scms'`.
- [ ] **Step 3: Implement** `ml/scms.py` per **Semantics**, the `ml/features.py` constants, and `ml/data/README.md` containing: title and publisher (USAID Supply Chain Management System, data.usaid.gov dataset `a3rc-nmf6`); that the official portal and the data.world mirror were unavailable in September 2026; source URL `https://raw.githubusercontent.com/jrcinco/supply-chain-shipment-price-data/master/SCMS_Delivery_History_Dataset.csv`; the SHA-256; the cross-check against `https://github.com/Prashant-Abbi/Supply-Chain-Management` (identical IDs, scheduled/delivered/recorded dates, weights, freight costs and late labels; that copy has cleaned placeholders and stripped accents); size facts (10,324 rows, 33 columns, 73 vendors, 43 countries, 2006–2015, 11.49% late); licence note: "U.S. federal government data; U.S. government works are not subject to copyright in the United States (17 U.S.C. §105)."
- [ ] **Step 4: Run the test and confirm it passes.**

### Task 2: Leakage-safe features

**Files:**
- Modify: `backend/ml/features.py`
- Test: `backend/tests/test_ml_features.py`

- [ ] **Step 1: Write the failing test**

```python
import math

import pandas as pd
import pytest

from ml.features import (
    FEATURE_COLUMNS,
    KNOWLEDGE_GAP_DAYS,
    ORDER_COLUMNS,
    build_training_frame,
    features_for_order,
)


def _orders(rows):
    frame = pd.DataFrame(rows, columns=ORDER_COLUMNS)
    frame["scheduled_date"] = pd.to_datetime(frame["scheduled_date"])
    frame["delivered_date"] = pd.to_datetime(frame["delivered_date"])
    return frame


ROWS = [
    ("A", "2020-01-01", "2020-01-05", 1000, 10, "Air", "Direct Drop"),    # late by 4
    ("A", "2020-03-01", "2020-03-01", 2000, 20, "Air", "Direct Drop"),    # on time
    ("A", "2020-06-01", "2020-06-20", 1500, 15, "Truck", "Direct Drop"),  # late by 19
    ("A", "2020-06-10", "2020-06-09", 1500, 15, "Truck", "Direct Drop"),  # on time
    ("B", "2020-02-01", "2020-02-01", 500, 5, None, "From RDC"),          # on time
]


def test_gap_constant():
    assert KNOWLEDGE_GAP_DAYS == 30


def test_first_order_has_no_history():
    frame = build_training_frame(_orders(ROWS))
    first = frame.loc[0]
    assert first["has_history"] == 0.0
    assert first["prior_count"] == 0
    assert math.isnan(first["prior_on_time_rate"])
    assert bool(first["late"]) is True


def test_prior_features_use_only_deliveries_before_the_cutoff():
    frame = build_training_frame(_orders(ROWS))
    second = frame.loc[1]          # cutoff 2020-01-31: knows order 0 only
    assert second["prior_count"] == 1
    assert second["prior_on_time_rate"] == 0.0
    assert second["prior_mean_delay_days"] == 4.0
    assert second["recent_late_rate"] == 1.0
    assert second["days_since_previous"] == 26
    third = frame.loc[2]           # cutoff 2020-05-02: knows orders 0 and 1
    assert third["prior_count"] == 2
    assert third["prior_on_time_rate"] == 0.5
    assert third["prior_mean_delay_days"] == 2.0
    assert third["days_since_previous"] == 62
    fourth = frame.loc[3]          # cutoff 2020-05-11: order 2 not yet delivered
    assert fourth["prior_count"] == 2


def test_a_later_outcome_never_changes_earlier_features():
    base = build_training_frame(_orders(ROWS))
    changed_rows = list(ROWS)
    changed_rows[3] = ("A", "2020-06-10", "2020-09-30", 1500, 15, "Truck", "Direct Drop")
    changed = build_training_frame(_orders(changed_rows))
    pd.testing.assert_frame_equal(
        base.loc[[0, 1, 2], FEATURE_COLUMNS], changed.loc[[0, 1, 2], FEATURE_COLUMNS]
    )
    assert bool(changed.loc[3, "late"]) is True


def test_suppliers_do_not_share_history_and_missing_mode_is_unknown():
    frame = build_training_frame(_orders(ROWS))
    other = frame.loc[4]
    assert other["prior_count"] == 0
    assert other["shipment_mode"] == "unknown"
    assert other["fulfil_via"] == "From RDC"
    assert list(frame.columns[: len(FEATURE_COLUMNS)]) == FEATURE_COLUMNS


def test_order_features_with_an_explicit_as_of_date():
    history = _orders(ROWS[:4])
    order = {"scheduled_date": pd.Timestamp("2020-07-01"), "order_value": 1000,
             "quantity": 10, "shipment_mode": "Air", "fulfil_via": "Direct Drop"}
    row = features_for_order(history, order, as_of=pd.Timestamp("2020-06-25")).iloc[0]
    assert row["prior_count"] == 4
    assert row["prior_on_time_rate"] == 0.5
    assert row["recent_late_rate"] == 0.5
    assert row["days_since_previous"] == 5
    assert row["log_order_value"] == pytest.approx(math.log1p(1000))


def test_order_features_default_to_the_training_cutoff():
    history = _orders(ROWS[:4])
    order = {"scheduled_date": pd.Timestamp("2020-07-01"), "order_value": 1000,
             "quantity": 10, "shipment_mode": None, "fulfil_via": None}
    row = features_for_order(history, order).iloc[0]    # cutoff 2020-06-01
    assert row["prior_count"] == 2
    assert row["shipment_mode"] == "unknown"


def test_empty_history_is_supported():
    empty = _orders([])
    order = {"scheduled_date": pd.Timestamp("2020-07-01"), "order_value": None,
             "quantity": None, "shipment_mode": "Air", "fulfil_via": "Direct Drop"}
    row = features_for_order(empty, order).iloc[0]
    assert row["has_history"] == 0.0
    assert math.isnan(row["log_order_value"])
```

- [ ] **Step 2: Run and confirm failures.**
- [ ] **Step 3: Implement** `build_training_frame` and `features_for_order` per **Semantics** (share one internal function so both compute identical values; vectorise per supplier).
- [ ] **Step 4: Run and confirm all pass.** Also time `build_training_frame(scms_orders(load_scms()))` and confirm < 10 s.

### Task 3: Training, evaluation, artifacts

**Files:**
- Create: `backend/ml/train_reliability.py`
- Test: `backend/tests/test_ml_training.py`

- [ ] **Step 1: Write the failing test**

```python
import json

import pytest

from ml.features import FEATURE_COLUMNS
from ml.scms import load_scms, scms_orders
from ml.train_reliability import save_artifacts, train_and_evaluate

REQUIRED = [
    "model_version", "model_name", "trained_at", "trained_on", "dataset_sha256",
    "feature_columns", "knowledge_gap_days", "decision_threshold", "base_late_rate",
    "sklearn_version", "train_rows", "test_rows", "train_period", "test_period",
    "cv", "test", "baselines", "risk_bands", "permutation_importance",
]


@pytest.fixture(scope="module")
def result():
    return train_and_evaluate(scms_orders(load_scms()), cv_folds=3)


def test_metadata_is_complete(result):
    meta = result.metadata
    for key in REQUIRED:
        assert key in meta, key
    assert meta["feature_columns"] == FEATURE_COLUMNS
    assert meta["model_name"] in {"logistic_regression", "random_forest", "hist_gradient_boosting"}
    assert "USAID SCMS" in meta["trained_on"]
    assert set(meta["cv"]) == {"logistic_regression", "random_forest", "hist_gradient_boosting"}


def test_time_split_keeps_the_future_out_of_training(result):
    meta = result.metadata
    assert meta["train_period"]["end"] < meta["test_period"]["start"]
    assert meta["test_period"]["start"].startswith("2014")
    assert meta["train_rows"] + meta["test_rows"] == 10324


def test_metrics_and_baselines_are_reported(result):
    test = result.metadata["test"]
    for key in ["roc_auc", "pr_auc", "macro_f1", "brier", "late_rate", "rows", "confusion_matrix"]:
        assert key in test, key
    assert 0.0 <= test["roc_auc"] <= 1.0
    assert "external_vendors" in test
    baselines = result.metadata["baselines"]
    assert baselines["always_on_time"]["roc_auc"] == 0.5
    assert baselines["always_on_time"]["pr_auc"] == pytest.approx(test["late_rate"], abs=1e-9)
    assert "prior_on_time_rate" in baselines
    bands = result.metadata["risk_bands"]
    assert bands["medium"] == pytest.approx(bands["high"] / 2)


def test_report_has_every_section(result):
    for heading in ["# Supplier late-delivery risk model", "## Dataset", "## Leakage controls",
                    "## Model selection (cross-validation)", "## Test period results",
                    "## Baselines", "## Feature importance", "## Limitations"]:
        assert heading in result.report_markdown, heading


def test_artifacts_are_written(result, tmp_path):
    save_artifacts(result, tmp_path)
    assert (tmp_path / "reliability_model.joblib").stat().st_size < 10 * 1024 * 1024
    meta = json.loads((tmp_path / "reliability_model.json").read_text(encoding="utf-8"))
    assert meta["model_version"] == result.metadata["model_version"]
    assert (tmp_path / "evaluation_report.md").read_text(encoding="utf-8").startswith("#")
```

- [ ] **Step 2: Run and confirm failure.**
- [ ] **Step 3: Implement** `ml/train_reliability.py` per **Semantics**, including `if __name__ == "__main__": raise SystemExit(main())`.
- [ ] **Step 4: Run the test and confirm it passes.**
- [ ] **Step 5: Produce the real artifacts** — `./.venv/Scripts/python.exe -m ml.train_reliability` → confirm the three files exist in `ml/artifacts/` and read `evaluation_report.md` end to end for correctness.

### Task 4: Inference

**Files:**
- Create: `backend/ml/reliability_model.py`
- Test: `backend/tests/test_ml_reliability_model.py`

- [ ] **Step 1: Write the failing test**

```python
import pandas as pd
import pytest

from ml.features import ORDER_COLUMNS
from ml.reliability_model import ReliabilityModel

AS_OF = pd.Timestamp("2025-05-15")
ORDER = {"scheduled_date": pd.Timestamp("2025-06-01"), "order_value": 5000.0,
         "quantity": 100.0, "shipment_mode": "Air", "fulfil_via": "Direct Drop"}


@pytest.fixture(scope="module")
def model():
    loaded = ReliabilityModel.load()
    assert loaded is not None, "run `python -m ml.train_reliability` first"
    return loaded


def _history(late_flags):
    start = pd.Timestamp("2024-01-01")
    rows = []
    for index, late in enumerate(late_flags):
        scheduled = start + pd.Timedelta(days=30 * index)
        delivered = scheduled + pd.Timedelta(days=12 if late else -1)
        rows.append(("S", scheduled, delivered, 5000.0, 100.0, "Air", "Direct Drop"))
    return pd.DataFrame(rows, columns=ORDER_COLUMNS)


def test_prediction_is_a_probability_with_provenance(model):
    prediction = model.predict_for_supplier(_history([False] * 10), ORDER, as_of=AS_OF)
    assert 0.0 <= prediction.late_probability <= 1.0
    assert prediction.on_time_probability == pytest.approx(1 - prediction.late_probability)
    assert prediction.risk_level in {"low", "medium", "high"}
    assert prediction.model_version == model.metadata["model_version"]
    assert prediction.history_count == 10
    assert "SCMS" in prediction.trained_on
    assert prediction.method == "ml_model"
    assert set(prediction.as_dict()) >= {"late_probability", "risk_level", "signals", "model_version"}


def test_a_consistently_late_supplier_scores_riskier_than_a_punctual_one(model):
    punctual = model.predict_for_supplier(_history([False] * 10), ORDER, as_of=AS_OF)
    late = model.predict_for_supplier(_history([True] * 10), ORDER, as_of=AS_OF)
    assert late.late_probability > punctual.late_probability


def test_signals_never_contradict_the_history(model):
    late = model.predict_for_supplier(_history([True] * 10), ORDER, as_of=AS_OF)
    assert any(s["direction"] == "raises_risk" for s in late.signals)
    assert not any(s["direction"] == "lowers_risk" for s in late.signals)
    punctual = model.predict_for_supplier(_history([False] * 10), ORDER, as_of=AS_OF)
    assert any(s["direction"] == "lowers_risk" for s in punctual.signals)
    assert not any(s["direction"] == "raises_risk" for s in punctual.signals)


def test_supplier_without_history_is_flagged(model):
    prediction = model.predict_for_supplier(_history([]), ORDER, as_of=AS_OF)
    assert prediction.history_count == 0
    assert any("No delivery history" in s["text"] for s in prediction.signals)


def test_missing_artifact_returns_none(tmp_path):
    assert ReliabilityModel.load(tmp_path) is None
```

- [ ] **Step 2: Run and confirm failure.**
- [ ] **Step 3: Implement** per **Semantics** (load with `joblib.load` and `json.loads`; `ARTIFACT_DIR = Path(__file__).parent / "artifacts"`).
- [ ] **Step 4: Run and confirm all pass.**

### Task 5: Price anomaly assessment

**Files:**
- Create: `backend/ml/anomaly.py`
- Test: `backend/tests/test_ml_anomaly.py`

- [ ] **Step 1: Write the failing test**

```python
import numpy as np

from ml.anomaly import MIN_SAMPLES, assess_price


def _history(n, center=100.0):
    rng = np.random.default_rng(0)
    return [float(v) for v in center * np.exp(rng.normal(0, 0.05, n))]


def test_too_little_history_returns_none():
    assert MIN_SAMPLES == 20
    assert assess_price(100.0, _history(MIN_SAMPLES - 1)) is None


def test_typical_price_is_normal():
    result = assess_price(101.0, _history(60))
    assert result["status"] == "NORMAL"
    assert result["method"] == "isolation_forest"
    assert result["sample_size"] == 60


def test_extreme_price_is_a_high_anomaly():
    result = assess_price(260.0, _history(60))
    assert result["status"] == "HIGH_ANOMALY"
    assert "median" in result["reason"]
    assert result["deviation_ratio"] > 1.0


def test_results_are_deterministic():
    history = _history(60)
    assert assess_price(130.0, history) == assess_price(130.0, history)


def test_zero_spread_history_still_flags_a_different_price():
    result = assess_price(150.0, [100.0] * 30)
    assert result["status"] != "NORMAL"
```

- [ ] **Step 2–4:** fail → implement per **Semantics** → pass.

### Task 6: Demand forecasting and analytics evaluation

**Files:**
- Create: `backend/ml/forecast.py`, `backend/ml/evaluate_analytics.py`
- Test: `backend/tests/test_ml_forecast.py`

- [ ] **Step 1: Write the failing test**

```python
import pandas as pd

from ml.forecast import MIN_MONTHS, forecast_demand, monthly_series, smape


def test_monthly_series_fills_missing_months_with_zero():
    series = monthly_series(pd.to_datetime(["2024-01-15", "2024-03-02"]), [10, 5])
    assert list(series.index.strftime("%Y-%m")) == ["2024-01", "2024-02", "2024-03"]
    assert list(series.values) == [10.0, 0.0, 5.0]


def test_short_history_is_reported_as_insufficient():
    dates = pd.date_range("2024-01-01", periods=MIN_MONTHS - 1, freq="MS")
    result = forecast_demand(monthly_series(dates, [5] * (MIN_MONTHS - 1)), horizon=3)
    assert result["status"] == "insufficient_data"
    assert result["history_months"] == MIN_MONTHS - 1


def test_seasonal_series_prefers_seasonal_naive():
    index = pd.date_range("2021-01-01", periods=36, freq="MS")
    values = [100.0 + 50.0 * (month.month in (6, 7, 8)) for month in index]
    result = forecast_demand(pd.Series(values, index=index), horizon=3)
    assert result["status"] == "ok"
    assert result["method"] == "seasonal_naive"
    assert result["backtest_smape"]["seasonal_naive"] <= result["backtest_smape"]["linear_trend"]
    assert [p["month"] for p in result["forecast"]] == ["2024-01", "2024-02", "2024-03"]
    assert all(p["quantity"] >= 0 for p in result["forecast"])


def test_smape_handles_zeros():
    assert smape([0, 0], [0, 0]) == 0.0
    assert smape([10], [0]) == 200.0
```

- [ ] **Step 2–4:** fail → implement `ml/forecast.py` → pass.
- [ ] **Step 5:** implement `ml/evaluate_analytics.py` per **Semantics** with `if __name__ == "__main__": raise SystemExit(main())`; run `./.venv/Scripts/python.exe -m ml.evaluate_analytics`; read `ml/artifacts/analytics_evaluation.md` end to end.

### Task 7: Final verification

- [ ] Run `./.venv/Scripts/python.exe -m pytest tests/test_ml_*.py -q -p no:cacheprovider --noconftest` → all pass; paste the summary line in your report.
- [ ] Confirm `git status` is not needed — do **not** run git.
- [ ] Report back: files created; test summary; the test-period metrics table and both baselines exactly as measured; the winning model; `analytics_evaluation.md` headline numbers; anything surprising or any test you could not satisfy and why.
