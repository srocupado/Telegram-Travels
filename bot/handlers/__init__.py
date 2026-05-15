from aiogram import Router

from bot.handlers import echo, start

router = Router(name="root")
router.include_router(start.router)
router.include_router(echo.router)
