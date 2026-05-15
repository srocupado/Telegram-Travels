from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import Message
from anthropic import AsyncAnthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from bot.db.models import User, Watch
from bot.services.parser import ParsedWatch, parse_watch

logger = logging.getLogger(__name__)
router = Router(name="watch")


def _params_from_parsed(p: ParsedWatch) -> dict:
    if p.kind == "flight":
        return {
            "origin_iata": p.origin_iata,
            "destination_iata": p.destination_iata,
            "depart_date": p.depart_date,
            "return_date": p.return_date,
            "adults": p.adults,
        }
    return {
        "location": p.location,
        "check_in": p.check_in,
        "check_out": p.check_out,
        "adults": p.adults,
    }


@router.message(F.text & ~F.text.startswith("/"))
async def handle_free_text(
    message: Message,
    session: AsyncSession,
    claude: AsyncAnthropic,
    settings: Settings,
) -> None:
    if message.from_user is None or not message.text:
        return

    await message.answer("🤔 Entendendo seu pedido…")
    try:
        parsed = await parse_watch(claude, settings, message.text)
    except Exception:
        logger.exception("parse failed")
        await message.answer("Tive um problema interpretando. Pode reformular?")
        return

    if parsed.kind == "unclear":
        await message.answer(parsed.clarification_needed or "Pode dar mais detalhes?")
        return

    user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
    if user is None:
        user = User(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
        )
        session.add(user)
        await session.flush()

    watch = Watch(
        user_id=user.id,
        kind=parsed.kind,
        params=_params_from_parsed(parsed),
        max_price=parsed.max_price_brl,
        currency=parsed.currency,
        summary=parsed.summary,
        status="active",
    )
    session.add(watch)
    await session.commit()

    teto = f"\nTeto: R$ {parsed.max_price_brl:.2f}" if parsed.max_price_brl else ""
    await message.answer(
        f"✅ Monitoramento #{watch.id} criado.\n"
        f"{parsed.summary}{teto}\n\n"
        f"Vou checar de tempos em tempos e te aviso quando o preço cair. "
        f"Use /list pra ver, /pause {watch.id} pra pausar."
    )
