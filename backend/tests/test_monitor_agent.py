"""Monitor agent: starts sourcing by itself, and chases overdue deliveries."""
from datetime import timedelta

import pytest

from app.core.config import settings
from app.repositories.automation import AgentRunRepository, PurchaseOrderRepository
from app.services.agents.monitor import follow_up_overdue_orders, on_quotation_processed
from app.services.automation.communications import now


@pytest.fixture
def autopilot(monkeypatch):
    monkeypatch.setattr(settings, "AGENT_AUTOPILOT", True)
    monkeypatch.setattr(settings, "AGENT_AUTOPILOT_MIN_QUOTATIONS", 2)


async def test_a_new_quotation_starts_sourcing_on_its_own(api, db, sourcing, autopilot):
    run = await on_quotation_processed(db, sourcing["q_apex"]["organization_id"],
                                       {**sourcing["q_apex"], "processing_status": "COMPLETED"})
    assert run is not None and run["status"] == "awaiting_approval"
    assert [s["agent"] for s in run["steps"]][:2] == ["Monitor Agent", "Supervisor Agent"]
    assert run["input"]["started_by"] == "monitor_agent"

    drafts = (await api.get("/api/v1/communications", headers=sourcing["headers"])).json()
    assert len(drafts) == 1 and drafts[0]["status"] == "draft"  # prepared, never sent

    # It does not pile up a second run for the same request while one is waiting.
    assert await on_quotation_processed(db, sourcing["q_apex"]["organization_id"],
                                        {**sourcing["q_apex"], "processing_status": "COMPLETED"}) is None


async def test_autopilot_waits_for_enough_quotations_and_can_be_switched_off(api, db, sourcing, autopilot, monkeypatch):
    monkeypatch.setattr(settings, "AGENT_AUTOPILOT_MIN_QUOTATIONS", 5)
    assert await on_quotation_processed(db, sourcing["q_apex"]["organization_id"],
                                        {**sourcing["q_apex"], "processing_status": "COMPLETED"}) is None

    monkeypatch.setattr(settings, "AGENT_AUTOPILOT_MIN_QUOTATIONS", 2)
    monkeypatch.setattr(settings, "AGENT_AUTOPILOT", False)
    assert await on_quotation_processed(db, sourcing["q_apex"]["organization_id"],
                                        {**sourcing["q_apex"], "processing_status": "COMPLETED"}) is None
    assert await AgentRunRepository(db).list(sourcing["q_apex"]["organization_id"]) == []


async def test_a_failed_quotation_does_not_trigger_anything(db, sourcing, autopilot):
    assert await on_quotation_processed(db, sourcing["q_apex"]["organization_id"],
                                        {**sourcing["q_apex"], "processing_status": "FAILED"}) is None


async def test_overdue_orders_get_one_follow_up_draft(api, db, sourcing, autopilot):
    h, org_id = sourcing["headers"], sourcing["q_shree"]["organization_id"]
    po = (await api.post(f"/api/v1/comparisons/procurement-requests/{sourcing['request']['id']}/award",
                         headers=h, json={"quotation_id": sourcing["q_shree"]["id"]})).json()
    for action in ("approve", "issue"):
        await api.post(f"/api/v1/purchase-orders/{po['id']}/{action}", headers=h)

    assert (await follow_up_overdue_orders(db))["drafted"] == 0  # not late yet

    await PurchaseOrderRepository(db).update(org_id, po["id"], {"expected_delivery_date": now() - timedelta(days=3)})
    assert (await follow_up_overdue_orders(db))["drafted"] == 1
    assert (await follow_up_overdue_orders(db))["drafted"] == 0  # never chases twice

    draft = [c for c in (await api.get("/api/v1/communications", headers=h)).json()
             if c["purchase_order_id"] == po["id"]][0]
    assert draft["status"] == "draft" and draft["days_late"] == 3
    assert po["po_number"] in draft["subject"] and "3 day(s) overdue" in draft["body"]
