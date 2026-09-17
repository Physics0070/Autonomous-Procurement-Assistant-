from __future__ import annotations

import logging
from typing import Optional

from app.core.config import settings
from app.integrations.ai.base import AIProvider, UnconfiguredProvider
from app.integrations.ai.gemini import GeminiProvider

logger = logging.getLogger(__name__)

_provider: Optional[AIProvider] = None


def build_provider(name: Optional[str] = None) -> AIProvider:
    name = (name or settings.AI_PROVIDER or "none").lower()
    if name == "gemini":
        provider = GeminiProvider()
        if provider.is_configured():
            return provider
        return UnconfiguredProvider(provider.configuration_error() or "Gemini is not configured.")
    if name == "none":
        return UnconfiguredProvider("AI_PROVIDER is set to 'none'; AI features are disabled.")
    # An unknown provider name is a configuration mistake, not a crash.
    return UnconfiguredProvider(
        f"Unknown AI_PROVIDER '{name}'. Supported values: gemini, none."
    )


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
