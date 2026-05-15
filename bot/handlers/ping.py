import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from anthropic import AsyncAnthropic

from bot.config import Settings

logger = logging.getLogger(__name__)
router = Router(name="ping")


@router.message(Command("ping"))
async def cmd_ping(message: Message, claude: AsyncAnthropic, settings: Settings) -> None:
    try:
        response = await claude.messages.create(
            model=settings.haiku_model,
            max_tokens=64,
            messages=[{"role": "user", "content": "Responda apenas: pong"}],
        )
        text = next((b.text for b in response.content if b.type == "text"), "")
        await message.answer(f"✅ Claude {settings.haiku_model}: {text.strip()}")
    except Exception as e:
        logger.exception("ping failed")
        await message.answer(f"❌ Claude API erro: {type(e).__name__}: {e}")
