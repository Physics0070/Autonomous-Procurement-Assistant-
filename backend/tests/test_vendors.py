"""Several AI vendors at once: `vendor:model` picks the vendor per task and per council seat,
each with its own key and endpoint, so a council can mix Grok, Qwen and Gemini."""
import pytest

from app.core.config import settings
from app.integrations.ai import factory
from app.integrations.ai.base import UnconfiguredProvider
from app.integrations.ai.council import CouncilProvider


@pytest.fixture
def vendors(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "g-test")
    monkeypatch.setattr(settings, "GEMINI_MODEL", "gemini-default")
    monkeypatch.setattr(settings, "GROK_API_KEY", "x-test")
    monkeypatch.setattr(settings, "QWEN_API_KEY", "q-test")
    monkeypatch.setattr(settings, "LLM_TASK_MODELS", "negotiation=qwen:qwen-plus, critic=council")
    monkeypatch.setattr(settings, "COUNCIL_MODELS", "grok:grok-4-fast, qwen:qwen-plus, gemini:gemini-2.5-flash")
    monkeypatch.setattr(settings, "COUNCIL_MONITOR_MODEL", "gemini:gemini-2.5-pro")
    factory.reset_ai_provider()
    yield
    factory.reset_ai_provider()


def test_a_council_can_mix_vendors(vendors):
    council = factory.get_ai_provider("critic")
    assert isinstance(council, CouncilProvider)
    assert [(m.name, m.model) for m in council.members] == [
        ("grok", "grok-4-fast"), ("qwen", "qwen-plus"), ("gemini", "gemini-2.5-flash")]
    assert [m.base_url for m in council.members] == [
        settings.GROK_BASE_URL, settings.QWEN_BASE_URL, settings.GEMINI_BASE_URL.rstrip("/")]
    assert [m.api_key for m in council.members] == ["x-test", "q-test", "g-test"]
    assert (council.monitor.name, council.monitor.model) == ("gemini", "gemini-2.5-pro")


def test_a_task_can_use_another_vendor_than_the_default(vendors):
    assert (factory.get_ai_provider("negotiation").name, factory.get_ai_provider("negotiation").model) == (
        "qwen", "qwen-plus")
    default = factory.get_ai_provider("extraction")
    assert (default.name, default.model) == ("gemini", "gemini-default")


def test_gemini_speaks_the_openai_format_so_it_can_use_tools(vendors):
    assert factory.get_ai_provider().supports_tools


def test_a_missing_vendor_key_is_named(vendors, monkeypatch):
    monkeypatch.setattr(settings, "GROK_API_KEY", "")
    factory.reset_ai_provider()
    council = factory.get_ai_provider("critic")
    assert isinstance(council, UnconfiguredProvider)
    assert "GROK_API_KEY" in council.configuration_error()
    assert factory.get_ai_provider("negotiation").is_configured()  # other vendors are unaffected


def test_unprefixed_models_keep_using_the_default_vendor(monkeypatch):
    """OpenRouter IDs contain ':' too ("vendor/model:free") - that is not a vendor prefix."""
    monkeypatch.setattr(settings, "AI_PROVIDER", "openrouter")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(settings, "LLM_TASK_MODELS", "hsn=nex-agi/nex-n2.5-mini:free")
    factory.reset_ai_provider()
    try:
        provider = factory.get_ai_provider("hsn")
        assert (provider.name, provider.model) == ("openrouter", "nex-agi/nex-n2.5-mini:free")
    finally:
        factory.reset_ai_provider()


def test_ollama_models_may_contain_colons(monkeypatch):
    monkeypatch.setattr(settings, "LLM_TASK_MODELS", "hsn=ollama:qwen2.5:7b")
    factory.reset_ai_provider()
    try:
        provider = factory.get_ai_provider("hsn")
        assert (provider.name, provider.model) == ("ollama", "qwen2.5:7b")
    finally:
        factory.reset_ai_provider()
