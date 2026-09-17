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
