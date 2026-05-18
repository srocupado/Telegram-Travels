from __future__ import annotations

import logging
import unicodedata

import httpx
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from bot.db.models import User
from bot.services.traffic import (
    USER_AGENT,
    TrafficError,
    fetch_traffic_with_alternative,
    format_traffic_message_dual,
    parse_route_waypoints,
)

logger = logging.getLogger(__name__)

router = Router(name="traffic")

_USAGE = "Uso: /trafego_now casa  (ou)  /trafego_now trabalho"
_MISSING_CONFIG = (
    "⚠️ Trânsito ainda não está configurado. "
    "Veja .env: HOME_COORDS, WORK_COORDS, GOOGLE_MAPS_API_KEY."
)
_FETCH_ERROR = (
    "⚠️ Não consegui calcular o trânsito agora. Tenta de novo em alguns minutos."
)


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


def _normalize(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s.strip().casefold())
        if not unicodedata.combining(c)
    )


@router.message(Command("trafego_on"))
async def cmd_trafego_on(message: Message, session: AsyncSession) -> None:
    user = await _get_or_create_user(session, message)
    if user is None:
        return
    user.traffic_subscribed = True
    await session.commit()
    await message.answer(
        "🚗 Inscrito no resumo diário de trânsito casa→trabalho (seg-sex 07:20 BRT)."
    )


@router.message(Command("trafego_off"))
async def cmd_trafego_off(message: Message, session: AsyncSession) -> None:
    user = await _get_or_create_user(session, message)
    if user is None:
        return
    user.traffic_subscribed = False
    await session.commit()
    await message.answer("🚗 Resumo diário de trânsito cancelado.")


@router.message(Command("trafego_now"))
async def cmd_trafego_now(
    message: Message, command: CommandObject, settings: Settings
) -> None:
    arg = _normalize(command.args or "")
    if arg not in ("casa", "trabalho"):
        await message.answer(_USAGE)
        return

    if not (settings.home_coords and settings.work_coords and settings.google_maps_api_key):
        await message.answer(_MISSING_CONFIG)
        return

    if arg == "trabalho":
        origin = settings.home_coords
        destination = settings.work_coords
        label = "casa → trabalho"
        reverse = False
    else:
        origin = settings.work_coords
        destination = settings.home_coords
        label = "trabalho → casa"
        reverse = True

    api_key = settings.google_maps_api_key.get_secret_value()
    try:
        async with httpx.AsyncClient(
            timeout=20.0,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            waypoints: list[str] = []
            if settings.route_google_maps_url:
                waypoints = await parse_route_waypoints(
                    client, settings.route_google_maps_url
                )
                if reverse:
                    waypoints = list(reversed(waypoints))
            pref, alt = await fetch_traffic_with_alternative(
                client,
                api_key,
                origin,
                destination,
                waypoints,
                maps_url=settings.route_google_maps_url or "",
            )
    except TrafficError:
        logger.exception("/trafego_now fetch failed")
        await message.answer(_FETCH_ERROR)
        return

    if alt is not None:
        logger.info(
            "/trafego_now: 2 rotas (pref=%d min via %s, alt=%d min via %s)",
            pref.duration_minutes, pref.summary or "—",
            alt.duration_minutes, alt.summary or "—",
        )
    text = format_traffic_message_dual(pref, alt, label)
    try:
        await message.answer(text, disable_web_page_preview=True)
    except Exception:
        logger.exception("HTML send failed in /trafego_now")
        await message.answer(text, parse_mode=None, disable_web_page_preview=True)
