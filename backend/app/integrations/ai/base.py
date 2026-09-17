"""AI provider abstraction.

No service outside this package may import a vendor SDK. Everything talks to
AIProvider, so adding Ollama (or swapping Gemini) is a new file here and a
config value - nothing else changes.
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


class AIProvider(abc.ABC):
    name: str = "abstract"
    model: str = ""

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
