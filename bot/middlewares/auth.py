from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject, Update
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.db.models import User

logger = logging.getLogger(__name__)


def _extract_message(event: TelegramObject) -> Message | None:
    if isinstance(event, Message):
        return event
    if isinstance(event, Update):
        return event.message
    return None


class AuthMiddleware(BaseMiddleware):
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        password: str,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._password = password.strip()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        message = _extract_message(event)
        if message is None or message.from_user is None:
            return await handler(event, data)

        async with self._sessionmaker() as session:
            user = await session.scalar(
                select(User).where(User.telegram_id == message.from_user.id)
            )
            if user is not None and user.is_authorized:
                return await handler(event, data)

            text = (message.text or "").strip()

            if text == self._password:
                if user is None:
                    user = User(
                        telegram_id=message.from_user.id,
                        username=message.from_user.username,
                        first_name=message.from_user.first_name,
                        is_authorized=True,
                    )
                    session.add(user)
                else:
                    user.is_authorized = True
                await session.commit()
                logger.info("user %d authorized", message.from_user.id)
                await message.answer(
                    "✅ Acesso liberado! Sou seu agente de viagens. Mande /help pra ver o que sei fazer."
                )
                return None

            if not text:
                await message.answer("🔒 Esse bot é privado. Mande a senha:")
                return None

            await message.answer("🔒 Esse bot é privado. Mande a senha:")
            return None
