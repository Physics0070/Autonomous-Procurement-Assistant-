import math

import pandas as pd
import pytest

from ml.features import (
    FEATURE_COLUMNS,
    KNOWLEDGE_GAP_DAYS,
    ORDER_COLUMNS,
    build_training_frame,
    features_for_order,
)


def _orders(rows):
    frame = pd.DataFrame(rows, columns=ORDER_COLUMNS)
    frame["scheduled_date"] = pd.to_datetime(frame["scheduled_date"])
    frame["delivered_date"] = pd.to_datetime(frame["delivered_date"])
    return frame


ROWS = [
    ("A", "2020-01-01", "2020-01-05", 1000, 10, "Air", "Direct Drop"),    # late by 4
    ("A", "2020-03-01", "2020-03-01", 2000, 20, "Air", "Direct Drop"),    # on time
    ("A", "2020-06-01", "2020-06-20", 1500, 15, "Truck", "Direct Drop"),  # late by 19
    ("A", "2020-06-10", "2020-06-09", 1500, 15, "Truck", "Direct Drop"),  # on time
    ("B", "2020-02-01", "2020-02-01", 500, 5, None, "From RDC"),          # on time
]


def test_gap_constant():
    assert KNOWLEDGE_GAP_DAYS == 30


def test_first_order_has_no_history():
    frame = build_training_frame(_orders(ROWS))
    first = frame.loc[0]
    assert first["has_history"] == 0.0
    assert first["prior_count"] == 0
    assert math.isnan(first["prior_on_time_rate"])
    assert bool(first["late"]) is True


def test_prior_features_use_only_deliveries_before_the_cutoff():
    frame = build_training_frame(_orders(ROWS))
    second = frame.loc[1]          # cutoff 2020-01-31: knows order 0 only
    assert second["prior_count"] == 1
    assert second["prior_on_time_rate"] == 0.0
    assert second["prior_mean_delay_days"] == 4.0
    assert second["recent_late_rate"] == 1.0
    assert second["days_since_previous"] == 26
    third = frame.loc[2]           # cutoff 2020-05-02: knows orders 0 and 1
    assert third["prior_count"] == 2
    assert third["prior_on_time_rate"] == 0.5
    assert third["prior_mean_delay_days"] == 2.0
    assert third["days_since_previous"] == 62
    fourth = frame.loc[3]          # cutoff 2020-05-11: order 2 not yet delivered
    assert fourth["prior_count"] == 2


def test_a_later_outcome_never_changes_earlier_features():
    base = build_training_frame(_orders(ROWS))
    changed_rows = list(ROWS)
    changed_rows[3] = ("A", "2020-06-10", "2020-09-30", 1500, 15, "Truck", "Direct Drop")
    changed = build_training_frame(_orders(changed_rows))
    pd.testing.assert_frame_equal(
        base.loc[[0, 1, 2], FEATURE_COLUMNS], changed.loc[[0, 1, 2], FEATURE_COLUMNS]
    )
    assert bool(changed.loc[3, "late"]) is True


def test_suppliers_do_not_share_history_and_missing_mode_is_unknown():
    frame = build_training_frame(_orders(ROWS))
    other = frame.loc[4]
    assert other["prior_count"] == 0
    assert other["shipment_mode"] == "unknown"
    assert other["fulfil_via"] == "From RDC"
    assert list(frame.columns[: len(FEATURE_COLUMNS)]) == FEATURE_COLUMNS


def test_order_features_with_an_explicit_as_of_date():
    history = _orders(ROWS[:4])
    order = {"scheduled_date": pd.Timestamp("2020-07-01"), "order_value": 1000,
             "quantity": 10, "shipment_mode": "Air", "fulfil_via": "Direct Drop"}
    row = features_for_order(history, order, as_of=pd.Timestamp("2020-06-25")).iloc[0]
    assert row["prior_count"] == 4
    assert row["prior_on_time_rate"] == 0.5
    assert row["recent_late_rate"] == 0.5
    assert row["days_since_previous"] == 5
    assert row["log_order_value"] == pytest.approx(math.log1p(1000))


def test_order_features_default_to_the_training_cutoff():
    history = _orders(ROWS[:4])
    order = {"scheduled_date": pd.Timestamp("2020-07-01"), "order_value": 1000,
             "quantity": 10, "shipment_mode": None, "fulfil_via": None}
    row = features_for_order(history, order).iloc[0]    # cutoff 2020-06-01
    assert row["prior_count"] == 2
    assert row["shipment_mode"] == "unknown"


def test_empty_history_is_supported():
    empty = _orders([])
    order = {"scheduled_date": pd.Timestamp("2020-07-01"), "order_value": None,
             "quantity": None, "shipment_mode": "Air", "fulfil_via": "Direct Drop"}
    row = features_for_order(empty, order).iloc[0]
    assert row["has_history"] == 0.0
    assert math.isnan(row["log_order_value"])
