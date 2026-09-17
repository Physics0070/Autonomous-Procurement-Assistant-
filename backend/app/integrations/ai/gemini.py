from __future__ import annotations

import asyncio
import logging
from typing import Optional

from app.core.config import settings
from app.integrations.ai.base import AIProvider, AIResponse

logger = logging.getLogger(__name__)


class GeminiProvider(AIProvider):
    name = "gemini"

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = (api_key if api_key is not None else settings.GEMINI_API_KEY or "").strip()
        self.model = model or settings.GEMINI_MODEL
        self._sdk_error: Optional[str] = None

    def is_configured(self) -> bool:
        return bool(self.api_key) and self._import_sdk() is not None

    def configuration_error(self) -> Optional[str]:
        if not self.api_key:
            return (
                "GEMINI_API_KEY is not set. Structured AI extraction and AI explanations "
                "are disabled until a key is configured in backend/.env."
            )
        if self._import_sdk() is None:
            return f"google-generativeai SDK unavailable: {self._sdk_error}"
        return None

    def _import_sdk(self):
        try:
            import google.generativeai as genai

            return genai
        except Exception as exc:  # pragma: no cover - import guard
            self._sdk_error = str(exc)
            return None

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

        genai = self._import_sdk()

        def _call() -> AIResponse:
            try:
                genai.configure(api_key=self.api_key)
                generation_config: dict = {
                    "temperature": temperature,
                    "max_output_tokens": max_output_tokens,
                }
                if json_mode:
                    generation_config["response_mime_type"] = "application/json"
                model = genai.GenerativeModel(
                    model_name=self.model,
                    generation_config=generation_config,
                    system_instruction=system,
                )
                response = model.generate_content(prompt)
                text = getattr(response, "text", "") or ""
                if not text:
                    # Blocked or empty completions must surface, not pass silently.
                    feedback = getattr(response, "prompt_feedback", None)
                    return AIResponse(
                        ok=False,
                        error=f"Empty response from Gemini (feedback={feedback})",
                        provider=self.name,
                        model=self.model,
                    )
                usage = getattr(response, "usage_metadata", None)
                meta = {}
                if usage is not None:
                    meta = {
                        "prompt_tokens": getattr(usage, "prompt_token_count", None),
                        "output_tokens": getattr(usage, "candidates_token_count", None),
                    }
                return AIResponse(
                    text=text, ok=True, provider=self.name, model=self.model, meta=meta
                )
            except Exception as exc:
                return AIResponse(ok=False, error=str(exc), provider=self.name, model=self.model)

        try:
            return await asyncio.wait_for(
                asyncio.to_thread(_call), timeout=settings.AI_REQUEST_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            return AIResponse(
                ok=False,
                error=f"Gemini request timed out after {settings.AI_REQUEST_TIMEOUT_SECONDS}s",
                provider=self.name,
                model=self.model,
            )
