from __future__ import annotations

from abc import abstractmethod
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import AsyncIterator, Literal, Protocol, runtime_checkable

Speed = Literal["fast", "slow"]
StopReason = Literal["end_turn", "max_tokens", "refusal", "other"]


@dataclass
class CompleteResult:
    text: str
    stop_reason: StopReason


class StreamHandle(Protocol):
    text_stream: AsyncIterator[str]

    async def get_final(self) -> CompleteResult: ...


@runtime_checkable
class LLMClient(Protocol):
    provider: str
    fast_model: str
    slow_model: str

    @abstractmethod
    async def complete(
        self,
        *,
        speed: Speed,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        timeout: float | None = None,
        max_retries: int | None = None,
    ) -> CompleteResult: ...

    @abstractmethod
    def stream(
        self,
        *,
        speed: Speed,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int,
    ) -> AbstractAsyncContextManager[StreamHandle]: ...

    async def aclose(self) -> None: ...


class LLMError(Exception):
    """Base class for all LLM provider errors."""


class LLMTimeout(LLMError):
    pass


class LLMRateLimit(LLMError):
    pass


class LLMConnection(LLMError):
    pass


class LLMAuth(LLMError):
    pass


class LLMServerError(LLMError):
    def __init__(self, message: str, status_code: int = 500) -> None:
        super().__init__(message)
        self.status_code = status_code


class LLMBadRequest(LLMError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class LLMRefusal(LLMError):
    pass
