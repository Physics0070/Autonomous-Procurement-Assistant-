"""Procurement Assistant: agent <-> tools loop (LangGraph), at most MAX_TOOL_ROUNDS tool rounds.

Every tool is bound to the caller's organization on the server. The model never
supplies an organization id; any argument it invents that a tool doesn't take is dropped.
"""
from __future__ import annotations

import inspect
import json
from typing import Any, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from app.core.config import settings
from app.core.errors import AppError, UpstreamError
from app.integrations.ai.base import AIProvider, ChatMessage
from app.repositories.automation import CommunicationRepository, PurchaseOrderRepository
from app.repositories.procurement_requests import ProcurementRequestRepository
from app.repositories.quotations import ComparisonRepository, QuotationRepository
from app.repositories.suppliers import SupplierRepository
from app.services.analytics.spend import spend_summary
from app.services.automation import communications as comms

MAX_TOOL_ROUNDS = settings.ASSISTANT_MAX_TOOL_ROUNDS

SYSTEM = (
    "You are the Procurement Assistant for {org}. Answer only from tool results; never invent figures, "
    "suppliers or dates. If the tools don't have it, say so. Amounts are in the currency the tools report. "
    "You can prepare RFQ and negotiation email drafts, but you cannot approve or send anything - a person "
    "reviews drafts on the Communications page. Be concise."
)


def _schema(name: str, description: str, **props: tuple[str, str]) -> dict:
    """props: name -> (json type, description); every prop ending in '?' is optional."""
    properties = {k.rstrip("?"): {"type": t, "description": d} for k, (t, d) in props.items()}
    for k, (t, _) in props.items():
        if t == "array":
            properties[k.rstrip("?")]["items"] = {"type": "string"}
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties, "required": [k for k in props if not k.endswith("?")]}}}


TOOLS = [
    _schema("list_procurement_requests", "List procurement requests, newest first.", **{"status?": ("string", "draft|open|comparing|awarded|closed|cancelled")}),
    _schema("get_procurement_request", "One procurement request with its items.", request_id=("string", "Request id")),
    _schema("search_quotations", "Quotations, optionally for one request or supplier, or matching a supplier name.",
            **{"procurement_request_id?": ("string", "Request id"), "supplier_name?": ("string", "Part of a supplier name")}),
    _schema("get_quotation", "One quotation's extracted items, prices and terms.", quotation_id=("string", "Quotation id")),
    _schema("get_comparison", "The stored supplier comparison (scores, ranking, recommendation) for a request.",
            procurement_request_id=("string", "Request id")),
    _schema("get_supplier", "A supplier by id or name, with reliability.", **{"supplier_id?": ("string", "Supplier id"), "name?": ("string", "Supplier name")}),
    _schema("spend_summary", "Spend by supplier, month and item from issued/delivered purchase orders, plus savings and on-time rates."),
    _schema("draft_rfq", "Create RFQ email DRAFTS (not sent) for a request to chosen suppliers.",
            procurement_request_id=("string", "Request id"), supplier_ids=("array", "Supplier ids")),
    _schema("draft_negotiation", "Create a negotiation email DRAFT (not sent) to the supplier of one compared quotation.",
            procurement_request_id=("string", "Request id"), quotation_id=("string", "Quotation id")),
]


def _slim(doc: Optional[dict], *keys: str) -> Optional[dict]:
    return {k: doc.get(k) for k in keys if doc.get(k) is not None} if doc else None


class AssistantTools:
    """Server-side tool implementations, closed over the caller's organization."""

    def __init__(self, db, organization: dict, user_id: str, provider: AIProvider):
        self.org_id, self.org, self.user_id, self.provider = organization["id"], organization, user_id, provider
        self.requests, self.quotations = ProcurementRequestRepository(db), QuotationRepository(db)
        self.suppliers, self.comparisons = SupplierRepository(db), ComparisonRepository(db)
        self.communications, self.pos = CommunicationRepository(db), PurchaseOrderRepository(db)

    async def list_procurement_requests(self, status: Optional[str] = None):
        rows = await self.requests.list_with_counts(self.org_id, status=status, limit=25)
        return [_slim(r, "id", "title", "status", "quotation_count", "required_by") for r in rows]

    async def get_procurement_request(self, request_id: str):
        r = await self.requests.get_or_404(self.org_id, request_id)
        return {**_slim(r, "id", "title", "status", "department", "required_by", "currency"),
                "items": [_slim(i, "item_id", "name", "quantity", "unit", "specifications") for i in r.get("items") or []]}

    async def search_quotations(self, procurement_request_id: Optional[str] = None, supplier_name: Optional[str] = None):
        rows = await self.quotations.list_filtered(self.org_id, procurement_request_id=procurement_request_id, limit=50)
        if supplier_name:
            rows = [r for r in rows if supplier_name.lower() in (r.get("supplier_name") or "").lower()]
        return [_slim(r, "id", "supplier_name", "procurement_request_id", "processing_status", "total_amount", "currency", "item_count")
                for r in rows[:25]]

    async def get_quotation(self, quotation_id: str):
        q = await self.quotations.get_or_404(self.org_id, quotation_id)
        data = q.get("effective_data") or q.get("normalized_data") or {}
        return {**_slim(q, "id", "supplier_name", "processing_status", "procurement_request_id"),
                "items": [_slim(i, "original_name", "quantity", "unit", "unit_price", "tax_percentage", "total_price") for i in data.get("items") or []],
                "pricing": data.get("pricing"), "delivery": data.get("delivery"), "payment_terms": data.get("payment_terms")}

    async def get_comparison(self, procurement_request_id: str):
        c = await self.comparisons.latest_for_request(self.org_id, procurement_request_id)
        if not c:
            return {"error": "No comparison has been run for this request yet."}
        return {"recommended_supplier_name": c.get("recommended_supplier_name"), "warnings": c.get("warnings"),
                "explanation": (c.get("ai_explanation") or {}).get("summary"),
                "suppliers": [_slim(s, "rank", "supplier_name", "quotation_id", "overall_score", "total_cost", "landed_cost",
                                    "transport_cost", "delivery_days", "payment_days", "coverage", "price_anomaly") for s in c["suppliers"]]}

    async def get_supplier(self, supplier_id: Optional[str] = None, name: Optional[str] = None):
        s = await self.suppliers.get(self.org_id, supplier_id) if supplier_id else await self.suppliers.find_by_name(self.org_id, name or "")
        return _slim(s, "id", "name", "email", "phone", "gst_number", "reliability") or {"error": "Supplier not found."}

    async def spend_summary(self):
        return spend_summary(await self.pos.find_all(self.org_id), await self.quotations.list_filtered(self.org_id, limit=500))

    async def draft_rfq(self, procurement_request_id: str, supplier_ids: list[str]):
        request = await self.requests.get_or_404(self.org_id, procurement_request_id)
        chosen = [await self.suppliers.get_or_404(self.org_id, s) for s in supplier_ids]
        drafts = await comms.draft_rfqs(request, chosen, self.org, self.provider)
        saved = [await comms.save_draft(self.communications, self.org_id, self.user_id, d, via="assistant") for d in drafts]
        return [{"communication_id": d["id"], "to": d.get("to_email"), "status": d["status"]} for d in saved]

    async def draft_negotiation(self, procurement_request_id: str, quotation_id: str):
        request = await self.requests.get_or_404(self.org_id, procurement_request_id)
        c = await self.comparisons.latest_for_request(self.org_id, procurement_request_id)
        row = next((s for s in (c or {}).get("suppliers", []) if str(s["quotation_id"]) == quotation_id), None)
        if row is None:
            return {"error": "That quotation is not in this request's comparison."}
        supplier = await self.suppliers.get(self.org_id, row["supplier_id"]) if row.get("supplier_id") else None
        draft = await comms.draft_negotiation(row, c["suppliers"], request, self.org, self.provider, to_email=(supplier or {}).get("email"))
        saved = await comms.save_draft(self.communications, self.org_id, self.user_id, draft, via="assistant")
        return {"communication_id": saved["id"], "status": saved["status"], "target_price": saved.get("target_price")}

    async def call(self, name: str, arguments: dict) -> Any:
        fn = getattr(self, name, None) if name in {t["function"]["name"] for t in TOOLS} else None
        if fn is None:
            return {"error": f"Unknown tool {name}."}
        accepted = inspect.signature(fn).parameters
        try:
            return await fn(**{k: v for k, v in arguments.items() if k in accepted})
        except (AppError, TypeError) as exc:
            return {"error": getattr(exc, "message", str(exc))}


class AssistantState(TypedDict, total=False):
    messages: list[ChatMessage]
    rounds: int


async def run_assistant(history: list[ChatMessage], tools: AssistantTools, provider: AIProvider) -> list[ChatMessage]:
    """Returns only the messages produced in this turn (assistant + tool messages)."""
    system = ChatMessage(role="system", content=SYSTEM.format(org=tools.org.get("name")))

    async def agent(state: AssistantState) -> dict:
        result = await provider.chat([system, *state["messages"]], tools=TOOLS)
        if not result.ok:
            raise UpstreamError(f"The AI provider failed: {result.error}")
        reply = ChatMessage(role="assistant", content=result.content, tool_calls=result.tool_calls)
        return {"messages": [*state["messages"], reply]}

    async def run_tools(state: AssistantState) -> dict:
        outputs = [
            ChatMessage(role="tool", tool_call_id=call.id, name=call.name,
                        content=json.dumps(await tools.call(call.name, call.arguments), default=str)[:12000])
            for call in state["messages"][-1].tool_calls
        ]
        return {"messages": [*state["messages"], *outputs], "rounds": state["rounds"] + 1}

    async def give_up(state: AssistantState) -> dict:
        note = ChatMessage(role="assistant", content=f"I stopped after {MAX_TOOL_ROUNDS} tool rounds without a final answer. "
                                                     "Please ask a narrower question.")
        return {"messages": [*state["messages"], note]}

    def route(state: AssistantState) -> str:
        if not state["messages"][-1].tool_calls:
            return END
        return "tools" if state["rounds"] < MAX_TOOL_ROUNDS else "give_up"

    graph = StateGraph(AssistantState)
    graph.add_node("agent", agent)
    graph.add_node("tools", run_tools)
    graph.add_node("give_up", give_up)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route)
    graph.add_edge("tools", "agent")
    graph.add_edge("give_up", END)
    state = await graph.compile().ainvoke({"messages": list(history), "rounds": 0},
                                          {"recursion_limit": 3 * MAX_TOOL_ROUNDS + 5})
    return state["messages"][len(history):]
