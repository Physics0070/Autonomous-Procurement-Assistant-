"""Price anomaly detection.

Starts simple and honest: historical mean + Z-score, with an explicit
"insufficient history" state so a single prior observation is never dressed up
as a statistical finding. Designed so Isolation Forest (or similar) can be
added later behind the same interface.
"""
from __future__ import annotations

import statistics
from enum import Enum
from typing import Any, Optional, Sequence


class AnomalyStatus(str, Enum):
    NORMAL = "NORMAL"
    POSSIBLE_ANOMALY = "POSSIBLE_ANOMALY"
    HIGH_ANOMALY = "HIGH_ANOMALY"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


# Minimum prior observations before a Z-score means anything.
MIN_SAMPLES = 3
POSSIBLE_Z = 2.0
HIGH_Z = 3.0
# With few samples, fall back to a ratio test against the mean.
POSSIBLE_RATIO = 0.35
HIGH_RATIO = 0.60


def detect_price_anomaly(
    unit_price: Optional[float],
    history: Optional[Sequence[float]] = None,
    *,
    stats: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Classify a unit price against historical prices for the same product.

    `history` is a list of prior unit prices; `stats` is a pre-aggregated
    {mean, stdev, count} (as returned by the repository) for the same purpose.
    """
    if unit_price is None:
        return {
            "status": AnomalyStatus.INSUFFICIENT_DATA.value,
            "reason": "No unit price available to evaluate.",
            "sample_size": 0,
        }

    if stats:
        mean = stats.get("mean")
        stdev = stats.get("stdev")
        count = int(stats.get("count") or 0)
    elif history:
        values = [float(v) for v in history if v is not None]
        count = len(values)
        mean = statistics.fmean(values) if values else None
        stdev = statistics.stdev(values) if count >= 2 else 0.0
    else:
        count, mean, stdev = 0, None, None

    if not count or mean is None or mean <= 0:
        return {
            "status": AnomalyStatus.INSUFFICIENT_DATA.value,
            "reason": "No price history for this product yet.",
            "sample_size": count,
        }

    deviation_ratio = (unit_price - mean) / mean

    if count < MIN_SAMPLES or not stdev:
        # Not enough data for a Z-score; use a plain deviation test and say so.
        magnitude = abs(deviation_ratio)
        if magnitude >= HIGH_RATIO:
            status = AnomalyStatus.HIGH_ANOMALY
        elif magnitude >= POSSIBLE_RATIO:
            status = AnomalyStatus.POSSIBLE_ANOMALY
        else:
            status = AnomalyStatus.NORMAL
        return {
            "status": status.value,
            "method": "deviation_ratio",
            "reason": (
                f"Price is {deviation_ratio:+.1%} versus a historical mean of {mean:,.2f} "
                f"from only {count} observation(s); treat with caution."
            ),
            "mean": round(mean, 4),
            "deviation_ratio": round(deviation_ratio, 4),
            "sample_size": count,
            "z_score": None,
        }

    z_score = (unit_price - mean) / stdev
    magnitude = abs(z_score)
    if magnitude >= HIGH_Z:
        status = AnomalyStatus.HIGH_ANOMALY
    elif magnitude >= POSSIBLE_Z:
        status = AnomalyStatus.POSSIBLE_ANOMALY
    else:
        status = AnomalyStatus.NORMAL

    return {
        "status": status.value,
        "method": "z_score",
        "reason": (
            f"Price {unit_price:,.2f} is {deviation_ratio:+.1%} versus the historical mean "
            f"{mean:,.2f} (z = {z_score:+.2f}, n = {count})."
        ),
        "mean": round(mean, 4),
        "stdev": round(stdev, 4),
        "z_score": round(z_score, 4),
        "deviation_ratio": round(deviation_ratio, 4),
        "sample_size": count,
    }


def worst_status(statuses: Sequence[str]) -> str:
    order = [
        AnomalyStatus.HIGH_ANOMALY.value,
        AnomalyStatus.POSSIBLE_ANOMALY.value,
        AnomalyStatus.NORMAL.value,
        AnomalyStatus.INSUFFICIENT_DATA.value,
    ]
    for candidate in order:
        if candidate in statuses:
            return candidate
    return AnomalyStatus.INSUFFICIENT_DATA.value
