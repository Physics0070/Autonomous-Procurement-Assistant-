"""AI provider abstraction.

No service outside this package may import a vendor SDK or call a model API.
Everything talks to AIProvider, so adding or swapping a provider is a new file
here and a config value - nothing else changes.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class AIResponse:
    text: str = ""
    ok: bool = True
    error: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    raw: Optional[Any] = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    raw_arguments: str = ""


@dataclass
class ChatMessage:
    role: str  # system | user | assistant | tool
    content: Optional[str] = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: Optional[str] = None
    name: Optional[str] = None


@dataclass
class ChatResult:
    ok: bool = True
    content: Optional[str] = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    error: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    finish_reason: Optional[str] = None
    meta: dict[str, Any] = field(default_factory=dict)


class AIProvider(abc.ABC):
    name: str = "abstract"
    model: str = ""
    # Whether chat() supports tool calling (required by the assistant agent).
    supports_tools: bool = False

    @abc.abstractmethod
    def is_configured(self) -> bool:
        """True only when the provider can actually make a call."""

    @abc.abstractmethod
    def configuration_error(self) -> Optional[str]:
        """Human-readable reason the provider cannot be used, or None."""

    @abc.abstractmethod
    async def generate(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        json_mode: bool = False,
        temperature: float = 0.1,
        max_output_tokens: int = 8192,
    ) -> AIResponse:
        ...

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        tools: Optional[list[dict[str, Any]]] = None,
        temperature: float = 0.2,
        max_output_tokens: int = 2048,
    ) -> ChatResult:
        return ChatResult(
            ok=False,
            error=f"The {self.name} provider does not support conversational tool use.",
            provider=self.name,
            model=self.model,
        )


class UnconfiguredProvider(AIProvider):
    """Stand-in used when no AI provider is configured.

    It never raises and never fabricates content. Callers receive ok=False with
    an explicit reason, which is what makes "missing AI configuration fails
    gracefully" true rather than aspirational.
    """

    name = "none"

    def __init__(self, reason: str = "No AI provider is configured."):
        self.reason = reason

    def is_configured(self) -> bool:
        return False

    def configuration_error(self) -> Optional[str]:
        return self.reason

    async def generate(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        json_mode: bool = False,
        temperature: float = 0.1,
        max_output_tokens: int = 8192,
    ) -> AIResponse:
        return AIResponse(ok=False, error=self.reason, provider=self.name)

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        tools: Optional[list[dict[str, Any]]] = None,
        temperature: float = 0.2,
        max_output_tokens: int = 2048,
    ) -> ChatResult:
        return ChatResult(ok=False, error=self.reason, provider=self.name)
