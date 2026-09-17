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
