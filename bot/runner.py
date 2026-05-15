import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot import handlers
from bot.config import Settings
from bot.db import models  # noqa: F401  registers tables on Base.metadata
from bot.db.base import Base
from bot.db.session import make_engine, make_sessionmaker
from bot.logging_setup import setup_logging
from bot.middlewares.db import DepsMiddleware
from bot.services.claude_client import make_claude
from bot.services.scheduler import run_scheduler
from bot.services.serpapi_client import SerpAPIClient

logger = logging.getLogger(__name__)


async def main() -> None:
    settings = Settings()
    setup_logging(settings)

    engine = make_engine(settings)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    sessionmaker = make_sessionmaker(engine)
    claude = make_claude(settings)
    serpapi = SerpAPIClient(settings)

    bot = Bot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.update.middleware(DepsMiddleware(sessionmaker, settings, claude, serpapi))
    dp.include_router(handlers.router)

    scheduler_task = asyncio.create_task(
        run_scheduler(sessionmaker, serpapi, claude, bot, settings)
    )

    logger.info("Start polling")
    try:
        await dp.start_polling(bot, handle_signals=True)
    finally:
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass
        await serpapi.close()
        await bot.session.close()
        await engine.dispose()
        logger.info("Bot stopped")
