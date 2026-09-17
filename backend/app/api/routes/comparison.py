from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.api.deps import (
    CurrentUser,
    comparison_repo,
    quotation_repo,
    request_repo,
    supplier_repo,
)
from app.core.config import settings
from app.repositories.quotations import ComparisonRepository, QuotationRepository
from app.repositories.procurement_requests import ProcurementRequestRepository
from app.repositories.suppliers import SupplierRepository
from app.schemas.comparison import ComparisonRequest, ComparisonResult
from app.services.procurement.comparison import build_comparison
from app.services.procurement.explanation import explain_comparison

router = APIRouter(prefix="/comparisons", tags=["comparison"])


@router.get("/weights")
async def default_weights(context: CurrentUser) -> dict:
    """Configured scoring weights. Not hardcoded in the frontend."""
    return {
        "weights": settings.scoring_weights(),
        "thresholds": {
            "match_auto": settings.MATCH_AUTO_THRESHOLD,
            "match_review": settings.MATCH_REVIEW_THRESHOLD,
        },
    }


@router.post("/procurement-requests/{request_id}", response_model=ComparisonResult)
async def compute_comparison(
    request_id: str,
    context: CurrentUser,
    payload: Optional[ComparisonRequest] = None,
    requests: ProcurementRequestRepository = Depends(request_repo),
    quotations: QuotationRepository = Depends(quotation_repo),
    suppliers: SupplierRepository = Depends(supplier_repo),
    comparisons: ComparisonRepository = Depends(comparison_repo),
) -> ComparisonResult:
    """Score, rank, then explain - in that order.

    The ranking is computed deterministically first; the AI is only asked to
    describe the finished result.
    """
    payload = payload or ComparisonRequest()
    request = await requests.get_or_404(context.organization_id, request_id)
    rows = await quotations.for_request(context.organization_id, request_id)

    if payload.quotation_ids:
        wanted = set(payload.quotation_ids)
        rows = [r for r in rows if str(r.get("id")) in wanted]

    supplier_rows = await suppliers.list(context.organization_id, limit=500)
    suppliers_by_id = {str(s["id"]): s for s in supplier_rows}

    result = build_comparison(
        request,
        rows,
        suppliers_by_id=suppliers_by_id,
        weight_overrides=payload.weights,
    )

    if payload.include_ai_explanation:
        result.ai_explanation = await explain_comparison(result)

    stored = await comparisons.upsert_for_request(
        context.organization_id, request_id, result.model_dump(mode="json", exclude={"id", "organization_id"})
    )
    result.id = str(stored.get("id"))
    result.organization_id = context.organization_id
    return result


@router.get("/procurement-requests/{request_id}", response_model=ComparisonResult)
async def get_comparison(
    request_id: str,
    context: CurrentUser,
    recompute: bool = Query(default=False),
    requests: ProcurementRequestRepository = Depends(request_repo),
    quotations: QuotationRepository = Depends(quotation_repo),
    suppliers: SupplierRepository = Depends(supplier_repo),
    comparisons: ComparisonRepository = Depends(comparison_repo),
) -> ComparisonResult:
    """Return the stored comparison, or compute one if none exists."""
    if not recompute:
        stored = await comparisons.latest_for_request(context.organization_id, request_id)
        if stored is not None:
            return ComparisonResult.model_validate(stored)
    return await compute_comparison(
        request_id,
        context,
        ComparisonRequest(),
        requests=requests,
        quotations=quotations,
        suppliers=suppliers,
        comparisons=comparisons,
    )
