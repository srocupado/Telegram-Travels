import asyncio
import logging
from typing import Any

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
from bot.services.llm import make_llm
from bot.services.long_form_chat import LongFormStore
from bot.services.scheduler import run_scheduler
from bot.services.serpapi_client import SerpAPIClient

logger = logging.getLogger(__name__)


async def _column_exists(conn: Any, table: str, column: str) -> bool:
    result = await conn.exec_driver_sql(f"PRAGMA table_info({table})")
    return column in [row[1] for row in result.fetchall()]


async def _migrate(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        if not await _column_exists(conn, "users", "is_authorized"):
            await conn.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN is_authorized BOOLEAN NOT NULL DEFAULT 0"
            )
            await conn.execute(text("UPDATE users SET is_authorized = 1"))
            logger.info("migrated users.is_authorized; grandfathered existing users")

        if not await _column_exists(conn, "watches", "high_streak"):
            await conn.exec_driver_sql(
                "ALTER TABLE watches ADD COLUMN high_streak INTEGER NOT NULL DEFAULT 0"
            )
            logger.info("migrated watches.high_streak")

        if not await _column_exists(conn, "users", "congress_subscribed"):
            await conn.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN congress_subscribed BOOLEAN NOT NULL DEFAULT 0"
            )
            logger.info("migrated users.congress_subscribed")

        if not await _column_exists(conn, "users", "last_congress_digest_at"):
            await conn.exec_driver_sql(
                "ALTER TABLE users ADD COLUMN last_congress_digest_at DATETIME"
            )
            logger.info("migrated users.last_congress_digest_at")


async def main() -> None:
    settings = Settings()
    setup_logging(settings)

    engine = make_engine(settings)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _migrate(engine)

    sessionmaker = make_sessionmaker(engine)
    llm = make_llm(settings)
    serpapi = SerpAPIClient(settings)
    chat_store = ChatStore()
    long_form_store = LongFormStore()

    bot = Bot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.update.middleware(
        AuthMiddleware(sessionmaker, settings.access_password.get_secret_value())
    )
    dp.update.middleware(
        DepsMiddleware(
            sessionmaker, settings, llm, serpapi, chat_store, long_form_store
        )
    )
    dp.include_router(handlers.router)

    scheduler_task = asyncio.create_task(
        run_scheduler(sessionmaker, serpapi, llm, bot, settings)
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
        await llm.aclose()
        await serpapi.close()
        await bot.session.close()
        await engine.dispose()
        logger.info("Bot stopped")
