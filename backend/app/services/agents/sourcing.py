"""Sourcing graph: Comparison Agent -> Recommendation Agent -> Negotiation Agent -> awaiting_approval.

It prepares drafts only. Approving and sending stay with people (communications workflow).
"""
from __future__ import annotations

from typing import Any, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from app.integrations.ai.base import AIProvider
from app.repositories.automation import CommunicationRepository
from app.repositories.quotations import ComparisonRepository
from app.services.agents.runs import RunRecorder
from app.services.automation.communications import draft_negotiation, save_draft
from app.services.procurement.comparison import build_comparison
from app.services.procurement.explanation import explain_comparison


class SourcingState(TypedDict, total=False):
    comparison: Any
    communication_ids: list[str]


async def run_sourcing(
    *, recorder: RunRecorder, request: dict, quotations: list[dict], suppliers_by_id: dict[str, dict],
    buyer: dict, user_id: str, comparisons: ComparisonRepository, communications: CommunicationRepository,
    provider: Optional[AIProvider],
) -> dict[str, Any]:
    org_id = recorder.org_id

    async def compare(state: SourcingState) -> dict:
        async with recorder.step("Comparison Agent", "score and rank") as step:
            result = build_comparison(request, quotations, suppliers_by_id=suppliers_by_id)
            step["summary"] = (f"{len(result.suppliers)} quotation(s) ranked; top: {result.recommended_supplier_name}"
                               if result.suppliers else "; ".join(result.warnings) or "Nothing to compare")
            return {"comparison": result}

    async def recommend(state: SourcingState) -> dict:
        async with recorder.step("Recommendation Agent", "explain ranking") as step:
            result = state["comparison"]
            result.ai_explanation = await explain_comparison(result, provider)
            stored = await comparisons.upsert_for_request(
                org_id, request["id"], result.model_dump(mode="json", exclude={"id", "organization_id"}))
            result.id = str(stored["id"])
            step["summary"] = result.ai_explanation.summary or result.ai_explanation.unavailable_reason or ""
            return {"comparison": result}

    async def negotiate(state: SourcingState) -> dict:
        async with recorder.step("Negotiation Agent", "draft negotiation") as step:
            rows = [s.model_dump(mode="json") for s in state["comparison"].suppliers]
            top = rows[0]
            supplier = suppliers_by_id.get(str(top.get("supplier_id"))) or {}
            draft = await draft_negotiation(top, rows, request, buyer, provider, to_email=supplier.get("email"))
            created = await save_draft(communications, org_id, user_id, draft, agent_run_id=recorder.id)
            step["summary"] = f"Draft to {top['supplier_name']} ({draft['generated_by']}), awaiting approval"
            return {"communication_ids": [created["id"]]}

    graph = StateGraph(SourcingState)
    graph.add_node("comparison", compare)
    graph.add_node("recommendation", recommend)
    graph.add_node("negotiation", negotiate)
    graph.add_edge(START, "comparison")
    graph.add_conditional_edges("comparison", lambda s: "recommendation" if s["comparison"].suppliers else END)
    graph.add_edge("recommendation", "negotiation")
    graph.add_edge("negotiation", END)
    state = await graph.compile().ainvoke({"communication_ids": []})

    result = state["comparison"]
    if not result.suppliers:
        return await recorder.finish("no_quotations", {"warnings": result.warnings})
    return await recorder.finish("awaiting_approval", {
        "comparison_id": result.id,
        "recommended_quotation_id": result.recommended_quotation_id,
        "recommended_supplier_name": result.recommended_supplier_name,
        "communication_ids": state.get("communication_ids", []),
    })
