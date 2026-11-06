"""Vendor fallback: `a|b|c` in a model spec tries the next vendor when one fails, so a free tier that
runs out, rate-limits or goes down does not take the task with it."""
import pytest

from app.core.config import settings
from app.integrations.ai import factory, fallback
from app.integrations.ai.base import AIResponse, ChatResult, UnconfiguredProvider
from app.integrations.ai.fallback import FallbackProvider
from tests.fakes.llm import ScriptedProvider


def failing(name="down", error="the provider's rate limit was reached", tools=True):
    p = ScriptedProvider(responder=lambda prompt, system: AIResponse(ok=False, error=error, provider=name, model=name))
    p.name = p.model = name
    p.supports_tools = tools
    p.chat_responses = [ChatResult(ok=False, error=error)] * 5
    return p


def working(name="up", text="answer", tools=True):
    p = ScriptedProvider(responder=lambda prompt, system: text, chat_responses=[ChatResult(content=text)] * 5)
    p.name = p.model = name
    p.supports_tools = tools
    return p


@pytest.fixture(autouse=True)
def fresh_cooldowns():
    fallback.COOLING.clear()
    yield
    fallback.COOLING.clear()


async def test_the_next_vendor_answers_when_the_first_fails():
    first, second = failing("groq"), working("nvidia", "from nvidia")
    result = await FallbackProvider([first, second]).generate("q")
    assert result.ok and result.text == "from nvidia"
    assert result.meta["fallback"] == ["groq: the provider's rate limit was reached"]
    assert result.provider == "nvidia"


async def test_a_healthy_first_choice_is_the_only_one_called():
    first, second = working("groq"), working("nvidia")
    result = await FallbackProvider([first, second]).generate("q")
    assert result.ok and not second.calls and "fallback" not in result.meta


async def test_when_every_vendor_fails_the_error_names_each_one():
    result = await FallbackProvider([failing("groq", "limit"), failing("gemini", "overloaded")]).generate("q")
    assert result.ok is False
    assert "groq: limit" in result.error and "gemini: overloaded" in result.error


async def test_tool_loops_skip_vendors_that_cannot_call_tools():
    text_only, capable = working("gemini", tools=False), working("groq")
    chain = FallbackProvider([text_only, capable])
    assert chain.supports_tools is True
    result = await chain.chat([], tools=[{"type": "function"}])
    assert result.ok and not text_only.chat_calls and len(capable.chat_calls) == 1
    assert FallbackProvider([working("gemini", tools=False)]).supports_tools is False


async def test_a_vendor_that_just_failed_is_tried_last_for_a_while(monkeypatch):
    """No repeating a 120 s timeout on every call: a failed vendor cools off, then is retried."""
    clock = [1000.0]
    monkeypatch.setattr(fallback, "_now", lambda: clock[0])
    first, second = failing("groq"), working("nvidia")
    chain = FallbackProvider([first, second])
    await chain.generate("one")
    await chain.generate("two")
    assert len(first.calls) == 1 and len(second.calls) == 2          # groq skipped to the back while cooling
    clock[0] += settings.FALLBACK_COOLDOWN_SECONDS + 1
    await chain.generate("three")
    assert len(first.calls) == 2                                      # cooled off: tried first again


async def test_a_cooling_vendor_is_still_used_when_it_is_the_only_one_left(monkeypatch):
    monkeypatch.setattr(fallback, "_now", lambda: 1000.0)
    only = working("groq")
    fallback.COOLING[("groq", "groq")] = 2000.0
    assert (await FallbackProvider([only]).generate("q")).ok


# ---------------------------------------------------------------- the spec syntax

@pytest.fixture
def keyed(monkeypatch):
    for key in ("GROQ_API_KEY", "GEMINI_API_KEY", "NVIDIA_API_KEY"):
        monkeypatch.setattr(settings, key, "test")
    monkeypatch.setattr(settings, "AI_PROVIDER", "groq")
    monkeypatch.setattr(settings, "COUNCIL_MODELS", "")
    yield
    factory.reset_ai_provider()


def test_a_spec_with_pipes_builds_a_fallback_chain_in_order(keyed, monkeypatch):
    monkeypatch.setattr(settings, "LLM_TASK_MODELS", "extraction=gemini:gemini-3.1-flash-lite|groq:openai/gpt-oss-20b|nvidia:nvidia/nemotron-3.5-bolt-e4b")
    factory.reset_ai_provider()
    chain = factory.get_ai_provider("extraction")
    assert isinstance(chain, FallbackProvider)
    assert [(p.name, p.model) for p in chain.providers] == [
        ("gemini", "gemini-3.1-flash-lite"), ("groq", "openai/gpt-oss-20b"), ("nvidia", "nvidia/nemotron-3.5-bolt-e4b")]


def test_unconfigured_vendors_are_dropped_and_one_survivor_is_returned_plainly(keyed, monkeypatch):
    monkeypatch.setattr(settings, "NVIDIA_API_KEY", "")
    monkeypatch.setattr(settings, "LLM_TASK_MODELS", "hsn=nvidia:nvidia/nemotron-3.5-bolt-e4b|groq:openai/gpt-oss-20b")
    factory.reset_ai_provider()
    provider = factory.get_ai_provider("hsn")
    assert not isinstance(provider, FallbackProvider) and (provider.name, provider.model) == ("groq", "openai/gpt-oss-20b")


def test_a_chain_of_unconfigured_vendors_explains_itself(keyed, monkeypatch):
    for key in ("GEMINI_API_KEY", "NVIDIA_API_KEY"):
        monkeypatch.setattr(settings, key, "")
    monkeypatch.setattr(settings, "LLM_TASK_MODELS", "hsn=nvidia:nvidia/nemotron-3.5-bolt-e4b|gemini:gemini-3.1-flash-lite")
    factory.reset_ai_provider()
    provider = factory.get_ai_provider("hsn")
    assert isinstance(provider, UnconfiguredProvider) and "API_KEY" in provider.configuration_error()


def test_council_seats_can_have_fallbacks_too(keyed, monkeypatch):
    monkeypatch.setattr(settings, "LLM_TASK_MODELS", "critic=council")
    monkeypatch.setattr(settings, "COUNCIL_MODELS", "groq:openai/gpt-oss-20b|nvidia:nvidia/nemotron-3.5-bolt-e4b,gemini:gemini-3.1-flash-lite")
    monkeypatch.setattr(settings, "COUNCIL_MONITOR_MODEL", "groq:qwen/qwen3.8-27b|nvidia:nvidia/nemotron-3.5-bolt-e4b")
    factory.reset_ai_provider()
    council = factory.get_ai_provider("critic")
    assert isinstance(council.members[0], FallbackProvider) and council.members[1].name == "gemini"
    assert isinstance(council.monitor, FallbackProvider)
    assert council.members[0].timeout == float(settings.COUNCIL_MEMBER_TIMEOUT_SECONDS)
