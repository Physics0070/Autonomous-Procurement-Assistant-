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
