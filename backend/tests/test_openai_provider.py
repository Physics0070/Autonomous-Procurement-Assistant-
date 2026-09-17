"""OpenRouter / Ollama through one OpenAI-compatible provider."""
import json

import httpx
import pytest

from app.core.config import settings
from app.integrations.ai.base import ChatMessage, UnconfiguredProvider
from app.integrations.ai.factory import build_provider
from app.integrations.ai.openai_compatible import OpenAICompatibleProvider
from app.schemas.common import DocumentType
from app.schemas.document import ProcessedDocument
from app.services.documents.ai_extraction import extract_structured

BASE = "https://openrouter.ai/api/v1"


def _completion(content=None, tool_calls=None, model="google/gemma-4-31b-it:free"):
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "id": "gen-1",
        "model": model,
        "choices": [{"index": 0, "finish_reason": "tool_calls" if tool_calls else "stop",
                     "message": message}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 5},
    }


def _provider(handler, **overrides):
    captured = []

    def record(request):
        request.read()
        captured.append(request)
        return handler(request)

    options = dict(
        name="openrouter", base_url=BASE, api_key="sk-or-test",
        model="google/gemma-4-31b-it:free",
        fallback_models=["nvidia/nemotron-3-super-120b-a12b:free"],
        extra_headers={"HTTP-Referer": "http://localhost:5173", "X-Title": "Procurement Assistant"},
        http=httpx.AsyncClient(transport=httpx.MockTransport(record)),
        key_setting="OPENROUTER_API_KEY",
    )
    options.update(overrides)
    return OpenAICompatibleProvider(**options), captured


async def test_generate_sends_an_openrouter_request_with_fallbacks():
    provider, captured = _provider(lambda r: httpx.Response(200, json=_completion('{"ok": true}')))
    response = await provider.generate("Extract this", system="Be exact", json_mode=True)

    assert response.ok is True
    assert response.text == '{"ok": true}'
    request = captured[0]
    assert str(request.url) == f"{BASE}/chat/completions"
    assert request.headers["Authorization"] == "Bearer sk-or-test"
    assert request.headers["HTTP-Referer"] == "http://localhost:5173"
    assert request.headers["X-Title"] == "Procurement Assistant"
    body = json.loads(request.content)
    assert body["model"] == "google/gemma-4-31b-it:free"
    assert body["models"] == ["google/gemma-4-31b-it:free", "nvidia/nemotron-3-super-120b-a12b:free"]
    assert body["response_format"] == {"type": "json_object"}
    assert [m["role"] for m in body["messages"]] == ["system", "user"]


async def test_the_model_that_actually_answered_is_reported():
    provider, _ = _provider(lambda r: httpx.Response(
        200, json=_completion("hi", model="nvidia/nemotron-3-super-120b-a12b:free")))
    response = await provider.generate("hello")
    assert response.model == "nvidia/nemotron-3-super-120b-a12b:free"


async def test_chat_parses_tool_calls():
    tool_calls = [{"id": "call_9", "type": "function",
                   "function": {"name": "get_comparison", "arguments": '{"request_id": "abc"}'}}]
    provider, captured = _provider(lambda r: httpx.Response(200, json=_completion(None, tool_calls)))
    tools = [{"type": "function", "function": {"name": "get_comparison", "description": "x",
                                                "parameters": {"type": "object", "properties": {}}}}]
    result = await provider.chat([ChatMessage(role="user", content="compare")], tools=tools)

    assert result.ok is True
    assert result.tool_calls[0].id == "call_9"
    assert result.tool_calls[0].name == "get_comparison"
    assert result.tool_calls[0].arguments == {"request_id": "abc"}
    body = json.loads(captured[0].content)
    assert body["tools"] == tools
    assert body["tool_choice"] == "auto"


async def test_chat_serialises_tool_results_back_to_the_model():
    provider, captured = _provider(lambda r: httpx.Response(200, json=_completion("done")))
    from app.integrations.ai.base import ToolCall

    history = [
        ChatMessage(role="user", content="compare"),
        ChatMessage(role="assistant", tool_calls=[ToolCall(id="call_9", name="get_comparison",
                                                           arguments={"request_id": "abc"})]),
        ChatMessage(role="tool", tool_call_id="call_9", name="get_comparison", content='{"rank": 1}'),
    ]
    await provider.chat(history)
    messages = json.loads(captured[0].content)["messages"]
    assert messages[1]["tool_calls"][0]["function"]["arguments"] == '{"request_id": "abc"}'
    assert messages[2] == {"role": "tool", "tool_call_id": "call_9", "content": '{"rank": 1}'}


async def test_malformed_tool_arguments_do_not_crash():
    tool_calls = [{"id": "c", "type": "function", "function": {"name": "x", "arguments": "{not json"}}]
    provider, _ = _provider(lambda r: httpx.Response(200, json=_completion(None, tool_calls)))
    result = await provider.chat([ChatMessage(role="user", content="go")], tools=[])
    assert result.ok is True
    assert result.tool_calls[0].arguments == {}
    assert result.tool_calls[0].raw_arguments == "{not json"


@pytest.mark.parametrize("status,phrase", [
    (429, "rate limit"), (401, "rejected the API key"), (402, "credits"), (503, "unavailable"),
])
async def test_http_failures_become_explained_failures(status, phrase):
    provider, _ = _provider(lambda r: httpx.Response(status, json={"error": {"message": "nope"}}))
    response = await provider.generate("hello")
    assert response.ok is False
    assert phrase in response.error


async def test_an_error_inside_a_200_response_is_a_failure():
    provider, _ = _provider(lambda r: httpx.Response(
        200, json={"error": {"code": 429, "message": "Rate limit exceeded: free-models-per-day"}}))
    response = await provider.generate("hello")
    assert response.ok is False
    assert "free-models-per-day" in response.error


async def test_json_mode_is_dropped_when_a_model_rejects_it():
    def handler(request):
        body = json.loads(request.content)
        if "response_format" in body:
            return httpx.Response(400, json={"error": {"message": "response_format not supported"}})
        return httpx.Response(200, json=_completion('{"ok": true}'))

    provider, captured = _provider(handler)
    response = await provider.generate("extract", json_mode=True)
    assert response.ok is True
    assert len(captured) == 2


async def test_timeouts_are_failures_not_exceptions():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    provider, _ = _provider(handler)
    response = await provider.generate("hello")
    assert response.ok is False
    assert "timed out" in response.error


async def test_an_empty_answer_is_a_failure():
    provider, _ = _provider(lambda r: httpx.Response(200, json=_completion("")))
    response = await provider.generate("hello")
    assert response.ok is False


def test_factory_without_an_openrouter_key_explains_what_to_set(monkeypatch):
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")
    provider = build_provider("openrouter")
    assert isinstance(provider, UnconfiguredProvider)
    assert "OPENROUTER_API_KEY" in provider.configuration_error()


def test_factory_with_a_key_builds_the_openrouter_provider(monkeypatch):
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "sk-or-test")
    provider = build_provider("openrouter")
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.model == settings.OPENROUTER_MODEL
    assert provider.supports_tools is True


def test_factory_ollama_needs_no_key():
    provider = build_provider("ollama")
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.is_configured() is True


def test_factory_rejects_unknown_providers():
    provider = build_provider("mystery")
    assert isinstance(provider, UnconfiguredProvider)
    assert "mystery" in provider.configuration_error()


async def test_rate_limited_extraction_falls_back_to_the_heuristic_parser():
    provider, _ = _provider(lambda r: httpx.Response(429, json={"error": {"message": "slow down"}}))
    document = ProcessedDocument(
        document_type=DocumentType.TEXT,
        raw_text="SHREE PLASTICS\nGrand Total 40777.20\nDelivery within 7 days",
    )
    result, error = await extract_structured(document, provider=provider)
    assert result.provider == "heuristic"
    assert result.commercials.total_amount == 40777.20
    assert "rate limit" in error
