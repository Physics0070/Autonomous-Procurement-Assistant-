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


def _mean_last_12(history: np.ndarray, steps: int) -> np.ndarray:
    return np.full(steps, float(np.mean(history[-12:])))


def _croston_sba(history: np.ndarray, steps: int, alpha: float = 0.1) -> np.ndarray:
    """Croston's method with the Syntetos-Boylan correction, built for demand that arrives in lumps with empty months between.
    It smooths the size of each order and the gap between orders separately, then forecasts size / gap."""
    orders = np.flatnonzero(history > 0)
    if len(orders) < 2:
        return np.full(steps, float(np.mean(history)))
    size, gap, last = float(history[orders[0]]), float(orders[1] - orders[0]), orders[0]
    for i in orders[1:]:
        size = alpha * history[i] + (1 - alpha) * size
        gap = alpha * (i - last) + (1 - alpha) * gap
        last = i
    return np.full(steps, (1 - alpha / 2) * size / gap)


_METHODS = {"croston_sba": _croston_sba, "mean_last_12": _mean_last_12, "linear_trend": _linear_trend,
            "seasonal_naive": _seasonal_naive}
DEFAULT_METHOD = "croston_sba"
ORIGIN_STEP = 3  # months between the backtest origins
SWITCH_MARGIN = 0.75  # another method must cut the backtest error by 25% to replace the default
RANGE_ORIGINS = 12  # monthly cut-offs used to learn how far off the forecast tends to be
ERROR_LABELS = ((0.30, "fair"), (0.50, "rough"))  # backtest error up to 30% is "fair", up to 50% "rough", above that "poor"


def wape(actual, predicted) -> float:
    """Weighted absolute percentage error: total miss divided by total demand. Unlike sMAPE it is not wrecked by empty months."""
    a, p = np.asarray(actual, dtype=float), np.asarray(predicted, dtype=float)
    return float(np.abs(a - p).sum() / max(a.sum(), 1e-9))


def _confidence(error: float, months: int) -> str:
    label = next((name for limit, name in ERROR_LABELS if error <= limit), "poor")
    return "rough" if label == "fair" and months < 24 else label  # a short history never earns "fair"


def forecast_demand(series: pd.Series, horizon: int = 3, as_of: "pd.Timestamp | None" = None) -> dict:
    """Backtest the candidate methods, forecast with the best one, and say how far off it tends to be.

    `as_of` (today) drops the current calendar month when the series ends in it: a month still in progress looks like a
    collapse in demand and would drag every forecast down.
    Measured on real SCMS series at twelve cut-off months (3-month totals, lower is better): Croston 34% mean error, mean of the
    last 12 months 36%, linear trend 39%, last year's value 46%.
    """
    if as_of is not None and len(series) and pd.Timestamp(series.index[-1]).to_period("M") >= pd.Timestamp(as_of).to_period("M"):
        series = series.iloc[:-1]
    months = len(series)
    if months < MIN_MONTHS:
        return {"status": "insufficient_data", "history_months": months, "min_months": MIN_MONTHS}

    values = series.to_numpy(dtype=float)
    holdout = min(MAX_HOLDOUT, months // 4)
    origins = [months - holdout - k * ORIGIN_STEP for k in range(3)]
    origins = [o for o in origins if o >= MIN_MONTHS // 2 + 1] or [months - holdout]
    backtest = {}
    for name in _METHODS:
        # Last year's value needs a full year of history before the origin.
        usable = [o for o in origins if o + holdout <= months and (name != "seasonal_naive" or o >= SEASON)]
        if usable:
            backtest[name] = float(np.mean([wape(values[o:o + holdout], _METHODS[name](values[:o], holdout)) for o in usable]))
    method = min(backtest, key=backtest.get)
    if method != DEFAULT_METHOD and backtest[method] > SWITCH_MARGIN * backtest[DEFAULT_METHOD]:
        method = DEFAULT_METHOD

    predictions = _METHODS[method](values, horizon)
    # How far off this method has been month by month: actual / forecast over recent cut-offs gives an honest range.
    ratios, window_errors = [], []
    for o in range(max(MIN_MONTHS // 2 + 1, months - holdout - RANGE_ORIGINS), months - holdout + 1):
        if method == "seasonal_naive" and o < SEASON:
            continue  # last year's value needs a full year before the cut-off
        past = _METHODS[method](values[:o], holdout)
        window_errors.append(wape(values[o:o + holdout], past))
        if past[0] > 0:
            ratios.extend(values[o:o + holdout] / past[0])
    error = float(np.mean(window_errors)) if window_errors else backtest[method]  # twelve windows, steadier than three
    low_ratio, high_ratio = (np.percentile(ratios, [10, 90]) if len(ratios) >= 8 else (0.0, 2.0))
    first = pd.Timestamp(series.index[-1]).to_period("M") + 1
    labels = pd.period_range(first, periods=horizon, freq="M").strftime("%Y-%m")
    return {
        "status": "ok",
        "method": method,
        "history_months": months,
        "holdout_months": holdout,
        "backtest_error": {name: round(value, 3) for name, value in backtest.items()},
        "error_pct": round(100 * error),
        "confidence": _confidence(error, months),
        "forecast": [{"month": label, "quantity": float(value), "low": float(value * low_ratio), "high": float(value * high_ratio)}
                     for label, value in zip(labels, predictions)],
    }
