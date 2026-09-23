from __future__ import annotations

import logging
from typing import Optional

from app.core.config import settings
from app.integrations.ai.base import AIProvider, UnconfiguredProvider
from app.integrations.ai.council import CouncilProvider
from app.integrations.ai.openai_compatible import OpenAICompatibleProvider

logger = logging.getLogger(__name__)

# Direct vendors that need nothing beyond a key, an endpoint and a model (settings <VENDOR>_*).
KEYED_VENDORS = ("gemini", "grok", "qwen")
SUPPORTED_PROVIDERS = (*KEYED_VENDORS, "ollama", "openrouter", "none")

_providers: dict[Optional[str], AIProvider] = {}


def build_provider(name: Optional[str] = None, *, model: Optional[str] = None) -> AIProvider:
    """One provider. `model` overrides the configured default (per-task routing, council members)."""
    name = (name or settings.AI_PROVIDER or "none").strip().lower()

    if name in KEYED_VENDORS:
        prefix = name.upper()
        provider: AIProvider = OpenAICompatibleProvider(
            name=name,
            base_url=getattr(settings, f"{prefix}_BASE_URL"),
            api_key=getattr(settings, f"{prefix}_API_KEY"),
            model=model or getattr(settings, f"{prefix}_MODEL"),
            key_setting=f"{prefix}_API_KEY",
        )
    elif name == "openrouter":
        provider = OpenAICompatibleProvider(
            name="openrouter",
            base_url=settings.OPENROUTER_BASE_URL,
            api_key=settings.OPENROUTER_API_KEY,
            model=model or settings.OPENROUTER_MODEL,
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
            model=model or settings.OLLAMA_MODEL,
            requires_key=False,
        )
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


def build_model(spec: Optional[str]) -> AIProvider:
    """'qwen:qwen-plus' -> that vendor; anything else is a model of the default vendor.
    Only a known vendor counts as a prefix: OpenRouter and Ollama IDs contain ':' too."""
    vendor, _, model = (spec or "").partition(":")
    if model and vendor.lower() in SUPPORTED_PROVIDERS:
        return build_provider(vendor, model=model)
    return build_provider(model=spec or None)


def _split(value: str) -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def task_models() -> dict[str, str]:
    """LLM_TASK_MODELS='negotiation=vendor/model, critic=council' -> {task: model or 'council'}."""
    return dict(pair.split("=", 1) for pair in (p.replace(" ", "") for p in _split(settings.LLM_TASK_MODELS)) if "=" in pair)


def _build_for_task(task: Optional[str]) -> AIProvider:
    spec = task_models().get(task) if task else None
    if spec != "council":
        return build_model(spec)
    members = [build_model(m) for m in _split(settings.COUNCIL_MODELS)]
    monitor = build_model(settings.COUNCIL_MONITOR_MODEL)
    for participant in (*members, monitor):
        # No silent fallbacks inside a council: a member that quietly becomes another
        # vendor's model destroys the diversity the council exists for, and its errors
        # would be reported against the wrong model. Failures are visible instead.
        participant.fallback_models = []
    unusable = next((p for p in (*members, monitor) if not p.is_configured()), None)
    if unusable is not None:
        return UnconfiguredProvider(unusable.configuration_error() or "The council's models are not configured.")
    if len(members) < 2:
        return UnconfiguredProvider("COUNCIL_MODELS needs at least two models for task '%s'." % task)
    return CouncilProvider(members, monitor)


def get_ai_provider(task: Optional[str] = None) -> AIProvider:
    """The provider for a task: its own model, a council, or the default when unassigned."""
    if task not in _providers:
        provider = _build_for_task(task)
        _providers[task] = provider
        if provider.is_configured():
            logger.info("AI provider for %s: %s (%s)", task or "default", provider.name, provider.model)
        else:
            logger.warning("AI provider for %s unavailable: %s", task or "default", provider.configuration_error())
    return _providers[task]


def for_task(provider: AIProvider, task: str) -> AIProvider:
    """Route to the task's own model - unless the caller injected a provider (tests, callers
    that deliberately pass one), which is always respected."""
    return get_ai_provider(task) if provider is get_ai_provider() else provider


def reset_ai_provider() -> None:
    """Used by tests and after configuration changes."""
    _providers.clear()
