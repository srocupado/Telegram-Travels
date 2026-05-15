from aiogram import F, Router
from aiogram.types import Message

router = Router(name="echo")


@router.message(F.text)
async def echo(message: Message) -> None:
    await message.answer(message.text or "")
