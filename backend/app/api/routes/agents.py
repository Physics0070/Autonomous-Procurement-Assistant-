"""Agent graphs: sourcing runs, run timelines and the procurement assistant."""
from __future__ import annotations

from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import Field

from app.api.deps import DB, CurrentUser, comparison_repo, quotation_repo, request_repo, supplier_repo
from app.api.routes.automation import ai_provider, communication_repo
from app.core.errors import ConfigurationError
from app.integrations.ai.base import AIProvider, ChatMessage, ToolCall
from app.repositories.automation import AgentRunRepository, CommunicationRepository, ConversationRepository
from app.repositories.procurement_requests import ProcurementRequestRepository
from app.repositories.automation import PurchaseOrderRepository
from app.repositories.quotations import ComparisonRepository, PriceHistoryRepository, QuotationRepository
from app.repositories.suppliers import SupplierRepository
from app.schemas.common import APIModel
from app.services.agents.assistant import AssistantTools, run_assistant
from app.services.agents.runs import RunRecorder
from app.services.agents.specialists import AgentContext
from app.services.agents.supervisor import resume_supervisor, run_supervisor
from app.services.automation.communications import now
from app.services.agents.sourcing import run_sourcing

router = APIRouter(prefix="/agents", tags=["agents"])


def run_repo(database: DB) -> AgentRunRepository:
    return AgentRunRepository(database)


@router.post("/sourcing/{request_id}", status_code=201)
async def start_sourcing(
    request_id: str, context: CurrentUser,
    requests: ProcurementRequestRepository = Depends(request_repo),
    quotations: QuotationRepository = Depends(quotation_repo),
    suppliers: SupplierRepository = Depends(supplier_repo),
    comparisons: ComparisonRepository = Depends(comparison_repo),
    communications: CommunicationRepository = Depends(communication_repo),
    runs: AgentRunRepository = Depends(run_repo),
    provider: AIProvider = Depends(ai_provider),
) -> dict:
    org_id = context.organization_id
    request = await requests.get_or_404(org_id, request_id)
    recorder = await RunRecorder(runs, org_id, "sourcing", {"procurement_request_id": request_id}, context.user_id).start()
    return await run_sourcing(
        recorder=recorder, request=request, quotations=await quotations.for_request(org_id, request_id),
        suppliers_by_id={s["id"]: s for s in await suppliers.list(org_id, limit=500)},
        buyer=context.organization, user_id=context.user_id,
        comparisons=comparisons, communications=communications, provider=provider,
    )


class ResumeIn(APIModel):
    approved: bool = True


def _context(database, context: CurrentUser, recorder: RunRecorder, provider: AIProvider) -> AgentContext:
    return AgentContext(
        organization=context.organization, user_id=context.user_id, provider=provider, recorder=recorder,
        requests=ProcurementRequestRepository(database), quotations=QuotationRepository(database),
        suppliers=SupplierRepository(database), comparisons=ComparisonRepository(database),
        communications=CommunicationRepository(database), purchase_orders=PurchaseOrderRepository(database),
        price_history=PriceHistoryRepository(database),
    )


@router.post("/supervisor/{request_id}", status_code=201)
async def start_supervisor(
    request_id: str, context: CurrentUser, database: DB,
    requests: ProcurementRequestRepository = Depends(request_repo),
    runs: AgentRunRepository = Depends(run_repo),
    provider: AIProvider = Depends(ai_provider),
) -> dict:
    """Hand the whole request to the supervisor: it decides which agents run, and stops for approval."""
    request = await requests.get_or_404(context.organization_id, request_id)
    recorder = await RunRecorder(runs, context.organization_id, "supervisor",
                                 {"procurement_request_id": request_id}, context.user_id).start()
    return await run_supervisor(_context(database, context, recorder, provider), request)


@router.post("/runs/{run_id}/resume")
async def resume_run(
    run_id: str, context: CurrentUser, database: DB, payload: Optional[ResumeIn] = None,
    requests: ProcurementRequestRepository = Depends(request_repo),
    runs: AgentRunRepository = Depends(run_repo),
    provider: AIProvider = Depends(ai_provider),
) -> dict:
    """Continue a run that paused for approval (or cancel it)."""
    run = await runs.get_or_404(context.organization_id, run_id)
    request = await requests.get_or_404(context.organization_id, str((run.get("input") or {}).get("procurement_request_id")))
    recorder = RunRecorder.attach(runs, {**run, "organization_id": context.organization_id})
    return await resume_supervisor(_context(database, context, recorder, provider), run, request,
                                   approved=(payload or ResumeIn()).approved)


@router.get("/runs")
async def list_runs(context: CurrentUser, graph: Optional[str] = None, quotation_id: Optional[str] = None,
                    procurement_request_id: Optional[str] = None,
                    runs: AgentRunRepository = Depends(run_repo)) -> list[dict]:
    filters = {k: v for k, v in {"graph": graph, "input.quotation_id": quotation_id,
                                 "input.procurement_request_id": procurement_request_id}.items() if v}
    return await runs.list(context.organization_id, filters, limit=50)


@router.get("/runs/{run_id}")
async def get_run(run_id: str, context: CurrentUser, runs: AgentRunRepository = Depends(run_repo)) -> dict:
    return await runs.get_or_404(context.organization_id, run_id)


# ---------------------------------------------------------------------------
# Procurement Assistant
# ---------------------------------------------------------------------------

assistant_router = APIRouter(prefix="/assistant", tags=["assistant"])


class AssistantMessageIn(APIModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: Optional[str] = None


def conversation_repo(database: DB) -> ConversationRepository:
    return ConversationRepository(database)


def _to_chat(m: dict) -> ChatMessage:
    return ChatMessage(role=m["role"], content=m.get("content"), tool_call_id=m.get("tool_call_id"), name=m.get("name"),
                       tool_calls=[ToolCall(**{k: v for k, v in c.items() if k in ("id", "name", "arguments")})
                                   for c in m.get("tool_calls") or []])


@assistant_router.post("/messages")
async def send_message(
    payload: AssistantMessageIn, context: CurrentUser, database: DB,
    conversations: ConversationRepository = Depends(conversation_repo),
    provider: AIProvider = Depends(ai_provider),
) -> dict:
    if not provider.is_configured() or not provider.supports_tools:
        raise ConfigurationError(provider.configuration_error()
                                 or f"The {provider.name} provider does not support tool calling; use OpenRouter or Ollama.")
    org_id = context.organization_id
    conversation = (await conversations.get_or_404(org_id, payload.conversation_id) if payload.conversation_id
                    else await conversations.create(org_id, {"title": payload.message[:80], "messages": [], "created_by": context.user_id}))
    history = [_to_chat(m) for m in conversation["messages"]] + [ChatMessage(role="user", content=payload.message)]
    produced = await run_assistant(history, AssistantTools(database, context.organization, context.user_id, provider), provider)
    new = [{**asdict(m), "at": now()} for m in [history[-1], *produced]]
    await conversations.raw_update(org_id, conversation["id"], {"$push": {"messages": {"$each": new}}})
    return {"conversation_id": conversation["id"], "answer": produced[-1].content, "messages": new}


@assistant_router.get("/conversations")
async def list_conversations(context: CurrentUser, conversations: ConversationRepository = Depends(conversation_repo)) -> list[dict]:
    rows = await conversations.list(context.organization_id, limit=50)
    return [{"id": r["id"], "title": r["title"], "created_at": r["created_at"], "updated_at": r.get("updated_at"),
             "message_count": len(r["messages"])} for r in rows]


@assistant_router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, context: CurrentUser,
                           conversations: ConversationRepository = Depends(conversation_repo)) -> dict:
    return await conversations.get_or_404(context.organization_id, conversation_id)
