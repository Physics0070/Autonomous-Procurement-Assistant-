"""Supervisor agent: routing, handoffs, pausing for approval and resuming."""
import json

import pytest

from app.api.routes.automation import ai_provider
from app.integrations.ai.base import AIResponse
from app.main import app
from app.services.agents.supervisor import allowed_actions
from tests.fakes.llm import ScriptedProvider, answer, tool_call


def use(routes=None, chat=None, critic=None, explanation="Shree Steel is the balanced choice."):
    """A fake model that answers by which agent is asking, not by queue position.

    `routes` is the list of supervisor routing replies, in order.
    """
    queued = list(routes or [])

    def responder(prompt, system):
        system = system or ""
        if "Supervisor Agent" in system:
            return queued.pop(0) if queued else json.dumps({"action": "pause", "reason": "Waiting for a person."})
        if "review outgoing procurement emails" in system:
            return critic if critic is not None else json.dumps({"approved": True, "issues": []})
        return json.dumps({"summary": explanation, "reasoning": [], "risks": []})

    provider = ScriptedProvider(chat_responses=list(chat or []), responder=responder)
    app.dependency_overrides[ai_provider] = lambda: provider
    return provider


async def start(api, s):
    return await api.post(f"/api/v1/agents/supervisor/{s['request']['id']}", headers=s["headers"])


def test_the_policy_never_allows_an_order_before_comparison_and_approval():
    assert allowed_actions({}, []) == ["comparison"]
    assert allowed_actions({"rows": [{}]}, ["comparison"]) == ["recommendation", "risk"]
    assert allowed_actions({"rows": [{}]}, ["comparison", "recommendation"]) == ["risk", "negotiation"]
    # A drafted negotiation must be approved by a person before anything else happens.
    waiting = {"rows": [{}], "communication_id": "c1"}
    assert allowed_actions(waiting, ["comparison", "recommendation", "risk"]) == ["pause"]
    # Only after approval may it draft the purchase order, and that pauses again.
    approved = {**waiting, "approved_negotiation": True}
    assert allowed_actions(approved, ["comparison", "recommendation", "risk"]) == ["purchase_order"]
    done = ["comparison", "recommendation", "risk", "negotiation", "purchase_order"]
    assert allowed_actions({**approved, "purchase_order_id": "p1"}, done) == ["pause"]
    assert allowed_actions({**approved, "purchase_order_id": "p1", "approved_purchase_order": True}, done) == ["finish"]


async def test_supervisor_runs_the_specialists_and_stops_for_approval(api, sourcing):
    response = await start(api, sourcing)
    assert response.status_code == 201, response.text
    run = response.json()

    assert run["status"] == "awaiting_approval"
    assert [s["agent"] for s in run["steps"]] == [
        "Supervisor Agent", "Comparison Agent",
        "Supervisor Agent", "Recommendation Agent",
        "Supervisor Agent", "Risk Agent",
        "Supervisor Agent", "Negotiation Agent",
        "Supervisor Agent"]
    assert run["output"]["pending"]["waiting_for"] == "the negotiation draft"
    assert all(d["by"] == "policy" for d in run["output"]["decisions"])  # no LLM configured in tests

    drafts = (await api.get("/api/v1/communications", headers=sourcing["headers"])).json()
    assert [d["kind"] for d in drafts] == ["negotiation"] and drafts[0]["status"] == "draft"
    assert (await api.get("/api/v1/purchase-orders", headers=sourcing["headers"])).json() == []  # nothing ordered yet


async def test_approval_resumes_the_run_and_the_po_agent_takes_over(api, sourcing):
    h = sourcing["headers"]
    run = (await start(api, sourcing)).json()
    draft_id = run["output"]["pending"]["communication_id"]
    await api.post(f"/api/v1/communications/{draft_id}/approve", headers=h)

    resumed = (await api.post(f"/api/v1/agents/runs/{run['id']}/resume", headers=h, json={"approved": True})).json()
    assert resumed["status"] == "awaiting_approval"
    assert resumed["output"]["po_number"].startswith("PO-")
    assert [s["agent"] for s in resumed["steps"]][-2:] == ["Purchase Order Agent", "Supervisor Agent"]
    assert resumed["output"]["pending"]["waiting_for"].startswith("purchase order PO-")

    pos = (await api.get("/api/v1/purchase-orders", headers=h)).json()
    assert len(pos) == 1 and pos[0]["status"] == "draft"  # a person still approves the order itself

    # Approving the purchase order finishes the run.
    await api.post(f"/api/v1/purchase-orders/{pos[0]['id']}/approve", headers=h)
    done = (await api.post(f"/api/v1/agents/runs/{run['id']}/resume", headers=h, json={"approved": True})).json()
    assert done["status"] == "completed"
    assert (await api.post(f"/api/v1/agents/runs/{run['id']}/resume", headers=h, json={"approved": True})).status_code == 409


async def test_rejecting_cancels_the_run(api, sourcing):
    run = (await start(api, sourcing)).json()
    cancelled = (await api.post(f"/api/v1/agents/runs/{run['id']}/resume", headers=sourcing["headers"],
                                json={"approved": False})).json()
    assert cancelled["status"] == "cancelled"
    assert (await api.get("/api/v1/purchase-orders", headers=sourcing["headers"])).json() == []


async def test_the_llm_routes_but_only_within_the_allowed_actions(api, sourcing):
    # The supervisor only asks the model when more than one action is legal.
    use(routes=[
        json.dumps({"action": "purchase_order", "reason": "Just buy it."}),   # illegal here -> policy wins
        json.dumps({"action": "risk", "reason": "Check their delivery record."}),
        AIResponse(ok=False, error="Rate limited (429)."),                     # provider failure -> policy wins
    ])
    run = (await start(api, sourcing)).json()
    decisions = run["output"]["decisions"]

    assert decisions[0] == {"action": "comparison", "reason": "Policy order.", "by": "policy"}  # only one option
    assert decisions[1]["action"] == "recommendation" and "not allowed" in decisions[1]["reason"]
    assert decisions[2] == {"action": "risk", "reason": "Check their delivery record.", "by": "llm"}
    assert "429" in decisions[3]["reason"] and decisions[3]["by"] == "policy"
    assert run["status"] == "awaiting_approval"


async def test_the_negotiation_agent_gathers_evidence_before_drafting(api, sourcing):
    # Whichever supplier ranks first is the recipient; naming the other one must be rejected.
    names = [s["supplier_name"] for s in sourcing["comparison"]["suppliers"]]
    use(chat=[
        tool_call("supplier_performance", {}, call_id="c1"),
        tool_call("past_negotiations", {}, call_id="c2"),
        tool_call("submit_draft", {"subject": "Price", "body": f"{names[0]} and {names[1]} quoted less."}, call_id="c3"),
        tool_call("submit_draft", {"subject": "Revised offer for MS plates",
                                   "body": "You delivered on time before; please improve the price.",
                                   "target_price": 10800}, call_id="c4"),
        answer("Draft submitted."),
    ])
    run = (await start(api, sourcing)).json()
    assert run["status"] == "awaiting_approval"
    recipient = run["output"]["recommended_supplier_name"]
    competitor = next(n for n in names if n != recipient)

    draft = (await api.get("/api/v1/communications", headers=sourcing["headers"])).json()[0]
    assert draft["generated_by"] == "ai"
    assert draft["subject"] == "Revised offer for MS plates"
    assert competitor not in draft["body"]
    assert draft["guardrail_findings"] == [f"Names another supplier ({competitor})."]

    negotiation_step = next(s for s in run["steps"] if s["agent"] == "Negotiation Agent")
    assert "supplier_performance" in negotiation_step["summary"]  # evidence it actually researched


async def test_a_critic_rejection_falls_back_to_the_template(api, sourcing):
    use(chat=[tool_call("submit_draft", {"subject": "Hi", "body": "Give discount now."}, call_id="c1"),
              answer("done")],
        critic=json.dumps({"approved": False, "issues": ["Rude and vague."]}))
    run = (await start(api, sourcing)).json()
    assert "Critic Agent" in [s["agent"] for s in run["steps"]]
    draft = (await api.get("/api/v1/communications", headers=sourcing["headers"])).json()[0]
    assert draft["generated_by"] == "template" and draft["subject"] != "Hi"


async def test_supervisor_runs_are_isolated(api, sourcing, org_b):
    run = (await start(api, sourcing)).json()
    assert (await api.post(f"/api/v1/agents/runs/{run['id']}/resume", headers=org_b["headers"],
                           json={"approved": True})).status_code == 404
