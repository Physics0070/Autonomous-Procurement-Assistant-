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
    assert result["backtest_error"]["seasonal_naive"] <= result["backtest_error"]["croston_sba"]
    assert [p["month"] for p in result["forecast"]] == ["2024-01", "2024-02", "2024-03"]
    assert all(p["quantity"] >= 0 for p in result["forecast"])


def test_smape_handles_zeros():
    assert smape([0, 0], [0, 0]) == 0.0
    assert smape([10], [0]) == 200.0


def test_a_noisy_flat_series_is_forecast_by_a_recent_level_not_a_trend_line():
    import numpy as np

    rng = np.random.default_rng(0)
    index = pd.date_range("2022-01-01", periods=30, freq="MS")
    values = 100 + rng.normal(0, 40, size=30).clip(-90)
    result = forecast_demand(pd.Series(values, index=index), horizon=3)
    assert result["method"] in {"croston_sba", "mean_last_12", "linear_trend", "seasonal_naive"}
    assert set(result["backtest_error"]) >= {"croston_sba", "mean_last_12", "linear_trend"}
    assert all(p["quantity"] >= 0 for p in result["forecast"])


def test_a_noisy_flat_series_defaults_to_croston_and_gives_an_honest_range():
    import numpy as np

    rng = np.random.default_rng(3)
    index = pd.date_range("2022-01-01", periods=36, freq="MS")
    result = forecast_demand(pd.Series(100 + rng.normal(0, 40, 36).clip(-90), index=index), horizon=3)
    assert result["method"] == "croston_sba"
    for point in result["forecast"]:
        assert point["low"] <= point["quantity"] * 1.0001 and point["high"] >= point["quantity"] * 0.9999
        assert point["low"] >= 0
    assert result["confidence"] in {"fair", "rough", "poor"} and 0 <= result["error_pct"]


def test_a_short_history_never_earns_the_label_fair():
    index = pd.date_range("2024-01-01", periods=14, freq="MS")
    result = forecast_demand(pd.Series([100.0] * 14, index=index), horizon=3)
    assert result["confidence"] != "fair"


def test_the_month_still_in_progress_is_left_out():
    index = pd.date_range("2025-01-01", periods=18, freq="MS")  # ends 2026-06
    values = pd.Series([100.0] * 17 + [3.0], index=index)  # the last month has barely started
    full = forecast_demand(values, horizon=1)
    trimmed = forecast_demand(values, horizon=1, as_of=pd.Timestamp("2026-06-15"))
    assert trimmed["history_months"] == 17 and trimmed["forecast"][0]["month"] == "2026-06"
    assert trimmed["forecast"][0]["quantity"] > full["forecast"][0]["quantity"]
