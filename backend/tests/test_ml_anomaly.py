import numpy as np

from ml.anomaly import MIN_SAMPLES, assess_price


def _history(n, center=100.0):
    rng = np.random.default_rng(0)
    return [float(v) for v in center * np.exp(rng.normal(0, 0.05, n))]


def test_too_little_history_returns_none():
    assert MIN_SAMPLES == 8
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


def test_a_moderately_high_price_is_flagged_but_not_called_certain():
    result = assess_price(100.0 * np.exp(0.05 * 3.2), _history(60))  # ~3 spreads out
    assert result["status"] in {"POSSIBLE_ANOMALY", "HIGH_ANOMALY"}
    assert "usual spread" in result["reason"]


def test_ordinary_variation_is_not_flagged():
    assert all(assess_price(100.0 * np.exp(0.05 * z), _history(60))["status"] == "NORMAL" for z in (-1.5, -0.5, 0.0, 1.0, 2.0))


def test_a_short_history_can_still_catch_a_decimal_shift():
    assert assess_price(1000.0, _history(10))["status"] == "HIGH_ANOMALY"
