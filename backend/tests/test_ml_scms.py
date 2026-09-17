import pandas as pd
import pytest

from ml.scms import DATASET_SHA256, load_scms, scms_orders
from ml.features import ORDER_COLUMNS


@pytest.fixture(scope="module")
def scms():
    return load_scms()


def test_loads_every_shipment_with_parsed_dates(scms):
    assert len(scms) == 10324
    assert scms["scheduled_date"].notna().all()
    assert scms["delivered_date"].notna().all()
    assert pd.api.types.is_datetime64_any_dtype(scms["scheduled_date"])


def test_late_label_matches_the_verified_rate(scms):
    assert round(scms["late"].mean(), 4) == 0.1149
    assert (scms.loc[scms["late"], "delay_days"] > 0).all()
    assert (scms.loc[~scms["late"], "delay_days"] <= 0).all()


def test_text_placeholders_become_missing_values(scms):
    assert pd.api.types.is_float_dtype(scms["freight_usd"])
    assert scms["freight_usd"].isna().sum() > 1000
    assert set(scms["fulfil_via"].unique()) == {"Direct Drop", "From RDC"}
    assert (scms["shipment_mode"] == "unknown").sum() == 360
    assert scms["country"].str.contains("Ivoire").any()


def test_checksum_mismatch_is_rejected(tmp_path):
    bad = tmp_path / "scms.csv"
    bad.write_text("ID\n1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        load_scms(bad)


def test_orders_view_uses_the_generic_schema(scms):
    orders = scms_orders(scms)
    assert list(orders.columns) == ORDER_COLUMNS
    assert len(orders) == len(scms)
    assert DATASET_SHA256.startswith("918b992d")
