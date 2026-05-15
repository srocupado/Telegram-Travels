from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import User

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession) -> None:
    if message.from_user is None:
        return

    tg_id = message.from_user.id
    existing = await session.scalar(select(User).where(User.telegram_id == tg_id))
    if existing is None:
        session.add(
            User(
                telegram_id=tg_id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
            )
        )
        await session.commit()

    await message.answer(
        "Olá! Sou o bot de viagens. Mande /help para ver o que sei fazer."
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "Comandos:\n"
        "/start - registra você no bot\n"
        "/help - mostra esta ajuda\n"
        "Qualquer outro texto eu repito de volta (por enquanto)."
    )
