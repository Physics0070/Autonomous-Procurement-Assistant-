"""OpenAI-compatible chat-completions provider.

One implementation serves OpenRouter (the configured provider) and Ollama (a
free local alternative named in the synopsis). Every failure - rate limits,
missing credits, outages, timeouts, malformed bodies - comes back as
`ok=False` with a readable reason, so callers can fall back instead of crash.
"""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional, Sequence

import httpx

from app.core.config import settings
from app.integrations.ai.base import AIProvider, AIResponse, ChatMessage, ChatResult, ToolCall

logger = logging.getLogger(__name__)

_STATUS_REASONS = {
    400: "the model rejected the request",
    401: "the provider rejected the API key",
    402: "the account has insufficient credits",
    403: "the request was refused by the provider",
    404: "the model was not found",
    408: "the provider timed out",
    429: "the provider's rate limit was reached",
}


class OpenAICompatibleProvider(AIProvider):
    supports_tools = True

    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        api_key: str,
        model: str,
        fallback_models: Sequence[str] = (),
        extra_headers: Optional[dict[str, str]] = None,
        timeout: Optional[float] = None,
        http: Optional[httpx.AsyncClient] = None,
        requires_key: bool = True,
        key_setting: str = "API key",
    ):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = (api_key or "").strip()
        self.model = model
        self.fallback_models = [m for m in fallback_models if m and m != model]
        self.extra_headers = extra_headers or {}
        self.timeout = timeout or float(settings.AI_REQUEST_TIMEOUT_SECONDS)
        self._http = http
        self.requires_key = requires_key
        self.key_setting = key_setting

    # -- configuration --------------------------------------------------
    def is_configured(self) -> bool:
        return self.configuration_error() is None

    def configuration_error(self) -> Optional[str]:
        if not self.model:
            return f"No model is configured for the {self.name} provider."
        if self.requires_key and not self.api_key:
            return (
                f"{self.key_setting} is not set. AI extraction, drafting and the assistant "
                "are disabled until it is added to backend/.env and the backend is restarted."
            )
        return None

    # -- transport ------------------------------------------------------
    @asynccontextmanager
    async def _client(self) -> AsyncIterator[httpx.AsyncClient]:
        if self._http is not None:
            yield self._http
        else:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                yield client

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", **self.extra_headers}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def _post(self, payload: dict[str, Any]) -> tuple[Optional[dict[str, Any]], Optional[str], int]:
        """Returns (body, error, status). Never raises for transport problems."""
        try:
            async with self._client() as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=self._headers(),
                    timeout=self.timeout,
                )
        except httpx.TimeoutException:
            return None, f"{self.name} request timed out after {self.timeout:.0f}s", 0
        except httpx.HTTPError as exc:
            return None, f"could not reach {self.name}: {exc.__class__.__name__}", 0

        try:
            body = response.json()
        except ValueError:
            body = None

        if response.status_code >= 400:
            reason = _STATUS_REASONS.get(response.status_code)
            if reason is None:
                reason = (
                    "the provider is unavailable"
                    if response.status_code >= 500
                    else f"the provider returned HTTP {response.status_code}"
                )
            detail = _error_detail(body)
            message = f"{self.name}: {reason}" + (f" ({detail})" if detail else "")
            return None, message, response.status_code

        if not isinstance(body, dict):
            return None, f"{self.name} returned a response that was not JSON", response.status_code
        # OpenRouter can report upstream failures inside a 200 response.
        if body.get("error"):
            return None, f"{self.name}: {_error_detail(body) or 'the model returned an error'}", response.status_code
        if not body.get("choices"):
            return None, f"{self.name} returned no choices", response.status_code
        return body, None, response.status_code

    def _base_payload(self, messages: list[dict[str, Any]], temperature: float, max_tokens: int) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if self.fallback_models:
            # OpenRouter routes to the next model when one is rate-limited or down.
            payload["models"] = [self.model, *self.fallback_models]
        return payload

    # -- generation -----------------------------------------------------
    async def generate(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        json_mode: bool = False,
        temperature: float = 0.1,
        max_output_tokens: int = 8192,
    ) -> AIResponse:
        error = self.configuration_error()
        if error:
            return AIResponse(ok=False, error=error, provider=self.name, model=self.model)

        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = self._base_payload(messages, temperature, max_output_tokens)
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        body, failure, status = await self._post(payload)
        if failure and json_mode and status == 400:
            # Some free models don't accept response_format; the caller parses
            # JSON defensively anyway, so retry without it.
            payload.pop("response_format", None)
            body, failure, status = await self._post(payload)
        if failure:
            logger.warning("LLM call failed: %s", failure)
            return AIResponse(ok=False, error=failure, provider=self.name, model=self.model)

        message = (body["choices"][0] or {}).get("message") or {}
        text = (message.get("content") or "").strip()
        used_model = body.get("model") or self.model
        if not text:
            return AIResponse(
                ok=False, error=f"{self.name} returned an empty answer", provider=self.name, model=used_model
            )
        return AIResponse(
            text=text, ok=True, provider=self.name, model=used_model, meta={"usage": body.get("usage") or {}}
        )

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        tools: Optional[list[dict[str, Any]]] = None,
        temperature: float = 0.2,
        max_output_tokens: int = 2048,
    ) -> ChatResult:
        error = self.configuration_error()
        if error:
            return ChatResult(ok=False, error=error, provider=self.name, model=self.model)

        payload = self._base_payload([_serialise(m) for m in messages], temperature, max_output_tokens)
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        body, failure, _ = await self._post(payload)
        if failure:
            logger.warning("LLM chat failed: %s", failure)
            return ChatResult(ok=False, error=failure, provider=self.name, model=self.model)

        choice = body["choices"][0] or {}
        message = choice.get("message") or {}
        calls = [_parse_tool_call(raw) for raw in message.get("tool_calls") or []]
        content = message.get("content")
        if not calls and not (content or "").strip():
            return ChatResult(
                ok=False, error=f"{self.name} returned an empty answer", provider=self.name,
                model=body.get("model") or self.model,
            )
        return ChatResult(
            ok=True,
            content=content,
            tool_calls=calls,
            provider=self.name,
            model=body.get("model") or self.model,
            finish_reason=choice.get("finish_reason"),
            meta={"usage": body.get("usage") or {}},
        )


def _serialise(message: ChatMessage) -> dict[str, Any]:
    if message.role == "tool":
        return {"role": "tool", "tool_call_id": message.tool_call_id, "content": message.content or ""}
    data: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.tool_calls:
        data["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": call.raw_arguments or json.dumps(call.arguments),
                },
            }
            for call in message.tool_calls
        ]
    return data


def _parse_tool_call(raw: dict[str, Any]) -> ToolCall:
    function = raw.get("function") or {}
    raw_arguments = function.get("arguments") or ""
    try:
        arguments = json.loads(raw_arguments) if raw_arguments else {}
        if not isinstance(arguments, dict):
            arguments = {}
    except (TypeError, ValueError):
        arguments = {}
    return ToolCall(
        id=str(raw.get("id") or ""),
        name=str(function.get("name") or ""),
        arguments=arguments,
        raw_arguments=raw_arguments if isinstance(raw_arguments, str) else json.dumps(raw_arguments),
    )


def _error_detail(body: Any) -> str:
    if not isinstance(body, dict):
        return ""
    error = body.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error.get("code") or "")[:300]
    if isinstance(error, str):
        return error[:300]
    return ""
