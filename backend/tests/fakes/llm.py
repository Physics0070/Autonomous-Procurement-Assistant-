"""A scripted stand-in for an LLM provider.

Tests queue the exact responses the "model" gives, then assert on what the code
did with them - including which prompts and tools it sent.
"""
from __future__ import annotations

from typing import Any, Callable, Optional, Union

from app.integrations.ai.base import AIProvider, AIResponse, ChatMessage, ChatResult, ToolCall

ChatScript = Union[ChatResult, Callable[[list[ChatMessage], Optional[list[dict]]], ChatResult]]


class ScriptedProvider(AIProvider):
    name = "scripted"
    model = "scripted-model"
    supports_tools = True

    def __init__(
        self,
        responses: Optional[list[Union[AIResponse, str]]] = None,
        chat_responses: Optional[list[ChatScript]] = None,
    ) -> None:
        self.responses = list(responses or [])
        self.chat_responses = list(chat_responses or [])
        self.calls: list[dict[str, Any]] = []
        self.chat_calls: list[dict[str, Any]] = []

    def is_configured(self) -> bool:
        return True

    def configuration_error(self) -> Optional[str]:
        return None

    async def generate(self, prompt: str, *, system: Optional[str] = None, json_mode: bool = False,
                       temperature: float = 0.1, max_output_tokens: int = 8192) -> AIResponse:
        self.calls.append({"prompt": prompt, "system": system, "json_mode": json_mode})
        if not self.responses:
            return AIResponse(ok=False, error="script exhausted", provider=self.name, model=self.model)
        item = self.responses.pop(0)
        if isinstance(item, str):
            return AIResponse(text=item, ok=True, provider=self.name, model=self.model)
        return item

    async def chat(self, messages: list[ChatMessage], *, tools: Optional[list[dict]] = None,
                   temperature: float = 0.2, max_output_tokens: int = 2048) -> ChatResult:
        self.chat_calls.append({"messages": list(messages), "tools": tools})
        if not self.chat_responses:
            return ChatResult(ok=False, error="script exhausted", provider=self.name, model=self.model)
        item = self.chat_responses.pop(0)
        result = item(messages, tools) if callable(item) else item
        result.provider = result.provider or self.name
        result.model = result.model or self.model
        return result


def tool_call(name: str, arguments: dict[str, Any], call_id: str = "call-1") -> ChatResult:
    return ChatResult(ok=True, tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments)])


def answer(text: str) -> ChatResult:
    return ChatResult(ok=True, content=text, finish_reason="stop")
