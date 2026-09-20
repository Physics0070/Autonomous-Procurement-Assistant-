"""Supervisor agent: decides which specialist runs next, and pauses for human approval.

    supervisor ──> comparison ──┐
        ^                       │   every specialist hands control back with Command(goto="supervisor")
        ├──> recommendation <───┤
        ├──> risk           <───┤
        ├──> negotiation    <───┤
        └──> purchase_order <───┘

The supervisor picks the next agent with an LLM when one is configured, otherwise with the
same bounded policy the LLM is offered. Either way it may only choose from the actions the
policy allows, so an odd model reply can never skip an approval or exceed the step budget.

Pausing is durable: the run's state lives in `agent_runs`, so an approval days later (or
after a restart) resumes exactly where it stopped. LangGraph's own checkpointers are not
used because the MongoDB one requires a pymongo newer than Motor supports.
"""
from __future__ import annotations

import json
from typing import Any, Literal, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app.core.config import settings
from app.core.errors import ConflictError, NotFoundError
from app.services.agents import specialists as ag
from app.services.agents.runs import RunRecorder
from app.services.agents.specialists import AgentContext

Action = Literal["comparison", "recommendation", "risk", "negotiation", "purchase_order", "pause", "finish"]

ROUTING_SYSTEM = (
    "You are the Supervisor Agent of a procurement system for {org}. You choose which specialist works next "
    "on: {goal}\n\n"
    "Specialists — comparison: score and rank the quotations; recommendation: explain the ranking; "
    "risk: check the recommended supplier's delivery record with the ML model; negotiation: research and draft "
    "a negotiation email; purchase_order: draft the purchase order for the chosen quotation; "
    "pause: stop and wait for a person to approve what is waiting; finish: the goal is met.\n\n"
    'Reply with JSON only: {{"action": "<one of the allowed actions>", "reason": "<one short sentence>"}}. '
    "Choose only from the allowed actions given to you. Prefer gathering evidence before committing money: "
    "the buyer cannot be asked to approve a purchase order before the supplier has been compared and checked."
)


class SupervisorState(TypedDict, total=False):
    facts: dict[str, Any]
    done: list[str]
    steps: int
    decisions: list[dict[str, str]]
    pending: Optional[dict[str, Any]]
    status: str


def allowed_actions(facts: dict, done: list[str]) -> list[Action]:
    """The bounded policy: what may legally happen next, best first."""
    if not facts.get("rows"):
        return ["comparison"] if "comparison" not in done else ["finish"]
    if "recommendation" not in done:
        return ["recommendation", "risk"]
    if "risk" not in done:
        return ["risk", "negotiation"]
    if not facts.get("communication_id"):
        # Negotiating is optional: with nothing to improve on, go straight to the order.
        return ["negotiation", "purchase_order"] if facts.get("negotiable") else ["purchase_order", "negotiation"]
    if not facts.get("approved_negotiation"):
        return ["pause"]
    if not facts.get("purchase_order_id"):
        return ["purchase_order"]
    if not facts.get("approved_purchase_order"):
        return ["pause"]
    return ["finish"]


async def _choose(ctx: AgentContext, goal: str, state: SupervisorState, options: list[Action]) -> dict[str, str]:
    """LLM picks from `options`; anything else (or no LLM) falls back to the policy's first choice."""
    default = {"action": options[0], "reason": "Policy order.", "by": "policy"}
    if len(options) == 1 or not (ctx.provider and ctx.provider.is_configured()):
        return default
    facts = {k: v for k, v in state["facts"].items() if k != "result"}
    response = await ctx.provider.generate(
        f"Allowed actions: {options}\nDone so far: {state['done']}\nWhat we know: {json.dumps(facts, default=str)[:2000]}",
        system=ROUTING_SYSTEM.format(org=ctx.organization.get("name"), goal=goal), json_mode=True, temperature=0.0)
    if not response.ok:
        return {**default, "reason": f"{response.error} Fell back to policy order."}
    try:
        choice = json.loads(response.text)
        action = str(choice.get("action"))
        if action in options:
            return {"action": action, "reason": str(choice.get("reason") or "")[:200], "by": "llm"}
        return {**default, "reason": f"Model suggested '{action}', which is not allowed here; used policy order."}
    except (ValueError, TypeError):
        return {**default, "reason": "Model reply was not valid JSON; used policy order."}


def _top_row(facts: dict) -> dict:
    return facts["rows"][0]


async def run_supervisor(ctx: AgentContext, request: dict, *, state: Optional[SupervisorState] = None) -> dict:
    """Run (or continue) the supervisor loop until it pauses, finishes or runs out of steps."""
    goal = f"handle procurement request '{request['title']}'"
    budget = settings.AGENT_MAX_STEPS

    async def supervisor(state: SupervisorState) -> Command:
        if state["steps"] >= budget:
            return Command(goto=END, update={"status": "step_budget_reached"})
        options = allowed_actions(state["facts"], state["done"])
        decision = await _choose(ctx, goal, state, options)
        async with ctx.recorder.step("Supervisor Agent", f"route → {decision['action']}") as step:
            step["summary"] = f"{decision['reason']} ({decision['by']})"
        update = {"steps": state["steps"] + 1, "decisions": [*state["decisions"], decision]}
        if decision["action"] == "finish":
            return Command(goto=END, update={**update, "status": "completed"})
        if decision["action"] == "pause":
            waiting = ("the negotiation draft" if not state["facts"].get("approved_negotiation")
                       else f"purchase order {state['facts'].get('po_number')}")
            return Command(goto=END, update={
                **update, "status": "awaiting_approval",
                "pending": {"waiting_for": waiting,
                            "communication_id": state["facts"].get("communication_id"),
                            "purchase_order_id": state["facts"].get("purchase_order_id")}})
        return Command(goto=decision["action"], update=update)

    async def comparison(state: SupervisorState) -> Command:
        result = await ag.comparison_agent(ctx, request)
        facts = {**state["facts"], "comparison_id": result["comparison_id"], "rows": result["rows"],
                 "warnings": result["warnings"], "result": result["result"],
                 "negotiable": bool(result["rows"] and _negotiable(result["rows"][0]))}
        return Command(goto="supervisor", update={"facts": facts, "done": [*state["done"], "comparison"]})

    async def recommendation(state: SupervisorState) -> Command:
        comparison = state["facts"].get("result") or await _rebuild_comparison(ctx, request["id"])
        result = await ag.recommendation_agent(ctx, request, comparison)
        return Command(goto="supervisor", update={
            "facts": {**state["facts"], "explanation": result["explanation"], "recommended": result["recommended"]},
            "done": [*state["done"], "recommendation"]})

    async def risk(state: SupervisorState) -> Command:
        result = await ag.risk_agent(ctx, _top_row(state["facts"]))
        facts = {**state["facts"], "risk": result.get("risk"), "risk_concern": result.get("concern", False)}
        if result.get("concern"):
            facts["negotiable"] = True  # a shaky delivery record is worth raising before ordering
        return Command(goto="supervisor", update={"facts": facts, "done": [*state["done"], "risk"]})

    async def negotiation(state: SupervisorState) -> Command:
        facts = state["facts"]
        result = await ag.negotiation_agent(ctx, request, _top_row(facts), facts["rows"], facts.get("risk"))
        return Command(goto="supervisor", update={
            "facts": {**facts, "communication_id": result["communication_id"],
                      "negotiation_by": result["generated_by"]},
            "done": [*state["done"], "negotiation"]})

    async def purchase_order(state: SupervisorState) -> Command:
        result = await ag.purchase_order_agent(ctx, request, _top_row(state["facts"]))
        return Command(goto="supervisor", update={
            "facts": {**state["facts"], "purchase_order_id": result["purchase_order_id"],
                      "po_number": result.get("po_number"), "po_warnings": result.get("warnings", [])},
            "done": [*state["done"], "purchase_order"]})

    graph = StateGraph(SupervisorState)
    for name, node in (("supervisor", supervisor), ("comparison", comparison), ("recommendation", recommendation),
                       ("risk", risk), ("negotiation", negotiation), ("purchase_order", purchase_order)):
        graph.add_node(name, node)
    graph.add_edge(START, "supervisor")

    start: SupervisorState = state or {"facts": {}, "done": [], "steps": 0, "decisions": [], "pending": None,
                                       "status": "running"}
    final = await graph.compile().ainvoke(start, {"recursion_limit": 4 * budget + 10})
    return await _persist(ctx, final)


async def _rebuild_comparison(ctx: AgentContext, request_id: str):
    """A resumed run reloads the stored comparison instead of re-scoring it."""
    from app.schemas.comparison import ComparisonResult

    stored = await ctx.comparisons.latest_for_request(ctx.org_id, request_id)
    if not stored:
        raise NotFoundError("No comparison has been computed for this request.")
    return ComparisonResult.model_validate(stored)


def _negotiable(row: dict) -> bool:
    """Is there anything worth asking this supplier to improve?"""
    weak = settings.NEGOTIATION_WEAK_CRITERION_SCORE
    return any(c.get("score", 1) < weak for c in row.get("criteria") or [])


async def _persist(ctx: AgentContext, state: SupervisorState) -> dict:
    """Store the state so an approval later can resume this run, and finish the record."""
    facts = {k: v for k, v in state["facts"].items() if k not in ("result", "rows")}
    facts["top_supplier"] = (state["facts"].get("rows") or [{}])[0].get("supplier_name")
    saved = {"facts": facts, "done": state["done"], "steps": state["steps"],
             "decisions": state["decisions"], "pending": state.get("pending"), "status": state["status"]}
    await ctx.recorder.save_state(saved)
    return await ctx.recorder.finish(state["status"], {
        "pending": state.get("pending"), "decisions": state["decisions"],
        "comparison_id": facts.get("comparison_id"), "recommended_supplier_name": facts.get("recommended"),
        "communication_ids": [facts["communication_id"]] if facts.get("communication_id") else [],
        "purchase_order_id": facts.get("purchase_order_id"), "po_number": facts.get("po_number"),
        "risk": facts.get("risk"),
    })


async def resume_supervisor(ctx: AgentContext, run: dict, request: dict, *, approved: bool) -> dict:
    """Continue a paused run after a person approved (or rejected) what it was waiting for."""
    if run.get("status") != "awaiting_approval" or not run.get("state"):
        raise ConflictError(f"This run is {run.get('status')}, so there is nothing to resume.")
    saved = run["state"]
    facts = dict(saved["facts"])
    if not approved:
        await ctx.recorder.save_state({**saved, "status": "cancelled"})
        return await ctx.recorder.finish("cancelled", {"reason": "A person rejected what the run was waiting for."})
    facts["approved_negotiation" if not facts.get("approved_negotiation") else "approved_purchase_order"] = True
    # rows are rebuilt from the stored comparison so the agents see the same figures as before
    stored = await ctx.comparisons.latest_for_request(ctx.org_id, request["id"])
    if not stored:
        raise NotFoundError("The comparison this run was based on no longer exists.")
    state: SupervisorState = {
        "facts": {**facts, "rows": stored["suppliers"], "result": None},
        "done": list(saved["done"]), "steps": int(saved["steps"]), "decisions": list(saved["decisions"]),
        "pending": None, "status": "running",
    }
    return await run_supervisor(ctx, request, state=state)
