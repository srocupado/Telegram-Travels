from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import anthropic
from anthropic import AsyncAnthropic

from bot.config import Settings
from bot.services.llm.base import (
    CompleteResult,
    LLMAuth,
    LLMBadRequest,
    LLMConnection,
    LLMError,
    LLMRateLimit,
    LLMServerError,
    LLMTimeout,
    Speed,
    StopReason,
)

logger = logging.getLogger(__name__)


def _map_stop_reason(value: str | None) -> StopReason:
    if value == "end_turn":
        return "end_turn"
    if value == "max_tokens":
        return "max_tokens"
    if value == "refusal":
        return "refusal"
    return "other"


def _translate(e: BaseException) -> LLMError:
    if isinstance(e, anthropic.APITimeoutError):
        return LLMTimeout(str(e))
    if isinstance(e, anthropic.RateLimitError):
        return LLMRateLimit(str(e))
    if isinstance(e, anthropic.AuthenticationError):
        return LLMAuth(str(e))
    if isinstance(e, anthropic.APIConnectionError):
        return LLMConnection(str(e))
    if isinstance(e, anthropic.APIStatusError):
        if e.status_code >= 500:
            return LLMServerError(str(e), status_code=e.status_code)
        return LLMBadRequest(str(e), status_code=e.status_code)
    return LLMError(str(e))


class AnthropicLLM:
    provider = "anthropic"

    def __init__(self, settings: Settings) -> None:
        self._client = AsyncAnthropic(
            api_key=settings.anthropic_api_key.get_secret_value()
        )
        self.fast_model = settings.haiku_model
        self.slow_model = settings.sonnet_model

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
        client = self._client
        if timeout is not None or max_retries is not None:
            opts: dict = {}
            if timeout is not None:
                opts["timeout"] = timeout
            if max_retries is not None:
                opts["max_retries"] = max_retries
            client = client.with_options(**opts)
        try:
            response = await client.messages.create(
                model=self._model(speed),
                max_tokens=max_tokens,
                system=system,
                messages=messages,
            )
        except Exception as e:
            raise _translate(e) from e
        text = next((b.text for b in response.content if b.type == "text"), "")
        return CompleteResult(text=text, stop_reason=_map_stop_reason(response.stop_reason))

    @asynccontextmanager
    async def stream(
        self,
        *,
        speed: Speed,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int,
    ):
        try:
            async with self._client.messages.stream(
                model=self._model(speed),
                max_tokens=max_tokens,
                system=system,
                messages=messages,
            ) as native_stream:
                yield _AnthropicStreamHandle(native_stream)
        except Exception as e:
            raise _translate(e) from e

    async def aclose(self) -> None:
        await self._client.close()


class _AnthropicStreamHandle:
    def __init__(self, native_stream) -> None:
        self._native = native_stream

    @property
    def text_stream(self) -> AsyncIterator[str]:
        return self._native.text_stream

    async def get_final(self) -> CompleteResult:
        msg = await self._native.get_final_message()
        text = next((b.text for b in msg.content if b.type == "text"), "")
        return CompleteResult(text=text, stop_reason=_map_stop_reason(msg.stop_reason))
