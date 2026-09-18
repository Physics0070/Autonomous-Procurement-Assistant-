"""Procurement Assistant: tool loop, org-bound tools, draft-only actions, round limit, 503 without an LLM."""
import json

from app.api.routes.automation import ai_provider
from app.main import app
from app.services.agents.assistant import MAX_TOOL_ROUNDS
from tests.fakes.llm import ScriptedProvider, answer, tool_call


def use(*chat):
    provider = ScriptedProvider(chat_responses=list(chat))
    app.dependency_overrides[ai_provider] = lambda: provider
    return provider


async def ask(api, headers, text, conversation_id=None):
    return await api.post("/api/v1/assistant/messages", headers=headers,
                          json={"message": text, "conversation_id": conversation_id})


async def test_the_tool_loop_runs_and_answers_from_tool_results(api, sourcing):
    rid = sourcing["request"]["id"]
    provider = use(tool_call("get_comparison", {"procurement_request_id": rid}),
                   lambda messages, tools: answer(f"Top: {json.loads(messages[-1].content)['recommended_supplier_name']}"))
    response = await ask(api, sourcing["headers"], "Who should I buy the plates from?")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["answer"] == f"Top: {sourcing['comparison']['recommended_supplier_name']}"
    assert [m["role"] for m in body["messages"]] == ["user", "assistant", "tool", "assistant"]
    assert provider.chat_calls[0]["messages"][0].role == "system" and provider.chat_calls[0]["tools"]

    # The conversation continues with its history.
    use(answer("You're welcome."))
    follow = (await ask(api, sourcing["headers"], "Thanks", body["conversation_id"])).json()
    stored = (await api.get(f"/api/v1/assistant/conversations/{follow['conversation_id']}", headers=sourcing["headers"])).json()
    assert len(stored["messages"]) == 6


async def test_tools_are_bound_to_the_callers_organization(api, sourcing, org_b):
    rid = sourcing["request"]["id"]
    use(tool_call("get_procurement_request", {"request_id": rid, "organization_id": sourcing["request"]["organization_id"]}),
        lambda messages, tools: answer(messages[-1].content))
    body = (await ask(api, org_b["headers"], "Show me that request")).json()
    assert "not found" in body["answer"].lower() and "MS plates" not in body["answer"]


async def test_draft_tool_creates_a_draft_only(api, sourcing):
    use(tool_call("draft_rfq", {"procurement_request_id": sourcing["request"]["id"], "supplier_ids": [sourcing["apex"]["id"]]}),
        answer("Drafted an RFQ for Apex Metals; review it on the Communications page."))
    await ask(api, sourcing["headers"], "Send an RFQ to Apex")
    drafts = (await api.get("/api/v1/communications", headers=sourcing["headers"])).json()
    assert [(d["kind"], d["status"], d["to_email"]) for d in drafts] == [("rfq", "draft", "quotes@apexmetals.com")]


async def test_tool_rounds_are_limited(api, sourcing):
    use(*[tool_call("list_procurement_requests", {}, call_id=f"c{i}") for i in range(MAX_TOOL_ROUNDS + 3)])
    body = (await ask(api, sourcing["headers"], "Loop forever")).json()
    assert f"after {MAX_TOOL_ROUNDS} tool rounds" in body["answer"]
    assert sum(m["role"] == "tool" for m in body["messages"]) == MAX_TOOL_ROUNDS


async def test_503_without_an_llm(api, org_a):
    response = await ask(api, org_a["headers"], "Hello")
    assert response.status_code == 503 and "AI_PROVIDER" in response.json()["error"]["message"]
