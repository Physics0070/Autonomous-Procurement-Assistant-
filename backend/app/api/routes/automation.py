"""Communications (drafts only - the app never sends email) and purchase orders."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Response
from pydantic import EmailStr, Field

from app.api.deps import (
    DB, CurrentUser, RequestContext, comparison_repo, quotation_repo, request_repo, require_roles, supplier_repo,
)
from app.core.errors import ConflictError, ValidationError
from app.integrations.ai.base import AIProvider
from app.integrations.ai.factory import get_ai_provider
from app.repositories.automation import CommunicationRepository, PurchaseOrderRepository
from app.repositories.procurement_requests import ProcurementRequestRepository
from app.repositories.quotations import ComparisonRepository, QuotationRepository
from app.repositories.suppliers import SupplierRepository
from app.schemas.common import APIModel, UserRole
from app.services.automation import communications as comms
from app.services.automation import purchase_orders as pos

router = APIRouter(tags=["automation"])
Manager = Depends(require_roles(UserRole.ADMIN, UserRole.PROCUREMENT_MANAGER))


def communication_repo(database: DB) -> CommunicationRepository:
    return CommunicationRepository(database)


def po_repo(database: DB) -> PurchaseOrderRepository:
    return PurchaseOrderRepository(database)


def ai_provider() -> AIProvider:
    return get_ai_provider()


class RFQIn(APIModel):
    supplier_ids: list[str] = Field(min_length=1, max_length=50)


class NegotiationIn(APIModel):
    quotation_id: str
    discount_pct: Optional[float] = Field(default=None, ge=0, le=50)  # default from settings
    target_price: Optional[float] = Field(default=None, gt=0)


class CommunicationEdit(APIModel):
    subject: Optional[str] = Field(default=None, min_length=1, max_length=300)
    body: Optional[str] = Field(default=None, min_length=1, max_length=20000)
    to_email: Optional[EmailStr] = None


class AwardIn(APIModel):
    quotation_id: str


class DeliveryIn(APIModel):
    delivered_at: Optional[datetime] = None


async def _comparison_rows(comparisons: ComparisonRepository, org_id: str, request_id: str) -> list[dict]:
    stored = await comparisons.latest_for_request(org_id, request_id)
    if not stored or not stored.get("suppliers"):
        raise ConflictError("Run the comparison for this request first.")
    return stored["suppliers"]


# ---------------------------------------------------------------------------
# Communications
# ---------------------------------------------------------------------------


@router.get("/communications")
async def list_communications(
    context: CurrentUser, kind: Optional[str] = None, status: Optional[str] = None,
    procurement_request_id: Optional[str] = None, repo: CommunicationRepository = Depends(communication_repo),
) -> list[dict]:
    filters = {k: v for k, v in {"kind": kind, "status": status, "procurement_request_id": procurement_request_id}.items() if v}
    return await repo.list(context.organization_id, filters)


@router.get("/communications/{communication_id}")
async def get_communication(communication_id: str, context: CurrentUser,
                            repo: CommunicationRepository = Depends(communication_repo)) -> dict:
    return await repo.get_or_404(context.organization_id, communication_id)


@router.post("/procurement-requests/{request_id}/rfqs", status_code=201)
async def create_rfqs(
    request_id: str, payload: RFQIn, context: CurrentUser,
    requests: ProcurementRequestRepository = Depends(request_repo),
    suppliers: SupplierRepository = Depends(supplier_repo),
    repo: CommunicationRepository = Depends(communication_repo),
    provider: AIProvider = Depends(ai_provider),
) -> list[dict]:
    request = await requests.get_or_404(context.organization_id, request_id)
    chosen = [await suppliers.get_or_404(context.organization_id, sid) for sid in payload.supplier_ids]
    drafts = await comms.draft_rfqs(request, chosen, context.organization, provider)
    return [await _create(repo, context, d) for d in drafts]


@router.post("/comparisons/procurement-requests/{request_id}/negotiations", status_code=201)
async def create_negotiation(
    request_id: str, payload: NegotiationIn, context: CurrentUser,
    requests: ProcurementRequestRepository = Depends(request_repo),
    comparisons: ComparisonRepository = Depends(comparison_repo),
    suppliers: SupplierRepository = Depends(supplier_repo),
    repo: CommunicationRepository = Depends(communication_repo),
    provider: AIProvider = Depends(ai_provider),
) -> dict:
    request = await requests.get_or_404(context.organization_id, request_id)
    rows = await _comparison_rows(comparisons, context.organization_id, request_id)
    row = next((r for r in rows if str(r["quotation_id"]) == payload.quotation_id), None)
    if row is None:
        raise ValidationError("That quotation is not part of the comparison.")
    supplier = await suppliers.get(context.organization_id, row["supplier_id"]) if row.get("supplier_id") else None
    draft = await comms.draft_negotiation(
        row, rows, request, context.organization, provider, discount_pct=payload.discount_pct,
        target_price=payload.target_price, to_email=(supplier or {}).get("email"),
    )
    return await _create(repo, context, draft)


async def _create(repo: CommunicationRepository, context: RequestContext, draft: dict) -> dict:
    return await comms.save_draft(repo, context.organization_id, context.user_id, draft)


@router.patch("/communications/{communication_id}")
async def edit_communication(communication_id: str, payload: CommunicationEdit, context: CurrentUser,
                             repo: CommunicationRepository = Depends(communication_repo)) -> dict:
    doc = await repo.get_or_404(context.organization_id, communication_id)
    if doc["status"] != "draft":
        raise ConflictError("Only drafts can be edited.")
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    return await repo.raw_update(context.organization_id, communication_id, {
        "$set": changes, "$push": {"history": comms.history_entry("edited", context.user_id, fields=sorted(changes))},
    })


async def _communication_action(action: str, communication_id: str, context: RequestContext,
                                repo: CommunicationRepository) -> dict:
    doc = await repo.get_or_404(context.organization_id, communication_id)
    return await repo.raw_update(context.organization_id, communication_id, comms.transition(doc, action, context.user_id))


@router.post("/communications/{communication_id}/approve")
async def approve_communication(communication_id: str, context: RequestContext = Manager,
                                repo: CommunicationRepository = Depends(communication_repo)) -> dict:
    return await _communication_action("approve", communication_id, context, repo)


@router.post("/communications/{communication_id}/mark-sent")
async def mark_communication_sent(communication_id: str, context: CurrentUser,
                                  repo: CommunicationRepository = Depends(communication_repo)) -> dict:
    return await _communication_action("mark_sent", communication_id, context, repo)


@router.post("/communications/{communication_id}/cancel")
async def cancel_communication(communication_id: str, context: CurrentUser,
                               repo: CommunicationRepository = Depends(communication_repo)) -> dict:
    return await _communication_action("cancel", communication_id, context, repo)


@router.get("/communications/{communication_id}/eml")
async def export_communication(communication_id: str, context: CurrentUser,
                               repo: CommunicationRepository = Depends(communication_repo)) -> Response:
    doc = await repo.get_or_404(context.organization_id, communication_id)
    return Response(
        comms.to_eml(doc, context.organization.get("contact_email")), media_type="message/rfc822",
        headers={"Content-Disposition": f'attachment; filename="{doc["kind"]}-{communication_id}.eml"'},
    )


# ---------------------------------------------------------------------------
# Purchase orders
# ---------------------------------------------------------------------------


@router.post("/comparisons/procurement-requests/{request_id}/award", status_code=201)
async def award(
    request_id: str, payload: AwardIn, context: RequestContext = Manager,
    requests: ProcurementRequestRepository = Depends(request_repo),
    quotations: QuotationRepository = Depends(quotation_repo),
    suppliers: SupplierRepository = Depends(supplier_repo),
    repo: PurchaseOrderRepository = Depends(po_repo),
) -> dict:
    org_id = context.organization_id
    request = await requests.get_or_404(org_id, request_id)
    quotation = await quotations.get_or_404(org_id, payload.quotation_id)
    if str(quotation.get("procurement_request_id")) != request_id:
        raise ValidationError("That quotation belongs to a different request.")
    supplier = await suppliers.get(org_id, quotation["supplier_id"]) if quotation.get("supplier_id") else None
    po = pos.build_purchase_order(request, quotation, supplier, context.organization)
    if not po["lines"]:
        raise ConflictError("No request item is matched and priced in this quotation.", {"warnings": po["warnings"]})
    po["po_number"] = await repo.next_po_number(org_id, datetime.now().year)
    po["created_by"] = context.user_id
    po["history"] = [comms.history_entry("created", context.user_id)]
    created = await repo.create(org_id, po)
    await requests.update(org_id, request_id, {"status": "awarded"})
    return created


@router.get("/purchase-orders")
async def list_purchase_orders(context: CurrentUser, status: Optional[str] = None,
                               repo: PurchaseOrderRepository = Depends(po_repo)) -> list[dict]:
    return await repo.list(context.organization_id, {"status": status} if status else None)


@router.get("/purchase-orders/{po_id}")
async def get_purchase_order(po_id: str, context: CurrentUser, repo: PurchaseOrderRepository = Depends(po_repo)) -> dict:
    return await repo.get_or_404(context.organization_id, po_id)


@router.post("/purchase-orders/{po_id}/{action}")
async def purchase_order_action(
    po_id: str, action: Literal["approve", "issue", "deliver", "close", "cancel"],
    context: RequestContext = Manager, payload: Optional[DeliveryIn] = None,
    repo: PurchaseOrderRepository = Depends(po_repo),
    communications: CommunicationRepository = Depends(communication_repo),
) -> dict:
    po = await repo.get_or_404(context.organization_id, po_id)
    update = pos.transition(po, action, context.user_id, (payload or DeliveryIn()).delivered_at)
    updated = await repo.raw_update(context.organization_id, po_id, update)
    if action == "approve":
        # The approved PO goes out as a draft email with the PDF attached by the sender.
        await _create(communications, context, {
            "kind": "purchase_order", "status": "draft", "purchase_order_id": po_id,
            "procurement_request_id": po["procurement_request_id"], "supplier_id": po.get("supplier_id"),
            "quotation_id": po["quotation_id"], "to_email": po["supplier"].get("email"),
            "subject": f"Purchase order {po['po_number']}",
            "body": f"Dear {po['supplier'].get('name') or 'Sir/Madam'},\n\nPlease find attached purchase order "
                    f"{po['po_number']} for {po['pricing']['currency']} {po['pricing']['total']:,.2f}. "
                    f"Kindly acknowledge and confirm the delivery date.\n\nRegards,\n{po['buyer'].get('name') or ''}",
            "generated_by": "template", "guardrail_findings": [],
        })
    return updated


@router.get("/purchase-orders/{po_id}/pdf")
async def purchase_order_pdf(po_id: str, context: CurrentUser, repo: PurchaseOrderRepository = Depends(po_repo)) -> Response:
    po = await repo.get_or_404(context.organization_id, po_id)
    return Response(pos.render_po_pdf(po), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{po["po_number"]}.pdf"'})
