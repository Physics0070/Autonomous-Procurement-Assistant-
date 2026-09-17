from __future__ import annotations

import logging
from typing import Optional

from app.core.config import settings
from app.integrations.ai.base import AIProvider, UnconfiguredProvider
from app.integrations.ai.gemini import GeminiProvider
from app.integrations.ai.openai_compatible import OpenAICompatibleProvider

logger = logging.getLogger(__name__)

SUPPORTED_PROVIDERS = ("openrouter", "ollama", "gemini", "none")

_provider: Optional[AIProvider] = None


def build_provider(name: Optional[str] = None) -> AIProvider:
    name = (name or settings.AI_PROVIDER or "none").strip().lower()

    if name == "openrouter":
        provider: AIProvider = OpenAICompatibleProvider(
            name="openrouter",
            base_url=settings.OPENROUTER_BASE_URL,
            api_key=settings.OPENROUTER_API_KEY,
            model=settings.OPENROUTER_MODEL,
            fallback_models=settings.openrouter_fallback_models,
            # OpenRouter uses these to attribute traffic to the app.
            extra_headers={"HTTP-Referer": settings.OPENROUTER_APP_URL, "X-Title": settings.APP_NAME},
            key_setting="OPENROUTER_API_KEY",
        )
    elif name == "ollama":
        provider = OpenAICompatibleProvider(
            name="ollama",
            base_url=settings.OLLAMA_BASE_URL,
            api_key="",
            model=settings.OLLAMA_MODEL,
            requires_key=False,
        )
    elif name == "gemini":
        provider = GeminiProvider()
    elif name == "none":
        return UnconfiguredProvider("AI_PROVIDER is set to 'none'; AI features are disabled.")
    else:
        # An unknown provider name is a configuration mistake, not a crash.
        return UnconfiguredProvider(
            f"Unknown AI_PROVIDER '{name}'. Supported values: {', '.join(SUPPORTED_PROVIDERS)}."
        )

    if provider.is_configured():
        return provider
    return UnconfiguredProvider(provider.configuration_error() or f"{name} is not configured.")


def get_ai_provider() -> AIProvider:
    global _provider
    if _provider is None:
        _provider = build_provider()
        if _provider.is_configured():
            logger.info("AI provider ready: %s (%s)", _provider.name, _provider.model)
        else:
            logger.warning("AI provider unavailable: %s", _provider.configuration_error())
    return _provider


def reset_ai_provider() -> None:
    """Used by tests and after configuration changes."""
    global _provider
    _provider = None
