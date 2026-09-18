"""ML late-delivery risk for suppliers, from the organization's delivered purchase orders.

Uses the SCMS-trained model (or the organization's own retrained one) and leaves the
rule-based score in place as the fallback shown alongside it.
"""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional

import pandas as pd

from app.core.config import settings
from app.core.errors import ConflictError
from ml.features import ORDER_COLUMNS
from ml.reliability_model import ARTIFACT_DIR, ReliabilityModel

MIN_RETRAIN_ORDERS = settings.ML_MIN_RETRAIN_ORDERS
# The PO fields orders_frame() reads.
ORDER_FIELDS = ["supplier_id", "expected_delivery_date", "delivered_at", "pricing.total", "lines.quantity", "terms"]


def org_artifact_dir(organization_id: str) -> Path:
    return ARTIFACT_DIR / "orgs" / organization_id


@lru_cache(maxsize=32)
def load_model(organization_id: Optional[str] = None) -> Optional[ReliabilityModel]:
    """The organization's retrained model if it has one, else the SCMS model."""
    if organization_id:
        own = ReliabilityModel.load(org_artifact_dir(organization_id))
        if own is not None:
            return own
    return ReliabilityModel.load()


def orders_frame(purchase_orders: list[dict]) -> pd.DataFrame:
    """Delivered POs as model order rows. Mode and fulfilment are "unknown" unless the PO records them."""
    rows = [{
        "supplier_key": str(po.get("supplier_id")),
        "scheduled_date": po["expected_delivery_date"],
        "delivered_date": po["delivered_at"],
        "order_value": po["pricing"]["total"],
        "quantity": sum(line["quantity"] for line in po["lines"]),
        "shipment_mode": (po.get("terms") or {}).get("shipment_mode") or "unknown",
        "fulfil_via": (po.get("terms") or {}).get("fulfil_via") or "unknown",
    } for po in purchase_orders if po.get("delivered_at") and po.get("expected_delivery_date") and po.get("supplier_id")]
    return pd.DataFrame(rows, columns=ORDER_COLUMNS)


def predict_all(model: Optional[ReliabilityModel], supplier_ids: list[str], orders: pd.DataFrame) -> dict[str, dict]:
    """Risk for each supplier's next order, in one model call. Suppliers without a model
    or delivery history are left out (the rule-based score stands alone for them)."""
    if model is None or orders.empty:
        return {}
    groups = {key: frame for key, frame in orders.groupby("supplier_key")}
    requests, ids = [], []
    for supplier_id in supplier_ids:
        history = groups.get(str(supplier_id))
        if history is None:
            continue
        # Every recorded delivery is known now, even one dated ahead of the server clock.
        latest = pd.to_datetime(history["delivered_date"], utc=True).max()
        now = max(pd.Timestamp(datetime.now(timezone.utc)), latest + pd.Timedelta(seconds=1))
        order = {"supplier_key": str(supplier_id), "scheduled_date": now,
                 "order_value": float(history["order_value"].median()), "quantity": float(history["quantity"].median()),
                 "shipment_mode": "unknown", "fulfil_via": "unknown"}
        requests.append((history, order, now))
        ids.append(str(supplier_id))
    metrics = {k: model.metadata["test"].get(k) for k in ("roc_auc", "pr_auc", "rows")}
    return {sid: {**p.as_dict(), "test_metrics": metrics} for sid, p in zip(ids, model.predict_many(requests))}


def predict(model: Optional[ReliabilityModel], supplier_id: str, orders: pd.DataFrame) -> Optional[dict]:
    return predict_all(model, [supplier_id], orders).get(str(supplier_id))


def retrain(organization_id: str, purchase_orders: list[dict]) -> dict:
    """Train on the organization's own delivered POs (>= MIN_RETRAIN_ORDERS), time-split by year."""
    from ml.train_reliability import save_artifacts, train_and_evaluate

    orders = orders_frame(purchase_orders)
    if len(orders) < MIN_RETRAIN_ORDERS:
        raise ConflictError(f"Retraining needs at least {MIN_RETRAIN_ORDERS} delivered purchase orders with a "
                            f"recorded delivery date; this organization has {len(orders)}. The USAID SCMS model stays in use.")
    years = pd.to_datetime(orders["scheduled_date"], utc=True).dt.year
    try:
        result = train_and_evaluate(orders, train_end_year=int(years.max()) - 1)
    except ValueError as exc:
        raise ConflictError(f"Retraining needs delivery history spanning at least two calendar years ({exc}).") from exc
    save_artifacts(result, org_artifact_dir(organization_id))
    load_model.cache_clear()
    return result.metadata
