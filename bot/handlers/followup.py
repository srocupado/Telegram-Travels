from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.filters.command import CommandObject
from aiogram.types import Message
from anthropic import AsyncAnthropic

from bot.config import Settings
from bot.services.long_form_chat import LongFormStore, stream_followup_to_telegram

logger = logging.getLogger(__name__)
router = Router(name="followup")


@router.message(Command("seguir"))
async def cmd_seguir(
    message: Message,
    command: CommandObject,
    claude: AsyncAnthropic,
    settings: Settings,
    long_form_store: LongFormStore,
) -> None:
    if message.from_user is None:
        return

    if not command.args:
        await message.answer(
            "Uso: /seguir &lt;pergunta&gt;\n"
            "Pergunta de follow-up sobre o último /roteiro ou /compras. "
            "Ex: <i>/seguir qual loja é mais barata?</i>"
        )
        return

    ctx = long_form_store.get(message.from_user.id)
    if ctx is None:
        await message.answer(
            "Não tenho contexto recente. Use /roteiro ou /compras primeiro, "
            "depois /seguir pra perguntar mais sobre a resposta."
        )
        return

    placeholder = await message.answer("💬 Pensando…")
    await stream_followup_to_telegram(
        claude, settings, ctx, command.args, placeholder,
        long_form_store, message.from_user.id,
    )
