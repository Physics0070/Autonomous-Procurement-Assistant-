from __future__ import annotations

import hashlib
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import DB, CurrentUser, quotation_repo, supplier_repo
from app.core.errors import ConflictError
from app.repositories.automation import PurchaseOrderRepository
from app.repositories.base import to_object_id
from app.repositories.quotations import QuotationRepository
from app.repositories.suppliers import SupplierRepository
from app.schemas.common import Paginated
from app.schemas.supplier import SupplierCreate, SupplierOut, SupplierUpdate
from app.services.analytics import cache
from app.services.analytics.reliability_ml import ORDER_FIELDS, load_model, orders_frame, predict, predict_all
from app.services.procurement.reliability import compute_reliability

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


@router.get("", response_model=Paginated[SupplierOut])
async def list_suppliers(
    context: CurrentUser,
    database: DB,
    search: Optional[str] = Query(default=None, max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    suppliers: SupplierRepository = Depends(supplier_repo),
    quotations: QuotationRepository = Depends(quotation_repo),
) -> Paginated[SupplierOut]:
    skip = (page - 1) * page_size
    if search:
        rows = await suppliers.search(context.organization_id, search, limit=page_size)
        total = len(rows)
    else:
        rows = await suppliers.list(context.organization_id, skip=skip, limit=page_size)
        total = await suppliers.count(context.organization_id)

    ids = [row["id"] for row in rows]
    orders = await _delivered_orders(context.organization_id, database)
    pos = PurchaseOrderRepository(database)

    async def predict() -> dict:
        return predict_all(load_model(context.organization_id), ids, orders)
    # ~40 ms per supplier, so ~2 s for a page of 50. The risk only changes when an order does; it also
    # drifts with the calendar ("days since the last delivery"), so the key carries today's date.
    ml = await cache.cached(f"supplier_risk:{date.today()}:{hashlib.sha1(','.join(ids).encode()).hexdigest()}",
                            context.organization_id, [pos.collection], predict)

    # One grouped query for every supplier on the page, instead of one count per supplier (~8 ms each).
    counted = await quotations.collection.aggregate([
        {"$match": {"organization_id": to_object_id(context.organization_id), "supplier_id": {"$in": [_oid(i) for i in ids]}}},
        {"$group": {"_id": "$supplier_id", "n": {"$sum": 1}}},
    ]).to_list(length=None)
    quotation_counts = {str(row["_id"]): row["n"] for row in counted}
    items = []
    for row in rows:
        row.setdefault("reliability", {})["ml"] = ml.get(row["id"])
        row["quotation_count"] = quotation_counts.get(row["id"], 0)
        items.append(SupplierOut.model_validate(row))
    return Paginated[SupplierOut](items=items, total=total, page=page, page_size=page_size)


@router.post("", response_model=SupplierOut, status_code=status.HTTP_201_CREATED)
async def create_supplier(
    payload: SupplierCreate,
    context: CurrentUser,
    suppliers: SupplierRepository = Depends(supplier_repo),
) -> SupplierOut:
    existing = await suppliers.find_by_name(context.organization_id, payload.name)
    if existing is not None:
        raise ConflictError(f"A supplier named '{payload.name}' already exists.")
    if payload.gst_number:
        by_gst = await suppliers.find_by_gst(context.organization_id, payload.gst_number)
        if by_gst is not None:
            raise ConflictError(f"A supplier with GST {payload.gst_number} already exists.")

    data = payload.model_dump()
    data["reliability"] = compute_reliability(data, quotations=[])
    created = await suppliers.create(context.organization_id, data)
    return SupplierOut.model_validate(created)


@router.get("/{supplier_id}", response_model=SupplierOut)
async def get_supplier(
    supplier_id: str,
    context: CurrentUser,
    database: DB,
    suppliers: SupplierRepository = Depends(supplier_repo),
    quotations: QuotationRepository = Depends(quotation_repo),
) -> SupplierOut:
    supplier = await suppliers.get_or_404(context.organization_id, supplier_id)
    related = await quotations.list_filtered(context.organization_id, supplier_id=supplier_id, limit=100)
    # Recompute on read so the score reflects the latest quotation history.
    supplier["reliability"] = compute_reliability(supplier, quotations=related)
    supplier["reliability"]["ml"] = predict(load_model(context.organization_id), supplier_id,
                                            await _delivered_orders(context.organization_id, database))
    supplier["quotation_count"] = len(related)
    return SupplierOut.model_validate(supplier)


@router.put("/{supplier_id}", response_model=SupplierOut)
async def update_supplier(
    supplier_id: str,
    payload: SupplierUpdate,
    context: CurrentUser,
    suppliers: SupplierRepository = Depends(supplier_repo),
) -> SupplierOut:
    await suppliers.get_or_404(context.organization_id, supplier_id)
    updated = await suppliers.update(
        context.organization_id, supplier_id, payload.model_dump(exclude_unset=True)
    )
    return SupplierOut.model_validate(updated)


async def _delivered_orders(organization_id: str, database):
    repository = PurchaseOrderRepository(database)

    async def compute():
        return orders_frame(await repository.find_all(
            organization_id, {"status": {"$in": ["delivered", "closed"]}}, fields=ORDER_FIELDS))
    # Building this table for 10,000 orders takes ~2 s; it only changes when an order does.
    return await cache.cached("delivered_orders", organization_id, [repository.collection], compute)


def _oid(value):
    from app.repositories.base import maybe_object_id

    return maybe_object_id(value)
