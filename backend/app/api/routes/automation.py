"""Communications (drafts only - the app never sends email) and purchase orders."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Response
from pydantic import EmailStr, Field

from app.api.deps import (
    DB, CurrentUser, RequestContext, comparison_repo, quotation_repo, request_repo, require_roles, supplier_repo,
)
from app.core.rate_limit import AILimited
from app.core.config import settings
from app.core.crypto import decrypt_secret
from app.core.errors import ConfigurationError, ConflictError, ValidationError
from app.integrations.ai.base import AIProvider
from app.integrations.ai.factory import for_task, get_ai_provider
from app.api.routes.channels import get_gmail_client
from app.integrations.ingestion.gmail_client import GmailAuthError, GmailClient
from app.integrations.storage.google_drive import SCOPE as DRIVE_SCOPE
from app.integrations.storage.google_drive import upload_file
from app.repositories.automation import CommunicationRepository, PurchaseOrderRepository
from app.repositories.channels import ChannelConnectionRepository
from app.repositories.procurement_requests import ProcurementRequestRepository
from app.repositories.quotations import ComparisonRepository, QuotationRepository
from app.repositories.suppliers import SupplierRepository
from app.schemas.common import APIModel, UserRole
from app.services.automation import communications as comms
from app.services.automation import purchase_orders as pos
from app.services.procurement.comparison import comparison_fingerprint
from app.services.procurement.reliability import refresh_reliability

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
    # The comparison flagged this quotation for review (another currency, a price far out of range); award anyway.
    confirm_review: bool = False


class ReceiptLineIn(APIModel):
    line: int = Field(ge=0, description="Index of the PO line this quantity is for")
    received_quantity: float = Field(ge=0, allow_inf_nan=False)
    # Leave out until quality has been inspected; 0 means inspected and nothing rejected.
    rejected_quantity: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)


class ReceiptIn(APIModel):
    lines: list[ReceiptLineIn] = Field(min_length=1)
    invoice_amount: Optional[float] = Field(default=None, gt=0, allow_inf_nan=False)
    # final: compared with the order total; partial and credit_note are recorded but not scored.
    invoice_type: Literal["final", "partial", "credit_note"] = "final"
    # An approved price change: the final invoice is compared with this instead of the PO total.
    approved_amount: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)


class POActionIn(APIModel):
    delivered_at: Optional[datetime] = None
    receipt: Optional[ReceiptIn] = None                           # deliver: what arrived, recorded in one step
    cancelled_by: Optional[Literal["supplier", "buyer"]] = None  # cancel: only "supplier" counts against it
    cancel_reason: Optional[str] = Field(default=None, max_length=500)


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


@router.post("/procurement-requests/{request_id}/rfqs", status_code=201, dependencies=[AILimited])
async def create_rfqs(
    request_id: str, payload: RFQIn, context: CurrentUser,
    requests: ProcurementRequestRepository = Depends(request_repo),
    suppliers: SupplierRepository = Depends(supplier_repo),
    repo: CommunicationRepository = Depends(communication_repo),
    provider: AIProvider = Depends(ai_provider),
) -> list[dict]:
    request = await requests.get_or_404(context.organization_id, request_id)
    chosen = [await suppliers.get_or_404(context.organization_id, sid) for sid in payload.supplier_ids]
    drafts = await comms.draft_rfqs(request, chosen, context.organization, for_task(provider, "drafting"))
    return [await _create(repo, context, d) for d in drafts]


@router.post("/comparisons/procurement-requests/{request_id}/negotiations", status_code=201, dependencies=[AILimited])
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
        row, rows, request, context.organization, for_task(provider, "negotiation"), discount_pct=payload.discount_pct,
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
    updated = await repo.raw_update(context.organization_id, communication_id, comms.transition(doc, action, context.user_id))
    if action == "mark_sent" and doc.get("kind") == "rfq" and doc.get("supplier_id"):
        await refresh_reliability(repo.db, context.organization_id, [str(doc["supplier_id"])])  # reply clock starts
    return updated


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


def _already_awarded(existing: dict, quotation_id: str, response: Response) -> dict:
    """The same award repeated (a retry, a double click) returns the order already made; another one is refused."""
    if str(existing.get("quotation_id")) == quotation_id:
        response.status_code = 200
        return existing
    raise ConflictError(f"This request already has purchase order {existing.get('po_number')} "
                        f"({existing.get('status')}). Cancel it before awarding another quotation; split awards are "
                        "not supported.", {"purchase_order_id": existing.get("id")})


@router.post("/comparisons/procurement-requests/{request_id}/award", status_code=201)
async def award(
    request_id: str, payload: AwardIn, response: Response, context: RequestContext = Manager,
    requests: ProcurementRequestRepository = Depends(request_repo),
    quotations: QuotationRepository = Depends(quotation_repo),
    suppliers: SupplierRepository = Depends(supplier_repo),
    repo: PurchaseOrderRepository = Depends(po_repo),
    comparisons: ComparisonRepository = Depends(comparison_repo),
) -> dict:
    """Award one quotation of the current comparison. Refused with no comparison, for a quotation the comparison
    did not include, when the request or any of its quotations changed since it was computed, and when the request
    already has a live purchase order (repeating the same award returns that order)."""
    org_id = context.organization_id
    request = await requests.get_or_404(org_id, request_id)
    quotation = await quotations.get_or_404(org_id, payload.quotation_id)
    if str(quotation.get("procurement_request_id")) != request_id:
        raise ValidationError("That quotation belongs to a different request.")
    existing = await repo.live_award(org_id, request_id)
    if existing:
        return _already_awarded(existing, payload.quotation_id, response)
    stored = await comparisons.latest_for_request(org_id, request_id)
    if not stored or not stored.get("suppliers"):
        raise ConflictError("Run the comparison for this request before awarding.")
    row = next((s for s in stored["suppliers"] if str(s.get("quotation_id")) == payload.quotation_id), None)
    if row is None:
        raise ConflictError("That quotation is not part of the current comparison. Recompute the comparison with it "
                            "included before awarding.")
    if stored.get("input_fingerprint") != comparison_fingerprint(request, await quotations.for_request(org_id, request_id)):
        raise ConflictError("The request or its quotations have changed since the comparison was computed. Recompute "
                            "the comparison and check the ranking before awarding.")
    review_reasons = row.get("review_reasons") or []
    if review_reasons and not payload.confirm_review:
        raise ConflictError("This quotation needs review before award: " + " ".join(review_reasons),
                            {"review_reasons": review_reasons})
    supplier = await suppliers.get(org_id, quotation["supplier_id"]) if quotation.get("supplier_id") else None
    po = pos.build_purchase_order(request, quotation, supplier, context.organization)
    if not po["lines"]:
        raise ConflictError("No request item is matched and priced in this quotation.", {"warnings": po["warnings"]})
    po["po_number"] = await repo.next_po_number(org_id, datetime.now().year)
    po["created_by"] = context.user_id
    po["history"] = [comms.history_entry("created", context.user_id)]
    if review_reasons:
        po["history"].append(comms.history_entry("review_confirmed", context.user_id, reasons=review_reasons))
    created, existing = await repo.create_award(org_id, po)
    if existing:  # another award got there first
        return _already_awarded(existing, payload.quotation_id, response)
    await requests.update(org_id, request_id, {"status": "awarded"})
    return created


@router.get("/purchase-orders")
async def list_purchase_orders(context: CurrentUser, status: Optional[str] = None,
                               repo: PurchaseOrderRepository = Depends(po_repo)) -> list[dict]:
    return await repo.list(context.organization_id, {"status": status} if status else None)


@router.get("/purchase-orders/{po_id}")
async def get_purchase_order(po_id: str, context: CurrentUser, repo: PurchaseOrderRepository = Depends(po_repo)) -> dict:
    return await repo.get_or_404(context.organization_id, po_id)


@router.post("/purchase-orders/{po_id}/drive")
async def file_purchase_order_to_drive(
    po_id: str, context: CurrentUser, database: DB,
    repo: PurchaseOrderRepository = Depends(po_repo),
    client: GmailClient = Depends(get_gmail_client),
) -> dict:
    """Upload the PO's PDF to the buyer's Google Drive, reusing the Gmail connection."""
    if not settings.google_configured:
        raise ConfigurationError(
            "Google is not configured on the server. Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET "
            "to backend/.env and restart the backend.")
    po = await repo.get_or_404(context.organization_id, po_id)
    connection = await ChannelConnectionRepository(database).get_for_provider(context.organization_id, "gmail")
    if not connection or connection.get("status") != "connected":
        raise ConflictError("Connect your Google account on the Integrations page first.")
    if DRIVE_SCOPE not in (connection.get("scopes") or []):
        raise ConflictError("This Google connection has no Drive permission. Reconnect it on the "
                            "Integrations page to grant access.")
    try:
        access_token = await client.refresh_access_token(decrypt_secret(connection["encrypted_refresh_token"]))
    except GmailAuthError as exc:
        await ChannelConnectionRepository(database).update_status(
            context.organization_id, "gmail", {"status": "reauthorization_required", "last_error": str(exc)})
        raise ConflictError("Google access has expired. Please reconnect the account on the Integrations page.")

    uploaded = await upload_file(client.http, access_token, filename=f"{po['po_number']}.pdf",
                                 data=pos.render_po_pdf(po), folder_id=settings.GOOGLE_DRIVE_FOLDER_ID or None)
    await repo.raw_update(context.organization_id, po_id, {
        "$set": {"drive_file": uploaded},
        "$push": {"history": comms.history_entry("filed_to_drive", context.user_id, file_id=uploaded["id"])},
    })
    return uploaded


@router.post("/purchase-orders/{po_id}/{action}")
async def purchase_order_action(
    po_id: str, action: Literal["approve", "issue", "deliver", "close", "cancel"],
    context: RequestContext = Manager, payload: Optional[POActionIn] = None,
    repo: PurchaseOrderRepository = Depends(po_repo),
    communications: CommunicationRepository = Depends(communication_repo),
) -> dict:
    payload = payload or POActionIn()
    po = await repo.get_or_404(context.organization_id, po_id)
    update = pos.transition(po, action, context.user_id, payload.delivered_at, payload.cancelled_by, payload.cancel_reason)
    if action == "deliver" and payload.receipt is not None:
        # The receipt is validated before anything is written, then saved in the same update as the delivery.
        update = pos.combine(update, _receipt_update({**po, "status": "delivered"}, context, payload.receipt))
    # Compare-and-set on the status read above: of two concurrent actions on one order, only the first applies.
    updated = await repo.raw_update(context.organization_id, po_id, update, expected={"status": po["status"]})
    if updated is None:
        raise ConflictError("This purchase order was changed by someone else just now. Reload it and try again.")
    if action in ("deliver", "close", "cancel") and po.get("supplier_id"):
        await refresh_reliability(repo.db, context.organization_id, [str(po["supplier_id"])])
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


def _receipt_update(po: dict, context: RequestContext, receipt: ReceiptIn) -> dict:
    invoice = receipt.model_dump(include={"invoice_amount", "invoice_type", "approved_amount"})
    return pos.record_receipt(po, [line.model_dump() for line in receipt.lines], invoice, context.user_id)


async def _save_receipt(repo: PurchaseOrderRepository, context: RequestContext, po: dict, receipt: ReceiptIn) -> dict:
    updated = await repo.raw_update(context.organization_id, po["id"], _receipt_update(po, context, receipt),
                                    expected={"status": po["status"]})
    if updated is None:
        raise ConflictError("This purchase order was changed by someone else just now. Reload it and try again.")
    return updated


@router.put("/purchase-orders/{po_id}/receipt")
async def record_purchase_order_receipt(po_id: str, payload: ReceiptIn, context: RequestContext = Manager,
                                        repo: PurchaseOrderRepository = Depends(po_repo)) -> dict:
    """Record or correct what arrived for a delivered order (received and rejected per line, invoice amount)."""
    updated = await _save_receipt(repo, context, await repo.get_or_404(context.organization_id, po_id), payload)
    if updated.get("supplier_id"):
        await refresh_reliability(repo.db, context.organization_id, [str(updated["supplier_id"])])
    return updated


@router.get("/purchase-orders/{po_id}/pdf")
async def purchase_order_pdf(po_id: str, context: CurrentUser, repo: PurchaseOrderRepository = Depends(po_repo)) -> Response:
    po = await repo.get_or_404(context.organization_id, po_id)
    return Response(pos.render_po_pdf(po), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{po["po_number"]}.pdf"'})
