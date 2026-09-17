from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import CurrentUser, quotation_repo, request_repo
from app.core.errors import NotFoundError
from app.repositories.quotations import QuotationRepository
from app.repositories.procurement_requests import ProcurementRequestRepository
from app.schemas.common import Paginated, ProcurementStatus
from app.schemas.procurement import (
    ProcurementRequestCreate,
    ProcurementRequestOut,
    ProcurementRequestUpdate,
)
from app.services.procurement.normalization import (
    convert_quantity,
    normalize_text,
    normalize_tokens,
    normalize_unit,
)

router = APIRouter(prefix="/procurement-requests", tags=["procurement-requests"])


def _prepare_items(items) -> list[dict]:
    """Attach normalized forms so matching does not redo this per comparison."""
    prepared = []
    for item in items:
        data = item.model_dump() if hasattr(item, "model_dump") else dict(item)
        base_quantity, base_unit = convert_quantity(data.get("quantity"), data.get("unit"))
        data.update(
            {
                "item_id": data.get("item_id") or f"item-{uuid.uuid4().hex[:8]}",
                "normalized_name": normalize_text(data.get("name")) or None,
                "normalized_tokens": normalize_tokens(data.get("name")),
                "normalized_unit": normalize_unit(data.get("unit")) or base_unit,
                "normalized_quantity": base_quantity,
            }
        )
        prepared.append(data)
    return prepared


@router.get("", response_model=Paginated[ProcurementRequestOut])
async def list_requests(
    context: CurrentUser,
    status_filter: Optional[ProcurementStatus] = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    requests: ProcurementRequestRepository = Depends(request_repo),
) -> Paginated[ProcurementRequestOut]:
    skip = (page - 1) * page_size
    rows = await requests.list_with_counts(
        context.organization_id,
        status=status_filter.value if status_filter else None,
        skip=skip,
        limit=page_size,
    )
    total = await requests.count(
        context.organization_id, {"status": status_filter.value} if status_filter else None
    )
    return Paginated[ProcurementRequestOut](
        items=[ProcurementRequestOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=ProcurementRequestOut, status_code=status.HTTP_201_CREATED)
async def create_request(
    payload: ProcurementRequestCreate,
    context: CurrentUser,
    requests: ProcurementRequestRepository = Depends(request_repo),
) -> ProcurementRequestOut:
    data = payload.model_dump()
    data["items"] = _prepare_items(payload.items)
    data["status"] = payload.status.value
    data["created_by"] = _oid(context.user_id)
    created = await requests.create(context.organization_id, data)
    created["quotation_count"] = 0
    return ProcurementRequestOut.model_validate(created)


@router.get("/{request_id}", response_model=ProcurementRequestOut)
async def get_request(
    request_id: str,
    context: CurrentUser,
    requests: ProcurementRequestRepository = Depends(request_repo),
    quotations: QuotationRepository = Depends(quotation_repo),
) -> ProcurementRequestOut:
    row = await requests.get_or_404(context.organization_id, request_id)
    row["quotation_count"] = await quotations.count(
        context.organization_id, {"procurement_request_id": _oid(request_id)}
    )
    return ProcurementRequestOut.model_validate(row)


@router.put("/{request_id}", response_model=ProcurementRequestOut)
async def update_request(
    request_id: str,
    payload: ProcurementRequestUpdate,
    context: CurrentUser,
    requests: ProcurementRequestRepository = Depends(request_repo),
    quotations: QuotationRepository = Depends(quotation_repo),
) -> ProcurementRequestOut:
    await requests.get_or_404(context.organization_id, request_id)
    data = payload.model_dump(exclude_unset=True)
    if "items" in data and data["items"] is not None:
        data["items"] = _prepare_items(payload.items or [])
    if data.get("status") is not None:
        data["status"] = (
            data["status"].value if hasattr(data["status"], "value") else str(data["status"])
        )
    updated = await requests.update(context.organization_id, request_id, data)
    if updated is None:
        raise NotFoundError("Procurement request not found")
    updated["quotation_count"] = await quotations.count(
        context.organization_id, {"procurement_request_id": _oid(request_id)}
    )
    return ProcurementRequestOut.model_validate(updated)


@router.delete("/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_request(
    request_id: str,
    context: CurrentUser,
    requests: ProcurementRequestRepository = Depends(request_repo),
) -> Response:
    deleted = await requests.delete(context.organization_id, request_id)
    if not deleted:
        raise NotFoundError("Procurement request not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _oid(value):
    from app.repositories.base import maybe_object_id

    return maybe_object_id(value)
