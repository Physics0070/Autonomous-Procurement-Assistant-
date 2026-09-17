"""Monthly demand series, backtesting and simple forecasts."""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

MIN_MONTHS = 12
MAX_HOLDOUT = 6
SEASON = 12


def smape(actual: Sequence[float], predicted: Sequence[float]) -> float:
    """Symmetric MAPE in percent (0-200); a 0/0 term counts as 0."""
    a = np.asarray(actual, dtype=float)
    f = np.asarray(predicted, dtype=float)
    if a.shape != f.shape or a.size == 0:
        raise ValueError("actual and predicted must be non-empty and the same length")
    denominator = np.abs(a) + np.abs(f)
    safe = np.where(denominator == 0, 1.0, denominator)
    terms = np.where(denominator == 0, 0.0, 200.0 * np.abs(a - f) / safe)
    return float(terms.mean())


def monthly_series(dates: Sequence, quantities: Sequence[float]) -> pd.Series:
    """Summed quantity per calendar month (month-start index, zeros for empty months)."""
    frame = pd.DataFrame({
        "date": pd.to_datetime(pd.Series(list(dates)), utc=True).dt.tz_localize(None),
        "quantity": pd.to_numeric(pd.Series(list(quantities), dtype=object),
                                  errors="coerce").astype(float),
    }).dropna()
    if frame.empty:
        return pd.Series([], index=pd.DatetimeIndex([], freq="MS"), dtype=float, name="quantity")
    months = frame["date"].dt.to_period("M").dt.to_timestamp()
    totals = frame["quantity"].groupby(months).sum()
    index = pd.date_range(totals.index.min(), totals.index.max(), freq="MS")
    return totals.reindex(index, fill_value=0.0).astype(float).rename("quantity")


def _linear_trend(history: np.ndarray, steps: int) -> np.ndarray:
    model = LinearRegression().fit(np.arange(len(history)).reshape(-1, 1), history)
    future = np.arange(len(history), len(history) + steps).reshape(-1, 1)
    return np.clip(model.predict(future), 0.0, None)


def _seasonal_naive(history: np.ndarray, steps: int) -> np.ndarray:
    extended = list(history)
    for _ in range(steps):
        extended.append(extended[-SEASON])
    return np.clip(np.asarray(extended[len(history):], dtype=float), 0.0, None)


_METHODS = {"linear_trend": _linear_trend, "seasonal_naive": _seasonal_naive}


def forecast_demand(series: pd.Series, horizon: int = 3) -> dict:
    """Backtest linear-trend and seasonal-naive forecasts, then forecast with the better one."""
    months = len(series)
    if months < MIN_MONTHS:
        return {"status": "insufficient_data", "history_months": months,
                "min_months": MIN_MONTHS}

    values = series.to_numpy(dtype=float)
    holdout = min(MAX_HOLDOUT, months // 4)
    train, actual = values[:-holdout], values[-holdout:]
    methods = ["linear_trend"]
    if months >= SEASON + holdout:
        methods.append("seasonal_naive")
    backtest = {name: smape(actual, _METHODS[name](train, holdout)) for name in methods}
    method = min(backtest, key=lambda name: (backtest[name], name != "seasonal_naive"))

    predictions = _METHODS[method](values, horizon)
    first = pd.Timestamp(series.index[-1]).to_period("M") + 1
    labels = pd.period_range(first, periods=horizon, freq="M").strftime("%Y-%m")
    return {
        "status": "ok",
        "method": method,
        "history_months": months,
        "holdout_months": holdout,
        "backtest_smape": backtest,
        "forecast": [{"month": label, "quantity": float(value)}
                     for label, value in zip(labels, predictions)],
    }
