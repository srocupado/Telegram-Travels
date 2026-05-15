from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.config import Settings
from bot.services.chat import ChatStore
from bot.services.serpapi_client import SerpAPIClient


class DepsMiddleware(BaseMiddleware):
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
        claude: AsyncAnthropic,
        serpapi: SerpAPIClient,
        chat_store: ChatStore,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings
        self._claude = claude
        self._serpapi = serpapi
        self._chat_store = chat_store

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with self._sessionmaker() as session:
            data["session"] = session
            data["settings"] = self._settings
            data["claude"] = self._claude
            data["serpapi"] = self._serpapi
            data["chat_store"] = self._chat_store
            return await handler(event, data)
