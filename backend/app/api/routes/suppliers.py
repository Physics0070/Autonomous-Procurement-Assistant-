from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import CurrentUser, quotation_repo, supplier_repo
from app.core.errors import ConflictError
from app.repositories.quotations import QuotationRepository
from app.repositories.suppliers import SupplierRepository
from app.schemas.common import Paginated
from app.schemas.supplier import SupplierCreate, SupplierOut, SupplierUpdate
from app.services.procurement.reliability import compute_reliability

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


@router.get("", response_model=Paginated[SupplierOut])
async def list_suppliers(
    context: CurrentUser,
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

    items = []
    for row in rows:
        row["quotation_count"] = await quotations.count(
            context.organization_id, {"supplier_id": _oid(row["id"])}
        )
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
    suppliers: SupplierRepository = Depends(supplier_repo),
    quotations: QuotationRepository = Depends(quotation_repo),
) -> SupplierOut:
    supplier = await suppliers.get_or_404(context.organization_id, supplier_id)
    related = await quotations.list_filtered(context.organization_id, supplier_id=supplier_id, limit=100)
    # Recompute on read so the score reflects the latest quotation history.
    supplier["reliability"] = compute_reliability(supplier, quotations=related)
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


def _oid(value):
    from app.repositories.base import maybe_object_id

    return maybe_object_id(value)
