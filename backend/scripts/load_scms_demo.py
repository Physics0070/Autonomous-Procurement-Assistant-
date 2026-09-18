"""Create the "SCMS demo — USAID public data" organization from the real SCMS file.

Suppliers, delivered purchase orders (USD) and price history come from the USAID SCMS
Delivery History, so reliability predictions, price anomalies, spend and forecasts can be
shown on real data in the app. Re-running replaces the demo organization.

Note: the reliability model was trained on SCMS shipments up to 2013, so predictions for
this demo organization are partly in-sample. The honest held-out metrics are in
ml/artifacts/evaluation_report.md.

Run from backend/:  ./.venv/Scripts/python.exe -m scripts.load_scms_demo
"""
from __future__ import annotations

import asyncio
import os
import sys

from bson import ObjectId

from app.core.database import close_database_connection, connect_to_database
from app.core.security import hash_password
from app.repositories.users import OrganizationRepository, UserRepository
from app.services.procurement.normalization import normalize_text
from ml.scms import load_scms

ORG_NAME = "SCMS demo — USAID public data"
EMAIL = os.getenv("SCMS_DEMO_EMAIL", "scms.demo@procurement-demo.com")
PASSWORD = os.getenv("SCMS_DEMO_PASSWORD", "ScmsDemo2026!")  # demo-only account; override via env
ORG_COLLECTIONS = ("suppliers", "purchase_orders", "price_history", "procurement_requests", "quotations",
                   "comparisons", "communications", "agent_runs", "conversations", "counters", "users")


async def main() -> int:
    db = await connect_to_database()
    old = await db.organizations.find_one({"name": ORG_NAME})
    if old:
        for name in ORG_COLLECTIONS:
            await db[name].delete_many({"organization_id": old["_id"]})
        await db.organizations.delete_one({"_id": old["_id"]})

    org = await OrganizationRepository(db).create(ORG_NAME, "Public-health supply chain (USAID SCMS)")
    org_id = ObjectId(org["id"])
    await UserRepository(db).create(name="SCMS Demo", email=EMAIL, hashed_password=hash_password(PASSWORD),
                                    organization_id=org["id"], role="admin")

    scms = load_scms()
    rows = scms.dropna(subset=["scheduled_date", "delivered_date", "order_value"])
    vendors = {v: ObjectId() for v in rows["vendor"].unique()}
    await db.suppliers.insert_many([
        {"_id": sid, "organization_id": org_id, "name": name, "metadata": {"source": "USAID SCMS"},
         "reliability": {"score": 0.5, "method": "rule_based", "sample_size": 0}, "created_at": rows["scheduled_date"].min()}
        for name, sid in vendors.items()])

    pos, prices = [], []
    for r in rows.itertuples():
        supplier_id = str(vendors[r.vendor])
        quantity = float(r.quantity or 0)
        unit_price = float(r.unit_price) if r.unit_price and r.unit_price > 0 else round(r.order_value / quantity, 4) if quantity else 0.0
        delay = (r.delivered_date.normalize() - r.scheduled_date.normalize()).days
        pos.append({
            "organization_id": org_id, "po_number": f"PO-{r.scheduled_date.year}-{r.shipment_id}",
            "procurement_request_id": None, "quotation_id": None, "supplier_id": supplier_id,
            "supplier": {"name": r.vendor}, "buyer": {"name": ORG_NAME},
            "lines": [{"request_item_id": None, "description": r.product, "quantity": quantity, "unit": r.dosage_form,
                       "unit_price": unit_price, "tax_percentage": 0, "line_total": float(r.order_value)}],
            "warnings": [], "pricing": {"currency": "USD", "subtotal": float(r.order_value), "taxes": [], "freight": 0,
                                        "total": float(r.order_value)},
            "terms": {"delivery_days": None, "payment_terms": None, "shipment_mode": r.shipment_mode, "fulfil_via": r.fulfil_via},
            "status": "delivered", "expected_delivery_date": r.scheduled_date.to_pydatetime(),
            "delivered_at": r.delivered_date.to_pydatetime(), "on_time": delay <= 0, "delay_days": max(delay, 0),
            "history": [], "source": {"dataset": "USAID SCMS", "shipment_id": str(r.shipment_id)},
            "created_at": r.scheduled_date.to_pydatetime(), "updated_at": r.delivered_date.to_pydatetime(),
        })
        if unit_price > 0:
            prices.append({"organization_id": org_id, "normalized_name": normalize_text(r.product), "unit": r.dosage_form,
                           "unit_price": unit_price, "supplier_id": ObjectId(supplier_id), "quotation_id": None,
                           "created_at": r.scheduled_date.to_pydatetime()})
    await db.purchase_orders.insert_many(pos)
    await db.price_history.insert_many(prices)
    await close_database_connection()

    print(f"{ORG_NAME}: {len(vendors)} suppliers, {len(pos):,} delivered purchase orders, {len(prices):,} prices.")
    print(f"Log in as {EMAIL} / {PASSWORD}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
