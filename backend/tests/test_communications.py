"""RFQ / negotiation drafts, the competitor guardrail, the status machine and .eml export."""
import json
from email import message_from_bytes

import pytest

from app.api.routes.automation import ai_provider
from app.integrations.ai.base import AIResponse
from app.main import app
from app.services.automation.communications import check_negotiation_guardrail
from tests.fakes.llm import ScriptedProvider


def use_llm(*replies):
    provider = ScriptedProvider(responses=list(replies))
    app.dependency_overrides[ai_provider] = lambda: provider
    return provider


async def rfq(api, s, supplier="shree"):
    response = await api.post(f"/api/v1/procurement-requests/{s['request']['id']}/rfqs", headers=s["headers"],
                              json={"supplier_ids": [s[supplier]["id"]]})
    assert response.status_code == 201, response.text
    return response.json()[0]


async def test_template_rfq_lists_every_item(api, sourcing):
    draft = await rfq(api, sourcing)
    assert draft["generated_by"] == "template"
    assert "AI_PROVIDER" in draft["fallback_reason"]
    assert draft["status"] == "draft" and draft["to_email"] == "sales@shreesteel.com"
    assert "MS plate 10mm: 100 kg - IS 2062" in draft["body"]
    assert "Hex bolt M12: 500 pcs" in draft["body"]


async def test_ai_rfq_is_recorded_as_ai(api, sourcing):
    use_llm(json.dumps({"subject": "RFQ - MS plates", "body": "Dear Shree Steel, please quote..."}))
    draft = await rfq(api, sourcing)
    assert (draft["generated_by"], draft["provider"], draft["subject"]) == ("ai", "scripted", "RFQ - MS plates")


async def test_ai_failure_falls_back_to_the_template_with_the_reason(api, sourcing):
    use_llm(AIResponse(ok=False, error="Rate limited (429)."))
    draft = await rfq(api, sourcing)
    assert draft["generated_by"] == "template" and draft["fallback_reason"] == "Rate limited (429)."


def test_guardrail_catches_competitor_names_and_amounts():
    rows = [{"supplier_name": "Shree Steel", "total_cost": 11450.0},
            {"supplier_name": "Apex Metals", "total_cost": 6800.0, "landed_cost": 8824.0}]
    assert check_negotiation_guardrail("Please match 10,000.", "Shree Steel", rows) == []
    assert check_negotiation_guardrail("apex metals is cheaper", "Shree Steel", rows) == ["Names another supplier (Apex Metals)."]
    assert check_negotiation_guardrail("Others quote INR 6,800.00", "Shree Steel", rows) == ["States another supplier's amount (6,800.00)."]


async def test_negotiation_targets_5_percent_below_and_rejects_a_leaky_ai_draft(api, sourcing):
    use_llm(json.dumps({"subject": "Price", "body": "Apex Metals offered INR 6,800. Please match."}))
    response = await api.post(
        f"/api/v1/comparisons/procurement-requests/{sourcing['request']['id']}/negotiations",
        headers=sourcing["headers"], json={"quotation_id": sourcing["q_shree"]["id"]})
    assert response.status_code == 201, response.text
    draft = response.json()
    assert draft["generated_by"] == "template"
    assert draft["target_price"] == pytest.approx(11450 * 0.95)
    assert "Apex" not in draft["body"] and "INR 10,877.50" in draft["body"]
    assert "Names another supplier (Apex Metals)." in draft["guardrail_findings"]


async def test_status_machine(api, sourcing):
    h, draft = sourcing["headers"], await rfq(api, sourcing)
    base = f"/api/v1/communications/{draft['id']}"
    assert (await api.post(f"{base}/mark-sent", headers=h)).status_code == 409
    edited = await api.patch(base, headers=h, json={"subject": "Updated subject"})
    assert edited.json()["subject"] == "Updated subject"
    approved = (await api.post(f"{base}/approve", headers=h)).json()
    assert approved["status"] == "approved" and approved["approved_by"]
    assert (await api.patch(base, headers=h, json={"body": "late edit"})).status_code == 409
    sent = (await api.post(f"{base}/mark-sent", headers=h)).json()
    assert sent["status"] == "sent" and [e["action"] for e in sent["history"]] == ["created", "edited", "approve", "mark_sent"]
    assert (await api.post(f"{base}/cancel", headers=h)).status_code == 409


async def test_eml_export(api, sourcing):
    draft = await rfq(api, sourcing)
    response = await api.get(f"/api/v1/communications/{draft['id']}/eml", headers=sourcing["headers"])
    message = message_from_bytes(response.content)
    assert response.headers["content-type"].startswith("message/rfc822")
    assert message["To"] == "sales@shreesteel.com" and message["X-Unsent"] == "1"
    assert "MS plate 10mm" in message.get_payload(decode=True).decode()


async def test_communications_are_isolated_per_organization(api, sourcing, org_b):
    draft = await rfq(api, sourcing)
    assert (await api.get(f"/api/v1/communications/{draft['id']}", headers=org_b["headers"])).status_code == 404
    assert (await api.get("/api/v1/communications", headers=org_b["headers"])).json() == []
    assert (await api.post(f"/api/v1/communications/{draft['id']}/approve", headers=org_b["headers"])).status_code == 404
