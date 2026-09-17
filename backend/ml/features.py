"""Leakage-safe feature engineering for supplier order histories.

Every feature for an order is computed only from the same supplier's orders that
were delivered strictly before the order's knowledge cutoff
(``scheduled_date - KNOWLEDGE_GAP_DAYS`` during training). The late label is never
an input for the order itself.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ORDER_COLUMNS = ["supplier_key", "scheduled_date", "delivered_date",
                 "order_value", "quantity", "shipment_mode", "fulfil_via"]
NUMERIC_FEATURES = ["has_history", "prior_count", "prior_on_time_rate",
                    "prior_mean_delay_days", "recent_late_rate", "days_since_previous",
                    "log_order_value", "log_quantity"]
CATEGORICAL_FEATURES = ["shipment_mode", "fulfil_via"]
FEATURE_COLUMNS = NUMERIC_FEATURES + CATEGORICAL_FEATURES
KNOWLEDGE_GAP_DAYS = 30
RECENT_WINDOW = 10

_PRIOR_FEATURES = ["has_history", "prior_count", "prior_on_time_rate",
                   "prior_mean_delay_days", "recent_late_rate", "days_since_previous"]
_ONE_DAY = np.timedelta64(1, "D")
_NS = "datetime64[ns]"


def _datetimes(values) -> np.ndarray:
    """Naive (UTC) datetime64[ns] array; timezone-aware input is converted to UTC."""
    parsed = pd.to_datetime(pd.Series(values), utc=True).dt.tz_localize(None)
    return parsed.to_numpy(dtype=_NS)


def _timestamp(value) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if stamp is pd.NaT:
        return stamp
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert("UTC").tz_localize(None)
    return stamp


def _completed_history(history: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Delivered dates, late flags and delay days of orders with both dates known."""
    scheduled = _datetimes(history["scheduled_date"])
    delivered = _datetimes(history["delivered_date"])
    valid = ~(np.isnat(scheduled) | np.isnat(delivered))
    scheduled, delivered = scheduled[valid], delivered[valid]
    late = delivered > scheduled
    delay_days = (delivered - scheduled) / _ONE_DAY
    return delivered, late, delay_days


def _prior_features(delivered: np.ndarray, late: np.ndarray, delay_days: np.ndarray,
                    cutoffs: np.ndarray) -> dict[str, np.ndarray]:
    """History features for each cutoff, from one supplier's completed orders."""
    size = len(cutoffs)
    out = {name: np.full(size, np.nan) for name in _PRIOR_FEATURES}
    out["has_history"] = np.zeros(size)
    out["prior_count"] = np.zeros(size)
    if len(delivered) == 0 or size == 0:
        return out

    order = np.argsort(delivered, kind="stable")
    delivered = delivered[order]
    late_sum = np.concatenate(([0.0], np.cumsum(late[order].astype(float))))
    delay_sum = np.concatenate(([0.0], np.cumsum(np.clip(delay_days[order], 0, None))))

    # Number of orders delivered strictly before each cutoff.
    counts = np.searchsorted(delivered, cutoffs, side="left")
    known = counts > 0
    count = counts[known]
    start = np.maximum(count - RECENT_WINDOW, 0)

    out["has_history"] = known.astype(float)
    out["prior_count"] = counts.astype(float)
    out["prior_on_time_rate"][known] = (count - late_sum[count]) / count
    out["prior_mean_delay_days"][known] = delay_sum[count] / count
    out["recent_late_rate"][known] = (late_sum[count] - late_sum[start]) / (count - start)
    out["days_since_previous"][known] = (cutoffs[known] - delivered[count - 1]) / _ONE_DAY
    return out


def _log_non_negative(values) -> np.ndarray:
    numbers = pd.to_numeric(pd.Series(values, dtype=object), errors="coerce").to_numpy(float)
    return np.log1p(np.maximum(numbers, 0.0))


def _category(values) -> np.ndarray:
    text = pd.Series(values, dtype=object).astype("string").str.strip()
    return text.fillna("unknown").replace("", "unknown").astype(object).to_numpy()


def _assemble(prior: dict[str, np.ndarray], order_value, quantity, shipment_mode,
              fulfil_via, index) -> pd.DataFrame:
    frame = pd.DataFrame(prior, index=index)
    frame["log_order_value"] = _log_non_negative(order_value)
    frame["log_quantity"] = _log_non_negative(quantity)
    frame["shipment_mode"] = _category(shipment_mode)
    frame["fulfil_via"] = _category(fulfil_via)
    return frame[FEATURE_COLUMNS]


def build_training_frame(orders: pd.DataFrame) -> pd.DataFrame:
    """Features, label and split keys for every order (same index as ``orders``)."""
    scheduled = _datetimes(orders["scheduled_date"])
    delivered = _datetimes(orders["delivered_date"])
    cutoffs = scheduled - np.timedelta64(KNOWLEDGE_GAP_DAYS, "D")

    prior = {name: np.full(len(orders), np.nan) for name in _PRIOR_FEATURES}
    prior["has_history"][:] = 0.0
    prior["prior_count"][:] = 0.0
    groups = orders.reset_index(drop=True).groupby("supplier_key", sort=False).indices
    for positions in groups.values():
        history = pd.DataFrame({"scheduled_date": scheduled[positions],
                                "delivered_date": delivered[positions]})
        values = _prior_features(*_completed_history(history), cutoffs[positions])
        for name, column in values.items():
            prior[name][positions] = column

    frame = _assemble(prior, orders["order_value"].to_numpy(), orders["quantity"].to_numpy(),
                      orders["shipment_mode"].to_numpy(), orders["fulfil_via"].to_numpy(),
                      orders.index)
    frame["late"] = delivered > scheduled
    frame["scheduled_date"] = scheduled
    frame["supplier_key"] = orders["supplier_key"].to_numpy()
    return frame


def features_for_order(history: pd.DataFrame, order: dict,
                       as_of: pd.Timestamp | None = None) -> pd.DataFrame:
    """One-row ``FEATURE_COLUMNS`` frame for a new order of the supplier in ``history``.

    ``history`` holds that supplier's completed orders (``ORDER_COLUMNS``; may be empty).
    The knowledge cutoff is ``as_of`` when given, else ``scheduled_date - KNOWLEDGE_GAP_DAYS``.
    """
    anchor = _timestamp(as_of if as_of is not None else order.get("scheduled_date"))
    if anchor is pd.NaT:
        raise ValueError("order needs a scheduled_date (or pass as_of)")
    # numpy arithmetic with explicit units (pd.Timedelta(days=...) warns under numpy 2.5).
    cutoffs = np.array([anchor.to_datetime64()]).astype(_NS)
    if as_of is None:
        cutoffs = cutoffs - np.timedelta64(KNOWLEDGE_GAP_DAYS, "D")
    prior = _prior_features(*_completed_history(history), cutoffs)
    return _assemble(prior, [order.get("order_value")], [order.get("quantity")],
                     [order.get("shipment_mode")], [order.get("fulfil_via")], pd.RangeIndex(1))
