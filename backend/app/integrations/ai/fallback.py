"""Vendor fallback: try the next vendor when one fails (free-tier limit spent, rate limit, outage).

A model spec `a|b|c` becomes one provider. A vendor that just failed is moved to the back for
FALLBACK_COOLDOWN_SECONDS, so a dead one is not re-tried (and waited on) at the start of every call.
Tool loops only use vendors that can call tools.
"""
from __future__ import annotations

import time
from typing import Any, Optional

from app.core.config import settings
from app.integrations.ai.base import AIProvider, AIResponse, ChatMessage, ChatResult

# (vendor, model) -> monotonic time until which it is tried last. Shared by every chain in the process.
COOLING: dict[tuple[str, str], float] = {}


def _now() -> float:
    return time.monotonic()


def _key(provider: AIProvider) -> tuple[str, str]:
    return provider.name, provider.model


class FallbackProvider(AIProvider):
    name = "fallback"

    def __init__(self, providers: list[AIProvider]):
        self.providers = providers
        self.model = "|".join(p.model for p in providers)

    # Settings applied to a provider by the factory (council timeout, no hidden fallbacks) reach every vendor.
    @property
    def timeout(self) -> float:
        return self.providers[0].timeout

    @timeout.setter
    def timeout(self, value: float) -> None:
        for p in self.providers:
            p.timeout = value

    @property
    def fallback_models(self) -> list[str]:
        return []

    @fallback_models.setter
    def fallback_models(self, value: list[str]) -> None:
        for p in self.providers:
            p.fallback_models = value

    @property
    def supports_tools(self) -> bool:  # type: ignore[override]
        return any(p.supports_tools for p in self.providers)

    def is_configured(self) -> bool:
        return any(p.is_configured() for p in self.providers)

    def configuration_error(self) -> Optional[str]:
        return None if self.is_configured() else "; ".join(p.configuration_error() or p.name for p in self.providers)

    def _order(self, candidates: list[AIProvider]) -> list[AIProvider]:
        now = _now()
        healthy = [p for p in candidates if COOLING.get(_key(p), 0) <= now]
        return healthy + [p for p in candidates if p not in healthy]

    def _failed(self, provider: AIProvider) -> None:
        COOLING[_key(provider)] = _now() + settings.FALLBACK_COOLDOWN_SECONDS

    async def generate(self, prompt: str, *, system: Optional[str] = None, json_mode: bool = False,
                       temperature: float = 0.1, max_output_tokens: int = 8192) -> AIResponse:
        skipped: list[str] = []
        for provider in self._order([p for p in self.providers if p.is_configured()]):
            result = await provider.generate(prompt, system=system, json_mode=json_mode, temperature=temperature,
                                             max_output_tokens=max_output_tokens)
            if result.ok:
                COOLING.pop(_key(provider), None)
                if skipped:
                    result.meta = {**result.meta, "fallback": skipped}
                return result
            self._failed(provider)
            skipped.append(f"{provider.name}: {result.error}")
        return AIResponse(ok=False, error="; ".join(skipped) or "no vendor is configured", provider=self.name, model=self.model,
                          meta={"fallback": skipped})

    async def chat(self, messages: list[ChatMessage], *, tools: Optional[list[dict[str, Any]]] = None,
                   temperature: float = 0.2, max_output_tokens: int = 2048) -> ChatResult:
        usable = [p for p in self.providers if p.is_configured() and (p.supports_tools or not tools)]
        skipped: list[str] = []
        for provider in self._order(usable):
            result = await provider.chat(messages, tools=tools, temperature=temperature, max_output_tokens=max_output_tokens)
            if result.ok:
                COOLING.pop(_key(provider), None)
                if skipped:
                    result.meta = {**result.meta, "fallback": skipped}
                return result
            self._failed(provider)
            skipped.append(f"{provider.name}: {result.error}")
        return ChatResult(ok=False, error="; ".join(skipped) or "no vendor that can call tools is configured",
                          provider=self.name, model=self.model, meta={"fallback": skipped})
