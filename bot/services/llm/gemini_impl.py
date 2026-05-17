from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from bot.config import Settings
from bot.services.llm.base import (
    CompleteResult,
    LLMAuth,
    LLMBadRequest,
    LLMConnection,
    LLMError,
    LLMRateLimit,
    LLMRefusal,
    LLMServerError,
    LLMTimeout,
    Speed,
    StopReason,
)

logger = logging.getLogger(__name__)


def _map_finish_reason(value: Any) -> StopReason:
    if value is None:
        return "other"
    name = getattr(value, "name", str(value)).upper()
    if name == "STOP":
        return "end_turn"
    if name == "MAX_TOKENS":
        return "max_tokens"
    if name in ("SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"):
        return "refusal"
    return "other"


def _translate(e: BaseException) -> LLMError:
    name = type(e).__name__
    msg = str(e)
    if name in ("DeadlineExceeded", "TimeoutError"):
        return LLMTimeout(msg)
    if name in ("ResourceExhausted", "TooManyRequests"):
        return LLMRateLimit(msg)
    if name in ("Unauthenticated", "PermissionDenied"):
        return LLMAuth(msg)
    if name in ("ServiceUnavailable", "InternalServerError"):
        return LLMServerError(msg, status_code=503)
    if name in ("InvalidArgument", "FailedPrecondition", "NotFound"):
        return LLMBadRequest(msg, status_code=400)
    if name == "ConnectionError":
        return LLMConnection(msg)
    code = getattr(e, "code", None) or getattr(e, "status_code", None)
    if isinstance(code, int):
        if code >= 500:
            return LLMServerError(msg, status_code=code)
        if code in (401, 403):
            return LLMAuth(msg)
        if code == 429:
            return LLMRateLimit(msg)
        if code == 408:
            return LLMTimeout(msg)
        if 400 <= code < 500:
            return LLMBadRequest(msg, status_code=code)
    return LLMError(msg)


def _to_gemini_contents(messages: list[dict[str, str]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        role = "model" if m.get("role") == "assistant" else "user"
        out.append({"role": role, "parts": [{"text": m.get("content", "")}]})
    return out


class GeminiLLM:
    provider = "gemini"

    def __init__(self, settings: Settings) -> None:
        if settings.gemini_api_key is None:
            raise LLMAuth("GEMINI_API_KEY is not set")
        from google import genai

        self._client = genai.Client(api_key=settings.gemini_api_key.get_secret_value())
        self.fast_model = settings.gemini_fast_model
        self.slow_model = settings.gemini_slow_model

    def _model(self, speed: Speed) -> str:
        return self.fast_model if speed == "fast" else self.slow_model

    async def complete(
        self,
        *,
        speed: Speed,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        timeout: float | None = None,
        max_retries: int | None = None,
    ) -> CompleteResult:
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
        )
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model(speed),
                contents=_to_gemini_contents(messages),
                config=config,
            )
        except Exception as e:
            raise _translate(e) from e
        text = getattr(response, "text", "") or ""
        finish = None
        candidates = getattr(response, "candidates", None) or []
        if candidates:
            finish = getattr(candidates[0], "finish_reason", None)
        return CompleteResult(text=text, stop_reason=_map_finish_reason(finish))

    @asynccontextmanager
    async def stream(
        self,
        *,
        speed: Speed,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int,
    ):
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
        )
        handle = _GeminiStreamHandle(
            self._client,
            self._model(speed),
            _to_gemini_contents(messages),
            config,
        )
        try:
            await handle._open()
            yield handle
        except Exception as e:
            raise _translate(e) from e


class _GeminiStreamHandle:
    def __init__(self, client, model: str, contents: list[dict[str, Any]], config) -> None:
        self._client = client
        self._model = model
        self._contents = contents
        self._config = config
        self._native = None
        self._finish_reason: Any = None
        self._full_text: list[str] = []

    async def _open(self) -> None:
        self._native = await self._client.aio.models.generate_content_stream(
            model=self._model,
            contents=self._contents,
            config=self._config,
        )

    @property
    def text_stream(self) -> AsyncIterator[str]:
        return self._iter_text()

    async def _iter_text(self) -> AsyncIterator[str]:
        assert self._native is not None
        try:
            async for chunk in self._native:
                piece = getattr(chunk, "text", None)
                candidates = getattr(chunk, "candidates", None) or []
                if candidates:
                    fr = getattr(candidates[0], "finish_reason", None)
                    if fr is not None:
                        self._finish_reason = fr
                if piece:
                    self._full_text.append(piece)
                    yield piece
        except Exception as e:
            raise _translate(e) from e

    async def get_final(self) -> CompleteResult:
        return CompleteResult(
            text="".join(self._full_text),
            stop_reason=_map_finish_reason(self._finish_reason),
        )
