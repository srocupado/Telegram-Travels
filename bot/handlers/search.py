from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.filters.command import CommandObject
from aiogram.types import Message
from anthropic import AsyncAnthropic

from bot.config import Settings
from bot.services.parser import parse_watch
from bot.services.serpapi_client import (
    SerpAPIClient,
    SerpAPIError,
    extract_best_flight,
    extract_best_hotel,
    format_flight,
    format_hotel,
)

logger = logging.getLogger(__name__)
router = Router(name="search")


@router.message(Command("search"))
async def cmd_search(
    message: Message,
    command: CommandObject,
    claude: AsyncAnthropic,
    serpapi: SerpAPIClient,
    settings: Settings,
) -> None:
    if not command.args:
        await message.answer(
            "Uso: /search &lt;descrição&gt;. Ex: /search GRU EZE 12/07 ida e volta 19/07"
        )
        return

    await message.answer("🔎 Buscando…")
    try:
        parsed = await parse_watch(claude, settings, command.args)
    except Exception:
        logger.exception("parse failed")
        await message.answer("Não consegui interpretar seu pedido. Tente reformular.")
        return

    if parsed.kind == "unclear":
        await message.answer(parsed.clarification_needed or "Preciso de mais detalhes.")
        return

    try:
        if parsed.kind == "flight":
            raw = await serpapi.search_flights(
                origin_iata=parsed.origin_iata or "",
                destination_iata=parsed.destination_iata or "",
                depart_date=parsed.depart_date or "",
                return_date=parsed.return_date,
                adults=parsed.adults,
                currency=parsed.currency,
            )
            best = extract_best_flight(raw)
        else:
            raw = await serpapi.search_hotels(
                location=parsed.location or "",
                check_in=parsed.check_in or "",
                check_out=parsed.check_out or "",
                adults=parsed.adults,
                currency=parsed.currency,
            )
            best = extract_best_hotel(raw)
    except SerpAPIError as e:
        await message.answer(f"❌ Erro na busca: {e}")
        return

    if best is None:
        await message.answer(f"Nenhum preço encontrado para: {parsed.summary}")
        return

    price, payload = best
    header = f"<b>{parsed.summary}</b>"
    body = (
        format_flight(price, payload)
        if parsed.kind == "flight"
        else format_hotel(price, payload)
    )
    await message.answer(f"{header}\n\n{body}", disable_web_page_preview=True)
