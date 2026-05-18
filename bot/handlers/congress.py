from __future__ import annotations

import logging
from datetime import datetime

import httpx
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import User
from bot.services.congress import (
    USER_AGENT,
    CongressScrapeError,
    fetch_week_mps,
    format_week_message,
)
from bot.services.scheduler import BRT, CONGRESS_HOUR

logger = logging.getLogger(__name__)

router = Router(name="congress")


async def _get_or_create_user(session: AsyncSession, message: Message) -> User | None:
    if message.from_user is None:
        return None
    tg_id = message.from_user.id
    user = await session.scalar(select(User).where(User.telegram_id == tg_id))
    if user is None:
        user = User(
            telegram_id=tg_id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
        )
        session.add(user)
        await session.flush()
    return user


@router.message(Command("congresso_on"))
async def cmd_congress_on(message: Message, session: AsyncSession) -> None:
    user = await _get_or_create_user(session, message)
    if user is None:
        return
    user.congress_subscribed = True
    await session.commit()
    await message.answer(
        "🏛️ Inscrito no resumo semanal de MPs. Toda segunda às 07:00 (BRT)."
    )


@router.message(Command("congresso_off"))
async def cmd_congress_off(message: Message, session: AsyncSession) -> None:
    user = await _get_or_create_user(session, message)
    if user is None:
        return
    user.congress_subscribed = False
    await session.commit()
    await message.answer("🏛️ Resumo semanal de MPs cancelado.")


@router.message(Command("congresso_at"))
async def cmd_congress_at(
    message: Message, command: CommandObject, session: AsyncSession
) -> None:
    user = await _get_or_create_user(session, message)
    if user is None:
        return
    arg = (command.args or "").strip()
    if not arg:
        user.congress_hour = None
        await session.commit()
        await message.answer(
            f"⏰ Hora do digest de MPs voltou pro default ({CONGRESS_HOUR:02d}:00 BRT)."
        )
        return
    try:
        h = int(arg)
    except ValueError:
        h = -1
    if not (0 <= h <= 23):
        await message.answer(
            "Uso: /congresso_at H (hora 0-23, ex: /congresso_at 8). "
            "Sem argumento volta pro default."
        )
        return
    user.congress_hour = h
    user.last_congress_digest_at = None
    await session.commit()
    await message.answer(
        f"⏰ Digest de MPs agendado para {h:02d}:00 BRT (segundas). "
        f"Marca de envio da semana zerada."
    )


@router.message(Command("congresso_reset"))
async def cmd_congress_reset(message: Message, session: AsyncSession) -> None:
    user = await _get_or_create_user(session, message)
    if user is None:
        return
    user.last_congress_digest_at = None
    await session.commit()
    await message.answer(
        "✅ Marca de envio da semana zerada. No próximo tick o digest sai "
        "(se for segunda e a hora agendada já passou)."
    )


@router.message(Command("congresso_now"))
async def cmd_congress_now(message: Message) -> None:
    today = datetime.now(BRT).date()
    try:
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            items = await fetch_week_mps(client, today)
    except CongressScrapeError:
        logger.exception("congresso_now scrape failed")
        await message.answer(
            "⚠️ Não consegui acessar a agenda do Congresso agora. "
            "Tenta de novo em alguns minutos."
        )
        return

    text = format_week_message(items, today)
    try:
        await message.answer(text, disable_web_page_preview=True)
    except Exception:
        logger.exception("HTML send failed in /congresso_now")
        await message.answer(text, parse_mode=None, disable_web_page_preview=True)
