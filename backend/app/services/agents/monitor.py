"""Monitor agent: starts work by itself, so the system is autonomous rather than button-driven.

Two triggers:
  * a quotation finishes processing and its request now has enough quotations to judge
    → hand the request to the supervisor (which compares, checks risk, drafts, then waits);
  * a purchase order passes its expected delivery date without being delivered
    → draft a follow-up email for a person to approve.

Both only ever produce drafts that wait for approval, so nothing reaches a supplier on its own.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.core.config import settings
from app.integrations.ai.factory import get_ai_provider
from app.repositories.automation import AgentRunRepository, CommunicationRepository, PurchaseOrderRepository
from app.repositories.procurement_requests import ProcurementRequestRepository
from app.repositories.quotations import ComparisonRepository, PriceHistoryRepository, QuotationRepository
from app.repositories.suppliers import SupplierRepository
from app.repositories.users import OrganizationRepository
from app.services.agents.runs import RunRecorder
from app.services.agents.specialists import AgentContext
from app.services.agents.supervisor import run_supervisor
from app.services.automation.communications import now, save_draft

logger = logging.getLogger(__name__)

COMPARABLE = ("COMPLETED", "REQUIRES_REVIEW")
ACTIVE_RUN_STATUSES = ("running", "awaiting_approval")


async def _context(database: Any, organization_id: str, user_id: Optional[str], recorder: RunRecorder) -> AgentContext:
    organization = await OrganizationRepository(database).get(organization_id)
    return AgentContext(
        organization=organization or {"id": organization_id, "name": "Unknown organization"},
        user_id=user_id or "monitor-agent", provider=get_ai_provider(), recorder=recorder,
        requests=ProcurementRequestRepository(database), quotations=QuotationRepository(database),
        suppliers=SupplierRepository(database), comparisons=ComparisonRepository(database),
        communications=CommunicationRepository(database), purchase_orders=PurchaseOrderRepository(database),
        price_history=PriceHistoryRepository(database),
    )


async def on_quotation_processed(database: Any, organization_id: str, quotation: dict) -> Optional[dict]:
    """Called after the processing pipeline finishes. Returns the run it started, if any."""
    if not settings.AGENT_AUTOPILOT:
        return None
    request_id = quotation.get("procurement_request_id")
    if not request_id or quotation.get("processing_status") not in COMPARABLE:
        return None
    request_id = str(request_id)

    requests = ProcurementRequestRepository(database)
    request = await requests.get(organization_id, request_id)
    if request is None or request.get("status") in ("awarded", "closed", "cancelled"):
        return None

    quotations = await QuotationRepository(database).for_request(organization_id, request_id)
    ready = [q for q in quotations if q.get("processing_status") in COMPARABLE]
    if len(ready) < settings.AGENT_AUTOPILOT_MIN_QUOTATIONS:
        return None

    runs = AgentRunRepository(database)
    existing = await runs.list(organization_id, {"graph": "supervisor", "input.procurement_request_id": request_id,
                                                 "status": {"$in": list(ACTIVE_RUN_STATUSES)}}, limit=1)
    if existing:
        return None  # one autonomous run per request at a time

    recorder = await RunRecorder(runs, organization_id, "supervisor",
                                 {"procurement_request_id": request_id, "started_by": "monitor_agent"},
                                 request.get("created_by")).start()
    async with recorder.step("Monitor Agent", "start sourcing") as step:
        step["summary"] = (f"{len(ready)} quotations ready for '{request['title']}' after "
                           f"{quotation.get('supplier_name') or 'a new quotation'} arrived.")
    ctx = await _context(database, organization_id, request.get("created_by"), recorder)
    return await run_supervisor(ctx, request)


async def follow_up_overdue_orders(database: Any) -> dict[str, int]:
    """Draft one follow-up per purchase order that is late, across all organizations."""
    summary = {"checked": 0, "drafted": 0}
    if not settings.AGENT_AUTOPILOT:
        return summary
    orders = PurchaseOrderRepository(database)
    communications = CommunicationRepository(database)
    overdue = await orders.collection.find(
        {"status": "issued", "expected_delivery_date": {"$lt": now()}}).to_list(length=200)

    for row in overdue:
        summary["checked"] += 1
        organization_id, po_id = str(row["organization_id"]), str(row["_id"])
        already = await communications.list(organization_id, {"purchase_order_id": po_id, "kind": "negotiation"}, limit=1)
        if already:
            continue
        expected = row.get("expected_delivery_date")
        days_late = (now().date() - expected.date()).days if expected else 0
        supplier = (row.get("supplier") or {}).get("name") or "Sir/Madam"
        draft = {
            "kind": "negotiation", "status": "draft",
            "subject": f"Delivery status: purchase order {row.get('po_number')}",
            "body": (f"Dear {supplier},\n\nPurchase order {row.get('po_number')} was expected on "
                     f"{expected:%d %b %Y} and is now {days_late} day(s) overdue.\n\n"
                     "Please confirm the dispatch status and a firm delivery date.\n\n"
                     f"Regards,\n{(row.get('buyer') or {}).get('name') or ''}"),
            "generated_by": "template", "provider": None, "model": None,
            "fallback_reason": "Written from the overdue-delivery template by the Monitor Agent.",
            "guardrail_findings": [], "to_email": (row.get("supplier") or {}).get("email"),
            "procurement_request_id": str(row["procurement_request_id"]) if row.get("procurement_request_id") else None,
            "supplier_id": row.get("supplier_id"), "purchase_order_id": po_id, "days_late": days_late,
        }
        await save_draft(communications, organization_id, "monitor-agent", draft, trigger="overdue_delivery")
        summary["drafted"] += 1
        logger.info("Monitor agent drafted a follow-up for overdue %s", row.get("po_number"))
    return summary
