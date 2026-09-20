"""The agent loop: model → tools → model, until it answers or runs out of rounds.

Every agent in the system (assistant and specialists) runs on this one LangGraph loop,
so they all share the same round limit, the same tool-error handling and the same
recording. Tools are always executed server-side by `execute`; the model only names them.
"""
from __future__ import annotations

import inspect
import json
from typing import Any, Awaitable, Callable, Optional, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph

from app.core.errors import AppError, UpstreamError
from app.integrations.ai.base import AIProvider, ChatMessage

MAX_TOOL_OUTPUT_CHARS = 12000


class StepSink(Protocol):
    """Called after each tool call so a run can be shown as a timeline."""

    def __call__(self, tool: str, arguments: dict, result: Any) -> None: ...


class LoopState(TypedDict, total=False):
    messages: list[ChatMessage]
    rounds: int


def tool_schema(name: str, description: str, **props: tuple[str, str]) -> dict:
    """props: name -> (json type, description); a name ending in '?' is optional."""
    properties: dict[str, dict] = {}
    for key, (json_type, text) in props.items():
        properties[key.rstrip("?")] = {"type": json_type, "description": text}
        if json_type == "array":
            properties[key.rstrip("?")]["items"] = {"type": "string"}
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties, "required": [k for k in props if not k.endswith("?")]}}}


async def call_method(owner: Any, allowed: set[str], name: str, arguments: dict) -> Any:
    """Run `owner.<name>(**arguments)` when the tool is allowed.

    Arguments the method does not accept are dropped, which is what stops a model from
    widening a tool's scope (for example by passing another organization's id).
    """
    method = getattr(owner, name, None) if name in allowed else None
    if method is None:
        return {"error": f"Unknown tool {name}."}
    accepted = inspect.signature(method).parameters
    try:
        result = method(**{k: v for k, v in arguments.items() if k in accepted})
        return await result if inspect.isawaitable(result) else result
    except (AppError, TypeError, ValueError) as exc:
        # Tool failures are data for the model to react to, not crashes.
        return {"error": getattr(exc, "message", str(exc))}


async def run_tool_loop(
    provider: AIProvider,
    *,
    system: str,
    history: list[ChatMessage],
    tools: list[dict],
    execute: Callable[[str, dict], Awaitable[Any]],
    max_rounds: int,
    on_step: Optional[StepSink] = None,
    give_up_message: Optional[str] = None,
) -> list[ChatMessage]:
    """Returns only the messages produced in this turn (assistant and tool messages)."""
    system_message = ChatMessage(role="system", content=system)

    async def agent(state: LoopState) -> dict:
        result = await provider.chat([system_message, *state["messages"]], tools=tools)
        if not result.ok:
            raise UpstreamError(f"The AI provider failed: {result.error}")
        reply = ChatMessage(role="assistant", content=result.content, tool_calls=result.tool_calls)
        return {"messages": [*state["messages"], reply]}

    async def run_tools(state: LoopState) -> dict:
        outputs = []
        for call in state["messages"][-1].tool_calls:
            result = await execute(call.name, call.arguments)
            if on_step:
                on_step(call.name, call.arguments, result)
            outputs.append(ChatMessage(role="tool", tool_call_id=call.id, name=call.name,
                                       content=json.dumps(result, default=str)[:MAX_TOOL_OUTPUT_CHARS]))
        return {"messages": [*state["messages"], *outputs], "rounds": state["rounds"] + 1}

    async def give_up(state: LoopState) -> dict:
        note = ChatMessage(role="assistant", content=give_up_message or
                           f"I stopped after {max_rounds} tool rounds without a final answer. "
                           "Please ask a narrower question.")
        return {"messages": [*state["messages"], note]}

    def route(state: LoopState) -> str:
        if not state["messages"][-1].tool_calls:
            return END
        return "tools" if state["rounds"] < max_rounds else "give_up"

    graph = StateGraph(LoopState)
    graph.add_node("agent", agent)
    graph.add_node("tools", run_tools)
    graph.add_node("give_up", give_up)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route)
    graph.add_edge("tools", "agent")
    graph.add_edge("give_up", END)
    state = await graph.compile().ainvoke({"messages": list(history), "rounds": 0},
                                          {"recursion_limit": 3 * max_rounds + 5})
    return state["messages"][len(history):]
