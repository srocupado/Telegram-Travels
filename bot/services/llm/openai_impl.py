from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import openai
from openai import AsyncOpenAI

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


def _map_finish_reason(value: str | None) -> StopReason:
    if value == "stop":
        return "end_turn"
    if value == "length":
        return "max_tokens"
    if value == "content_filter":
        return "refusal"
    return "other"


def _translate(e: BaseException) -> LLMError:
    if isinstance(e, openai.APITimeoutError):
        return LLMTimeout(str(e))
    if isinstance(e, openai.RateLimitError):
        return LLMRateLimit(str(e))
    if isinstance(e, openai.AuthenticationError):
        return LLMAuth(str(e))
    if isinstance(e, openai.APIConnectionError):
        return LLMConnection(str(e))
    if isinstance(e, openai.APIStatusError):
        if e.status_code >= 500:
            return LLMServerError(str(e), status_code=e.status_code)
        return LLMBadRequest(str(e), status_code=e.status_code)
    return LLMError(str(e))


def _to_openai_messages(system: str, messages: list[dict[str, str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = [{"role": "system", "content": system}]
    out.extend(messages)
    return out


class OpenAILLM:
    provider = "openai"

    def __init__(self, settings: Settings) -> None:
        if settings.openai_api_key is None:
            raise LLMAuth("OPENAI_API_KEY is not set")
        self._client = AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value())
        self.fast_model = settings.openai_fast_model
        self.slow_model = settings.openai_slow_model

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
            response = await client.chat.completions.create(
                model=self._model(speed),
                max_tokens=max_tokens,
                messages=_to_openai_messages(system, messages),
            )
        except Exception as e:
            raise _translate(e) from e
        choice = response.choices[0] if response.choices else None
        if choice is None:
            return CompleteResult(text="", stop_reason="other")
        text = (choice.message.content or "") if choice.message else ""
        return CompleteResult(text=text, stop_reason=_map_finish_reason(choice.finish_reason))

    @asynccontextmanager
    async def stream(
        self,
        *,
        speed: Speed,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int,
    ):
        handle = _OpenAIStreamHandle(
            self._client,
            self._model(speed),
            system,
            messages,
            max_tokens,
        )
        try:
            await handle._open()
            yield handle
        except Exception as e:
            raise _translate(e) from e
        finally:
            await handle._close()


class _OpenAIStreamHandle:
    def __init__(
        self,
        client: AsyncOpenAI,
        model: str,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int,
    ) -> None:
        self._client = client
        self._model = model
        self._system = system
        self._messages = messages
        self._max_tokens = max_tokens
        self._native = None
        self._finish_reason: str | None = None
        self._full_text: list[str] = []

    async def _open(self) -> None:
        self._native = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=self._max_tokens,
            messages=_to_openai_messages(self._system, self._messages),
            stream=True,
        )

    async def _close(self) -> None:
        if self._native is not None:
            await self._native.close()

    @property
    def text_stream(self) -> AsyncIterator[str]:
        return self._iter_text()

    async def _iter_text(self) -> AsyncIterator[str]:
        assert self._native is not None
        try:
            async for chunk in self._native:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                fr = chunk.choices[0].finish_reason
                if fr is not None:
                    self._finish_reason = fr
                content = getattr(delta, "content", None) if delta else None
                if content:
                    self._full_text.append(content)
                    yield content
        except Exception as e:
            raise _translate(e) from e

    async def get_final(self) -> CompleteResult:
        return CompleteResult(
            text="".join(self._full_text),
            stop_reason=_map_finish_reason(self._finish_reason),
        )
