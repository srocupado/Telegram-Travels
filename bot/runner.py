import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bot import handlers
from bot.config import Settings
from bot.db import models  # noqa: F401  registers tables on Base.metadata
from bot.db.base import Base
from bot.db.session import make_engine, make_sessionmaker
from bot.logging_setup import setup_logging
from bot.middlewares.auth import AuthMiddleware
from bot.middlewares.db import DepsMiddleware
from bot.services.chat import ChatStore
from bot.services.claude_client import make_claude
from bot.services.scheduler import run_scheduler
from bot.services.serpapi_client import SerpAPIClient

logger = logging.getLogger(__name__)


async def _migrate_users_authorization(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        result = await conn.exec_driver_sql("PRAGMA table_info(users)")
        cols = [row[1] for row in result.fetchall()]
        if "is_authorized" in cols:
            return
        await conn.exec_driver_sql(
            "ALTER TABLE users ADD COLUMN is_authorized BOOLEAN NOT NULL DEFAULT 0"
        )
        await conn.execute(text("UPDATE users SET is_authorized = 1"))
        logger.info("migrated users table: added is_authorized; grandfathered existing users")


async def main() -> None:
    settings = Settings()
    setup_logging(settings)

    engine = make_engine(settings)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _migrate_users_authorization(engine)

    sessionmaker = make_sessionmaker(engine)
    claude = make_claude(settings)
    serpapi = SerpAPIClient(settings)
    chat_store = ChatStore()

    bot = Bot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.update.middleware(
        AuthMiddleware(sessionmaker, settings.access_password.get_secret_value())
    )
    dp.update.middleware(
        DepsMiddleware(sessionmaker, settings, claude, serpapi, chat_store)
    )
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
