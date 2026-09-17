from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import FileResponse

from app.api.deps import CurrentUser, quotation_repo, storage
from app.core.errors import NotFoundError, ValidationError
from app.repositories.quotations import QuotationRepository
from app.schemas.common import Paginated, ProcessingStatus
from app.schemas.quotation import (
    CorrectionRequest,
    QuotationDetail,
    QuotationLinkRequest,
    QuotationListItem,
)
from app.services.storage.base import StorageBackend
from app.workers.processing import get_processing_queue

router = APIRouter(prefix="/quotations", tags=["quotations"])


@router.get("", response_model=Paginated[QuotationListItem])
async def list_quotations(
    context: CurrentUser,
    processing_status: Optional[ProcessingStatus] = Query(default=None, alias="status"),
    procurement_request_id: Optional[str] = Query(default=None),
    supplier_id: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    quotations: QuotationRepository = Depends(quotation_repo),
) -> Paginated[QuotationListItem]:
    skip = (page - 1) * page_size
    rows = await quotations.list_filtered(
        context.organization_id,
        status=processing_status.value if processing_status else None,
        procurement_request_id=procurement_request_id,
        supplier_id=supplier_id,
        skip=skip,
        limit=page_size,
    )
    filters: dict[str, Any] = {}
    if processing_status:
        filters["processing_status"] = processing_status.value
    total = await quotations.count(context.organization_id, filters or None)
    return Paginated[QuotationListItem](
        items=[QuotationListItem.model_validate(_list_shape(r)) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{quotation_id}", response_model=QuotationDetail)
async def get_quotation(
    quotation_id: str,
    context: CurrentUser,
    quotations: QuotationRepository = Depends(quotation_repo),
) -> QuotationDetail:
    row = await quotations.get_or_404(context.organization_id, quotation_id)
    return QuotationDetail.model_validate(_list_shape(row))


@router.get("/{quotation_id}/file")
async def download_original(
    quotation_id: str,
    context: CurrentUser,
    quotations: QuotationRepository = Depends(quotation_repo),
    store: StorageBackend = Depends(storage),
):
    """Serve the original uploaded file, unchanged."""
    row = await quotations.get_or_404(context.organization_id, quotation_id)
    source = row.get("source") or {}
    key = source.get("storage_key")
    if not key:
        raise NotFoundError("No original file is stored for this quotation.")
    path = store.local_path(key)
    if not path or not store.exists(key):
        raise NotFoundError("The original file is no longer available in storage.")
    return FileResponse(
        path,
        media_type=source.get("mime_type") or "application/octet-stream",
        filename=source.get("original_filename") or "document",
    )


@router.post("/{quotation_id}/reprocess", response_model=QuotationDetail)
async def reprocess(
    quotation_id: str,
    context: CurrentUser,
    quotations: QuotationRepository = Depends(quotation_repo),
) -> QuotationDetail:
    row = await quotations.get_or_404(context.organization_id, quotation_id)
    await get_processing_queue().enqueue(context.organization_id, quotation_id)
    row = await quotations.get_or_404(context.organization_id, quotation_id)
    return QuotationDetail.model_validate(_list_shape(row))


@router.patch("/{quotation_id}/link", response_model=QuotationDetail)
async def link_quotation(
    quotation_id: str,
    payload: QuotationLinkRequest,
    context: CurrentUser,
    quotations: QuotationRepository = Depends(quotation_repo),
) -> QuotationDetail:
    """Attach a quotation to a procurement request and/or supplier."""
    from app.repositories.base import maybe_object_id

    await quotations.get_or_404(context.organization_id, quotation_id)
    update: dict[str, Any] = {}
    if payload.procurement_request_id is not None:
        update["procurement_request_id"] = maybe_object_id(payload.procurement_request_id)
    if payload.supplier_id is not None:
        update["supplier_id"] = maybe_object_id(payload.supplier_id)
    if not update:
        raise ValidationError("Provide procurement_request_id and/or supplier_id.")

    await quotations.raw_update(context.organization_id, quotation_id, {"$set": update})
    # Re-run matching against the newly linked request.
    if "procurement_request_id" in update and update["procurement_request_id"] is not None:
        await get_processing_queue().enqueue(context.organization_id, quotation_id)
    row = await quotations.get_or_404(context.organization_id, quotation_id)
    return QuotationDetail.model_validate(_list_shape(row))


@router.post("/{quotation_id}/corrections", response_model=QuotationDetail)
async def apply_corrections(
    quotation_id: str,
    payload: CorrectionRequest,
    context: CurrentUser,
    quotations: QuotationRepository = Depends(quotation_repo),
) -> QuotationDetail:
    """Apply user corrections.

    Corrections are written to `effective_data` and recorded in
    `user_corrections`. `ai_extraction` and `normalized_data` are never
    modified, so the machine-produced view stays auditable forever.
    """
    row = await quotations.get_or_404(context.organization_id, quotation_id)
    if not payload.corrections:
        raise ValidationError("No corrections were supplied.")

    base = row.get("effective_data") or row.get("normalized_data")
    if not base:
        raise ValidationError("This quotation has no normalized data to correct yet.")

    effective = copy.deepcopy(base)
    records = []
    now = datetime.now(timezone.utc)

    for path, new_value in payload.corrections.items():
        previous = _get_path(effective, path)
        if not _set_path(effective, path, new_value):
            raise ValidationError(f"Unknown field path: '{path}'")
        records.append(
            {
                "path": path,
                "previous_value": previous,
                "new_value": new_value,
                "corrected_by": context.user_id,
                "corrected_at": now,
                "note": payload.note,
            }
        )

    # Totals that were derived from corrected values must be recomputed.
    _recompute_totals(effective)

    await quotations.append_corrections(context.organization_id, quotation_id, records, effective)
    await quotations.set_status(
        context.organization_id,
        quotation_id,
        ProcessingStatus.COMPLETED.value,
        message=f"{len(records)} correction(s) applied by {context.user.get('name')}.",
        details={"paths": [r['path'] for r in records]},
        extra={
            "requires_review": False,
            "total_amount": (effective.get("pricing") or {}).get("landed_total"),
        },
    )
    updated = await quotations.get_or_404(context.organization_id, quotation_id)
    return QuotationDetail.model_validate(_list_shape(updated))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _list_shape(row: dict[str, Any]) -> dict[str, Any]:
    """Flatten a few fields the list/detail models expose at the top level."""
    row = dict(row)
    data = row.get("effective_data") or row.get("normalized_data") or {}
    pricing = data.get("pricing") or {}
    row.setdefault("currency", pricing.get("currency") or "INR")
    if row.get("total_amount") is None:
        row["total_amount"] = pricing.get("landed_total") or pricing.get("total_amount")
    if not row.get("item_count"):
        row["item_count"] = len(data.get("items") or [])
    validation = row.get("validation") or {}
    if row.get("issue_count") is None:
        row["issue_count"] = int(validation.get("error_count") or 0) + int(
            validation.get("warning_count") or 0
        )
    row.setdefault("requires_review", row.get("processing_status") == ProcessingStatus.REQUIRES_REVIEW.value)
    return row


def _split(path: str) -> list[str]:
    return [p for p in path.split(".") if p != ""]


def _get_path(data: Any, path: str) -> Any:
    current = data
    for part in _split(path):
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None
        if current is None:
            return None
    return current


def _set_path(data: Any, path: str, value: Any) -> bool:
    """Set a value at a dotted path that must already exist.

    Intermediate keys are never created: a typo like 'delivery.delivry_days'
    must be rejected rather than quietly stored under a field nothing reads.
    Fields that exist but are currently null are still writable, which is the
    normal case for correcting something the extractor could not determine.
    """
    parts = _split(path)
    if not parts:
        return False
    current = data
    for part in parts[:-1]:
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return False
        elif isinstance(current, dict):
            if part not in current:
                return False
            if current[part] is None:
                # A known-but-empty container is fine to materialise.
                current[part] = {}
            current = current[part]
        else:
            return False

    last = parts[-1]
    if isinstance(current, list):
        try:
            current[int(last)] = value
            return True
        except (ValueError, IndexError):
            return False
    if isinstance(current, dict) and last in current:
        current[last] = value
        return True
    return False


def _recompute_totals(effective: dict[str, Any]) -> None:
    """Keep derived line and header totals consistent after an edit."""
    items = effective.get("items") or []
    subtotal = 0.0
    complete = bool(items)
    for item in items:
        quantity, unit_price = item.get("quantity"), item.get("unit_price")
        if quantity is not None and unit_price is not None:
            item["computed_total"] = round(float(quantity) * float(unit_price), 4)
        line_total = item.get("total_price")
        if line_total is None:
            line_total = item.get("computed_total")
        if line_total is None:
            complete = False
        else:
            subtotal += float(line_total)

    pricing = effective.setdefault("pricing", {})
    if complete and items:
        pricing["computed_subtotal"] = round(subtotal, 2)
        if pricing.get("subtotal") is None:
            pricing["subtotal"] = round(subtotal, 2)

    base = pricing.get("subtotal")
    if base is not None:
        tax = pricing.get("tax_amount")
        if tax is None and pricing.get("tax_percentage") is not None:
            tax = round(float(base) * float(pricing["tax_percentage"]) / 100.0, 2)
        freight = pricing.get("transportation_cost") or 0.0
        if pricing.get("total_amount") is not None:
            pricing["landed_total"] = pricing["total_amount"]
        elif tax is not None:
            pricing["landed_total"] = round(float(base) + float(tax) + float(freight), 2)
