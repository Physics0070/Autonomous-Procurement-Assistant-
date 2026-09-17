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
