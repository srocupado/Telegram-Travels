import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.config import Settings
from bot.services.llm import LLMClient

logger = logging.getLogger(__name__)
router = Router(name="ping")


@router.message(Command("ping"))
async def cmd_ping(message: Message, llm: LLMClient, settings: Settings) -> None:
    try:
        result = await llm.complete(
            speed="fast",
            system="",
            messages=[{"role": "user", "content": "Responda apenas: pong"}],
            max_tokens=64,
        )
        await message.answer(
            f"✅ {llm.provider} / {llm.fast_model}: {result.text.strip()}"
        )
    except Exception as e:
        logger.exception("ping failed")
        await message.answer(f"❌ {llm.provider} erro: {type(e).__name__}: {e}")
