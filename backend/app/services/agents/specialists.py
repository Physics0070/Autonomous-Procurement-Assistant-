"""The specialist agents the supervisor hands work to.

Each one owns a job, its own tools and its own judgement. Scoring and tax stay
deterministic — an agent decides *what to do*, never what a number is. Every agent
degrades to a deterministic result when no LLM is configured, so the system still
works (and stays testable) without a key.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

from app.core.errors import AppError
from app.integrations.ai.base import AIProvider, ChatMessage
from app.integrations.ai.factory import for_task
from app.repositories.automation import CommunicationRepository, PurchaseOrderRepository
from app.repositories.procurement_requests import ProcurementRequestRepository
from app.repositories.quotations import ComparisonRepository, PriceHistoryRepository, QuotationRepository
from app.repositories.suppliers import SupplierRepository
from app.services.agents.loop import call_method, run_tool_loop, tool_schema
from app.services.agents.runs import RunRecorder
from app.services.analytics.reliability_ml import ORDER_FIELDS, load_model, orders_frame, predict
from app.services.automation import purchase_orders as po_service
from app.services.automation.communications import history_entry as _history_entry
from app.services.automation.communications import (
    check_negotiation_guardrail,
    draft_negotiation,
    negotiation_asks,
    save_draft,
)
from app.services.procurement.comparison import build_comparison
from app.services.procurement.explanation import explain_comparison

MAX_AGENT_ROUNDS = 4


@dataclass
class AgentContext:
    """Everything an agent may touch, already bound to one organization."""

    organization: dict
    user_id: str
    provider: Optional[AIProvider]
    recorder: RunRecorder
    requests: ProcurementRequestRepository
    quotations: QuotationRepository
    suppliers: SupplierRepository
    comparisons: ComparisonRepository
    communications: CommunicationRepository
    purchase_orders: PurchaseOrderRepository
    price_history: PriceHistoryRepository
    notes: list[str] = field(default_factory=list)

    @property
    def org_id(self) -> str:
        return str(self.organization["id"])

    def has_llm(self) -> bool:
        return bool(self.provider and self.provider.is_configured() and self.provider.supports_tools)


# ---------------------------------------------------------------------------
# Comparison — deterministic scoring, no model involved
# ---------------------------------------------------------------------------


async def comparison_agent(ctx: AgentContext, request: dict) -> dict:
    async with ctx.recorder.step("Comparison Agent", "score and rank") as step:
        quotations = await ctx.quotations.for_request(ctx.org_id, request["id"])
        suppliers = {s["id"]: s for s in await ctx.suppliers.list(ctx.org_id, limit=500)}
        result = build_comparison(request, quotations, suppliers_by_id=suppliers)
        stored = await ctx.comparisons.upsert_for_request(
            ctx.org_id, request["id"], result.model_dump(mode="json", exclude={"id", "organization_id"}))
        step["summary"] = (f"{len(result.suppliers)} quotation(s) ranked; top: {result.recommended_supplier_name}"
                           if result.suppliers else "; ".join(result.warnings) or "Nothing to compare")
        return {"comparison_id": str(stored["id"]), "rows": [s.model_dump(mode="json") for s in result.suppliers],
                "warnings": result.warnings, "result": result}


async def recommendation_agent(ctx: AgentContext, request: dict, comparison) -> dict:
    async with ctx.recorder.step("Recommendation Agent", "explain ranking") as step:
        comparison.ai_explanation = await explain_comparison(comparison, for_task(ctx.provider, "recommendation"))
        stored = await ctx.comparisons.upsert_for_request(
            ctx.org_id, request["id"], comparison.model_dump(mode="json", exclude={"id", "organization_id"}))
        summary = comparison.ai_explanation.summary or comparison.ai_explanation.unavailable_reason or ""
        step["summary"] = summary
        return {"comparison_id": str(stored["id"]), "explanation": summary,
                "recommended": comparison.recommended_supplier_name}


# ---------------------------------------------------------------------------
# Risk — ML delivery risk for the supplier about to be chosen
# ---------------------------------------------------------------------------


async def risk_agent(ctx: AgentContext, row: dict) -> dict:
    """Checks the recommended supplier's delivery record before money is committed."""
    async with ctx.recorder.step("Risk Agent", "assess delivery risk") as step:
        supplier_id = row.get("supplier_id")
        orders = orders_frame(await ctx.purchase_orders.find_all(
            ctx.org_id, {"status": {"$in": ["delivered", "closed"]}}, fields=ORDER_FIELDS))
        prediction = predict(load_model(ctx.org_id), str(supplier_id), orders) if supplier_id else None
        if prediction is None:
            step["summary"] = f"No delivery history for {row.get('supplier_name')} yet — rule-based score only."
            return {"risk": None, "concern": False}
        concern = prediction["risk_level"] in ("medium", "high")
        step["summary"] = (f"{row.get('supplier_name')}: {prediction['risk_level']} risk "
                           f"({prediction['late_probability']:.0%} late) from {prediction['history_count']} deliveries")
        return {"risk": prediction, "concern": concern,
                "signals": [s["text"] for s in prediction.get("signals", [])]}


# ---------------------------------------------------------------------------
# Negotiation — retrieval, then drafting, with the guardrail as its critic
# ---------------------------------------------------------------------------

NEGOTIATION_SYSTEM = (
    "You are the Negotiation Agent for {org}. Write one short, courteous negotiation email to {supplier} "
    "about {title}.\n"
    "First gather evidence with the tools: the supplier's own delivery record, what this organisation has paid "
    "for these items before, and how earlier negotiations with them went. Then call submit_draft.\n"
    "Rules: argue only from evidence you retrieved; never invent figures; never mention or imply any other "
    "supplier, their prices or that you have other quotations. submit_draft checks this and will reject a "
    "draft that breaks it — fix it and submit again. Stop after submit_draft accepts."
)

NEGOTIATION_TOOLS = [
    tool_schema("supplier_performance", "This supplier's delivery record and predicted late-delivery risk."),
    tool_schema("price_history", "What this organisation paid before for the requested items."),
    tool_schema("past_negotiations", "Earlier RFQ/negotiation emails to this supplier and what happened to them."),
    tool_schema("submit_draft", "Submit the finished email. Returns accepted, or the guardrail's objections.",
                subject=("string", "Email subject"), body=("string", "Plain-text email body"),
                **{"target_price?": ("number", "Total you are asking for, in the quotation's currency")}),
]


class NegotiationTools:
    def __init__(self, ctx: AgentContext, request: dict, row: dict, rows: list[dict], risk: Optional[dict]):
        self.ctx, self.request, self.row, self.rows, self.risk = ctx, request, row, rows, risk
        self.accepted: Optional[dict] = None
        self.rejections: list[str] = []

    async def supplier_performance(self) -> dict:
        supplier_id = self.row.get("supplier_id")
        pos = await self.ctx.purchase_orders.find_all(
            self.ctx.org_id, {"supplier_id": str(supplier_id), "status": {"$in": ["delivered", "closed"]}}) if supplier_id else []
        late = [p for p in pos if p.get("on_time") is False]
        return {
            "supplier": self.row.get("supplier_name"),
            "delivered_orders": len(pos),
            "late_orders": len(late),
            "worst_delay_days": max((p.get("delay_days") or 0 for p in pos), default=0),
            "quoted_delivery_days": self.row.get("delivery_days"),
            "predicted_late_risk": None if not self.risk else
                {"level": self.risk["risk_level"], "probability": round(self.risk["late_probability"], 3),
                 "why": [s["text"] for s in self.risk.get("signals", [])]},
        }

    async def price_history(self) -> dict:
        history = []
        for item in (self.request.get("items") or [])[:10]:
            name = item.get("normalized_name") or item.get("name")
            stats = await self.ctx.price_history.stats(self.ctx.org_id, name) if name else None
            if stats and stats.get("count"):
                history.append({"item": item.get("name"), "average_paid": round(stats["mean"], 2),
                                "lowest": stats.get("min"), "highest": stats.get("max"), "observations": stats["count"]})
        return {"items": history or "No past prices recorded for these items.",
                "this_quotation_total": self.row.get("total_cost"), "currency": self.row.get("currency")}

    async def past_negotiations(self) -> list[dict]:
        if not self.row.get("supplier_id"):
            return []
        rows = await self.ctx.communications.list(
            self.ctx.org_id, {"supplier_id": str(self.row["supplier_id"]), "kind": {"$in": ["negotiation", "rfq"]}}, limit=5)
        return [{"kind": r["kind"], "status": r["status"], "subject": r["subject"],
                 "asked_for": r.get("target_price"), "sent": r.get("sent_at") is not None} for r in rows]

    async def submit_draft(self, subject: str, body: str, target_price: Optional[float] = None) -> dict:
        findings = check_negotiation_guardrail(f"{subject}\n{body}", self.row.get("supplier_name"), self.rows)
        if findings:
            self.rejections.extend(findings)
            return {"accepted": False, "objections": findings,
                    "advice": "Remove every reference to other suppliers and their figures, then submit again."}
        self.accepted = {"subject": subject, "body": body, "target_price": target_price}
        return {"accepted": True}

    async def call(self, name: str, arguments: dict) -> Any:
        return await call_method(self, {t["function"]["name"] for t in NEGOTIATION_TOOLS}, name, arguments)


async def negotiation_agent(ctx: AgentContext, request: dict, row: dict, rows: list[dict],
                            risk: Optional[dict] = None) -> dict:
    """Drafts the negotiation email. Falls back to the template when there is no LLM,
    when the agent never produces an accepted draft, or when the critic rejects it."""
    async with ctx.recorder.step("Negotiation Agent", "research and draft") as step:
        supplier = await ctx.suppliers.get(ctx.org_id, row["supplier_id"]) if row.get("supplier_id") else None
        tools = NegotiationTools(ctx, request, row, rows, risk)
        draft: Optional[dict] = None
        evidence: list[str] = []
        llm = for_task(ctx.provider, "negotiation")

        if llm.is_configured() and llm.supports_tools:
            asks = negotiation_asks(row, None) or ["a better overall offer"]
            task = (f"Their quotation totals {row.get('total_cost')} {row.get('currency')}, delivery "
                    f"{row.get('delivery_days')} days, payment {row.get('payment_days')} days. "
                    f"We want: {', '.join(asks)}.")
            try:
                produced = await run_tool_loop(
                    llm,
                    system=NEGOTIATION_SYSTEM.format(org=ctx.organization.get("name"),
                                                     supplier=row.get("supplier_name"), title=request["title"]),
                    history=[ChatMessage(role="user", content=task)],
                    tools=NEGOTIATION_TOOLS,
                    execute=tools.call,
                    max_rounds=MAX_AGENT_ROUNDS,
                    on_step=lambda tool, args, result: evidence.append(tool),
                )
                if tools.accepted:
                    draft = {
                        "kind": "negotiation", "status": "draft", **tools.accepted,
                        "generated_by": "ai", "provider": llm.name, "model": llm.model,
                        "fallback_reason": None, "guardrail_findings": tools.rejections,
                        "procurement_request_id": request["id"], "supplier_id": row.get("supplier_id"),
                        "quotation_id": row.get("quotation_id"), "to_email": (supplier or {}).get("email"),
                        "evidence_used": sorted(set(evidence)),
                    }
                    verdict = await critic_agent(ctx, draft)
                    if not verdict["approved"]:
                        draft = None
                        step["summary"] = f"Critic rejected the AI draft: {'; '.join(verdict['issues'])}"
                _ = produced
            except AppError as exc:
                step["summary"] = f"AI unavailable ({exc.message}); using the template."

        if draft is None:
            draft = await draft_negotiation(row, rows, request, ctx.organization, llm,
                                            to_email=(supplier or {}).get("email"))
            if tools.rejections:
                draft["guardrail_findings"] = tools.rejections
        saved = await save_draft(ctx.communications, ctx.org_id, ctx.user_id, draft, agent_run_id=ctx.recorder.id)
        step["summary"] = (step["summary"] or "") + (
            f" Draft to {row.get('supplier_name')} ({draft['generated_by']}"
            f"{', evidence: ' + ', '.join(draft.get('evidence_used', [])) if draft.get('evidence_used') else ''}), "
            "awaiting approval.")
        return {"communication_id": saved["id"], "generated_by": draft["generated_by"],
                "guardrail_findings": draft.get("guardrail_findings", [])}


CRITIC_SYSTEM = (
    "You review outgoing procurement emails for an Indian SME. Reply with JSON only: "
    '{"approved": true|false, "issues": ["..."]}. Reject only for real problems: a figure that was never '
    "given to you, a mention of another supplier, a promise the buyer cannot keep, rudeness, or an empty "
    "message. Ordinary negotiation language is fine."
)


async def critic_agent(ctx: AgentContext, draft: dict) -> dict:
    """Second opinion on a draft. The deterministic guardrail stays the hard gate;
    this catches tone and invented facts, and never overrides a guardrail pass into a fail silently."""
    critic = for_task(ctx.provider, "critic")  # may be a council: several models review the draft
    if not critic.is_configured():
        return {"approved": True, "issues": [], "method": "skipped_no_llm"}
    async with ctx.recorder.step("Critic Agent", "review draft") as step:
        response = await critic.generate(
            f"Subject: {draft['subject']}\n\n{draft['body']}", system=CRITIC_SYSTEM, json_mode=True, temperature=0.0)
        if not response.ok:
            step["summary"] = f"Review skipped: {response.error}"
            return {"approved": True, "issues": [], "method": "skipped_error"}
        try:
            verdict = json.loads(response.text)
            approved = bool(verdict.get("approved", True))
            issues = [str(i) for i in (verdict.get("issues") or [])]
        except (ValueError, TypeError):
            step["summary"] = "Review skipped: the reply was not valid JSON."
            return {"approved": True, "issues": [], "method": "skipped_unparsable"}
        step["summary"] = "Approved" if approved else f"Rejected: {'; '.join(issues)}"
        return {"approved": approved, "issues": issues, "method": "llm_review"}


# ---------------------------------------------------------------------------
# Purchase order — deterministic build, always left for a human to approve
# ---------------------------------------------------------------------------


async def purchase_order_agent(ctx: AgentContext, request: dict, row: dict) -> dict:
    async with ctx.recorder.step("Purchase Order Agent", "draft purchase order") as step:
        quotation = await ctx.quotations.get_or_404(ctx.org_id, str(row["quotation_id"]))
        supplier = await ctx.suppliers.get(ctx.org_id, quotation["supplier_id"]) if quotation.get("supplier_id") else None
        po = po_service.build_purchase_order(request, quotation, supplier, ctx.organization)
        if not po["lines"]:
            step["summary"] = "No requested item is matched and priced in that quotation; no PO created."
            return {"purchase_order_id": None, "warnings": po["warnings"]}
        po["po_number"] = await ctx.purchase_orders.next_po_number(ctx.org_id, date.today().year)
        po["created_by"] = ctx.user_id
        po["history"] = [_history_entry("created", ctx.user_id, agent_run_id=ctx.recorder.id)]
        created = await ctx.purchase_orders.create(ctx.org_id, po)
        await ctx.requests.update(ctx.org_id, request["id"], {"status": "awarded"})
        step["summary"] = (f"{po['po_number']} for {row.get('supplier_name')}: {len(po['lines'])} line(s), "
                           f"{po['pricing']['currency']} {po['pricing']['total']:,.2f}, awaiting approval")
        return {"purchase_order_id": created["id"], "po_number": po["po_number"],
                "total": po["pricing"]["total"], "warnings": po["warnings"]}
