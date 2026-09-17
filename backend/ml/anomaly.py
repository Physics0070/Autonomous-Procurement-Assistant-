"""Isolation Forest assessment of one unit price against a product's price history."""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from sklearn.ensemble import IsolationForest

MIN_SAMPLES = 20
HIGH_PERCENTILE = 2
POSSIBLE_PERCENTILE = 10
ZERO_SPREAD_TOLERANCE = 0.01


def _positive(values) -> np.ndarray:
    array = np.asarray([v for v in values if v is not None], dtype=float)
    return array[np.isfinite(array) & (array > 0)]


def assess_price(unit_price: float, history_prices: Sequence[float]) -> dict | None:
    """Classify ``unit_price`` as NORMAL, POSSIBLE_ANOMALY or HIGH_ANOMALY.

    Returns ``None`` when there are fewer than ``MIN_SAMPLES`` positive past prices or the
    new price is not a positive number. The feature is ``log(price / median(history))``;
    the new price's Isolation Forest score is compared with the scores of the past prices.
    """
    history = _positive(history_prices)
    if len(history) < MIN_SAMPLES or unit_price is None:
        return None
    price = float(unit_price)
    if not (np.isfinite(price) and price > 0):
        return None

    median = float(np.median(history))
    past = np.log(history / median).reshape(-1, 1)
    model = IsolationForest(n_estimators=200, random_state=42).fit(past)
    past_scores = model.score_samples(past)
    score = float(model.score_samples(np.array([[np.log(price / median)]]))[0])
    ratio = price / median
    comparison = f"{ratio:.2f} times the median of {len(history)} past prices ({median:,.4g})"

    if np.ptp(past) == 0:
        if abs(ratio - 1) > ZERO_SPREAD_TOLERANCE:
            status = "POSSIBLE_ANOMALY"
            reason = (f"Unit price {price:,.4g} is {comparison}, and every past price "
                      f"was the same.")
        else:
            status = "NORMAL"
            reason = f"Unit price {price:,.4g} matches the median of {len(history)} identical past prices."
    elif score < np.percentile(past_scores, HIGH_PERCENTILE):
        status = "HIGH_ANOMALY"
        reason = (f"Unit price {price:,.4g} is {comparison}; it is more unusual than "
                  f"{100 - HIGH_PERCENTILE}% of past prices.")
    elif score < np.percentile(past_scores, POSSIBLE_PERCENTILE):
        status = "POSSIBLE_ANOMALY"
        reason = (f"Unit price {price:,.4g} is {comparison}; it is more unusual than "
                  f"{100 - POSSIBLE_PERCENTILE}% of past prices.")
    else:
        status = "NORMAL"
        reason = f"Unit price {price:,.4g} is {comparison}, within the usual range."

    return {
        "status": status,
        "method": "isolation_forest",
        "score": score,
        "sample_size": int(len(history)),
        "median": median,
        "deviation_ratio": ratio,
        "reason": reason,
    }
