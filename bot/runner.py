import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot import handlers
from bot.config import Settings
from bot.db.session import make_engine, make_sessionmaker
from bot.logging_setup import setup_logging
from bot.middlewares.db import DbSessionMiddleware

logger = logging.getLogger(__name__)


async def main() -> None:
    settings = Settings()
    setup_logging(settings)

    engine = make_engine(settings)
    sessionmaker = make_sessionmaker(engine)

    bot = Bot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.update.middleware(DbSessionMiddleware(sessionmaker))
    dp.include_router(handlers.router)

    logger.info("Start polling")
    try:
        await dp.start_polling(bot, handle_signals=True)
    finally:
        await bot.session.close()
        await engine.dispose()
        logger.info("Bot stopped")
