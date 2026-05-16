from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import Message
from anthropic import AsyncAnthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from bot.db.models import User, Watch
from bot.services.chat import ChatStore, chat_turn
from bot.services.parser import ParsedWatch

logger = logging.getLogger(__name__)
router = Router(name="watch")


def _params_from_parsed(p: ParsedWatch) -> dict:
    if p.kind == "flight":
        dests = p.destination_iatas or ([p.destination_iata] if p.destination_iata else [])
        flight_params: dict = {
            "origin_iata": p.origin_iata,
            "destination_iatas": dests,
            "adults": p.adults,
            "travel_class": p.travel_class,
        }
        if p.nights and p.window_start and p.window_end:
            flight_params["window_start"] = p.window_start
            flight_params["window_end"] = p.window_end
            flight_params["nights"] = p.nights
        else:
            flight_params["depart_date"] = p.depart_date
            flight_params["return_date"] = p.return_date
        return flight_params
    params: dict = {"location": p.location, "adults": p.adults}
    if p.nights and p.window_start and p.window_end:
        params["window_start"] = p.window_start
        params["window_end"] = p.window_end
        params["nights"] = p.nights
    else:
        params["check_in"] = p.check_in
        params["check_out"] = p.check_out
    return params


@router.message(F.text & ~F.text.startswith("/"))
async def handle_free_text(
    message: Message,
    session: AsyncSession,
    claude: AsyncAnthropic,
    settings: Settings,
    chat_store: ChatStore,
) -> None:
    if message.from_user is None or not message.text:
        return

    try:
        turn = await chat_turn(
            claude, settings, chat_store, message.from_user.id, message.text
        )
    except Exception:
        logger.exception("chat_turn failed")
        await message.answer("Tive um problema. Pode tentar de novo?")
        return

    if turn.watch is not None:
        user = await session.scalar(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        if user is None:
            user = User(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
            )
            session.add(user)
            await session.flush()

        if turn.watch.kind == "unclear":
            await message.answer("Faltou alguma info. Pode descrever de novo?")
            return

        watch = Watch(
            user_id=user.id,
            kind=turn.watch.kind,
            params=_params_from_parsed(turn.watch),
            max_price=turn.watch.max_price_brl,
            currency=turn.watch.currency,
            summary=turn.watch.summary,
            status="active",
        )
        session.add(watch)
        await session.commit()

        teto = f"\nTeto: R$ {turn.watch.max_price_brl:.2f}" if turn.watch.max_price_brl else ""
        await message.answer(
            f"✅ Monitoramento #{watch.id} criado.\n"
            f"{turn.watch.summary}{teto}\n\n"
            f"Vou checar de tempos em tempos. /list pra ver, /pause {watch.id} pra pausar."
        )
        return

    if turn.reply:
        await message.answer(turn.reply)
