"""Load, verify and clean the USAID SCMS Delivery History dataset.

The raw file mixes numbers with text placeholders (for example
"Freight Included in Commodity Cost"); those cells become NaN here.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

from ml.features import ORDER_COLUMNS

DATASET_PATH = Path(__file__).resolve().parent / "data" / "SCMS_Delivery_History_Dataset.csv"
DATASET_SHA256 = "918b992dd3e8d4b64d2a727b2c4ea607603d0c58f19484e73f7b78528c6a8673"

_DATE_FORMAT = "%d-%b-%y"  # e.g. "2-Jun-06"

_TEXT_COLUMNS = {
    "Vendor": "vendor",
    "Country": "country",
    "Fulfill Via": "fulfil_via",
    "Product Group": "product_group",
    "Molecule/Test Type": "product",
    "Item Description": "item_description",
    "Dosage Form": "dosage_form",
}
_NUMBER_COLUMNS = {
    "Line Item Quantity": "quantity",
    "Line Item Value": "order_value",
    "Unit Price": "unit_price",
    "Pack Price": "pack_price",
    "Weight (Kilograms)": "weight_kg",
    "Freight Cost (USD)": "freight_usd",
}
_OUTPUT_COLUMNS = [
    "shipment_id", "vendor", "country", "shipment_mode", "fulfil_via", "product_group",
    "product", "item_description", "dosage_form", "scheduled_date", "delivered_date",
    "quantity", "order_value", "unit_price", "pack_price", "weight_kg", "freight_usd",
    "late", "delay_days",
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_raw(path: Path) -> pd.DataFrame:
    try:
        frame = pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    except UnicodeDecodeError:
        frame = pd.read_csv(path, encoding="latin-1", dtype=str, keep_default_na=False)
    frame.columns = [str(column).replace("﻿", "").strip() for column in frame.columns]
    return frame


def _to_number(values: pd.Series) -> pd.Series:
    return pd.to_numeric(values.str.strip(), errors="coerce").astype(float)


def load_scms(path: Path = DATASET_PATH, verify_checksum: bool = True) -> pd.DataFrame:
    """Return one cleaned row per SCMS shipment.

    Raises ``ValueError`` (message mentions "checksum") when the file is not the
    verified copy and ``verify_checksum`` is true.
    """
    path = Path(path)
    if verify_checksum:
        actual = _sha256(path)
        if actual != DATASET_SHA256:
            raise ValueError(
                f"SCMS dataset checksum mismatch for {path}: "
                f"expected {DATASET_SHA256}, got {actual}"
            )
    raw = _read_raw(path)

    clean = pd.DataFrame(index=raw.index)
    clean["shipment_id"] = pd.to_numeric(raw["ID"], errors="raise").astype(int)
    for source, target in _TEXT_COLUMNS.items():
        clean[target] = raw[source].str.strip()
    mode = raw["Shipment Mode"].str.strip()
    clean["shipment_mode"] = mode.where(~mode.isin(["", "N/A"]), "unknown")
    clean["scheduled_date"] = pd.to_datetime(raw["Scheduled Delivery Date"].str.strip(),
                                             format=_DATE_FORMAT)
    clean["delivered_date"] = pd.to_datetime(raw["Delivered to Client Date"].str.strip(),
                                             format=_DATE_FORMAT)
    for source, target in _NUMBER_COLUMNS.items():
        clean[target] = _to_number(raw[source])
    clean["late"] = clean["delivered_date"] > clean["scheduled_date"]
    clean["delay_days"] = (clean["delivered_date"] - clean["scheduled_date"]).dt.days.astype(int)
    return clean[_OUTPUT_COLUMNS]


def scms_orders(scms: pd.DataFrame) -> pd.DataFrame:
    """Map cleaned SCMS rows onto the generic order schema (``ORDER_COLUMNS``)."""
    orders = pd.DataFrame(
        {
            "supplier_key": scms["vendor"],
            "scheduled_date": scms["scheduled_date"],
            "delivered_date": scms["delivered_date"],
            "order_value": scms["order_value"],
            "quantity": scms["quantity"],
            "shipment_mode": scms["shipment_mode"],
            "fulfil_via": scms["fulfil_via"],
        },
        index=scms.index,
    )
    return orders[ORDER_COLUMNS]
