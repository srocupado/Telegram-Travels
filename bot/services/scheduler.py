from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from anthropic import AsyncAnthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.config import Settings
from bot.db.models import Alert, PriceSnapshot, User, Watch
from bot.services.alerts import compose_alert_message, should_alert
from bot.services.serpapi_client import (
    SerpAPIClient,
    SerpAPIError,
    extract_best_flight,
    extract_best_hotel,
    format_flight,
    format_hotel,
)

logger = logging.getLogger(__name__)


async def check_watch(
    session: AsyncSession,
    serpapi: SerpAPIClient,
    claude: AsyncAnthropic,
    bot: Bot,
    settings: Settings,
    watch: Watch,
) -> None:
    try:
        if watch.kind == "flight":
            raw = await serpapi.search_flights(
                origin_iata=watch.params["origin_iata"],
                destination_iata=watch.params["destination_iata"],
                depart_date=watch.params["depart_date"],
                return_date=watch.params.get("return_date"),
                adults=watch.params.get("adults", 1),
                currency=watch.currency,
            )
            best = extract_best_flight(raw)
        elif watch.kind == "hotel":
            raw = await serpapi.search_hotels(
                location=watch.params["location"],
                check_in=watch.params["check_in"],
                check_out=watch.params["check_out"],
                adults=watch.params.get("adults", 2),
                currency=watch.currency,
            )
            best = extract_best_hotel(raw)
        else:
            logger.warning("unknown watch kind: %s", watch.kind)
            return
    except SerpAPIError as e:
        logger.warning("serpapi error for watch %d: %s", watch.id, e)
        watch.last_checked_at = datetime.now(timezone.utc)
        await session.commit()
        return

    now = datetime.now(timezone.utc)
    watch.last_checked_at = now

    if best is None:
        logger.info("no price found for watch %d", watch.id)
        await session.commit()
        return

    price, payload = best
    snapshot = PriceSnapshot(
        watch_id=watch.id, price=price, currency=watch.currency, raw=payload
    )
    session.add(snapshot)
    await session.flush()

    fire, reason = should_alert(watch, price, settings.alert_cooldown_hours)
    watch.last_price = price
    if watch.min_price_seen is None or price < watch.min_price_seen:
        watch.min_price_seen = price

    if fire:
        headline = await compose_alert_message(claude, settings, watch, price, reason)
        details = (
            format_flight(price, payload)
            if watch.kind == "flight"
            else format_hotel(price, payload)
        )
        message = f"{headline}\n\n{details}"
        user = await session.get(User, watch.user_id)
        if user is not None:
            try:
                await bot.send_message(
                    user.telegram_id, message, disable_web_page_preview=True
                )
            except Exception:
                logger.exception("failed to send alert for watch %d", watch.id)
            else:
                watch.last_alert_at = now
                session.add(
                    Alert(
                        watch_id=watch.id,
                        snapshot_id=snapshot.id,
                        price=price,
                        reason=reason,
                    )
                )
    await session.commit()


async def tick(
    sessionmaker: async_sessionmaker[AsyncSession],
    serpapi: SerpAPIClient,
    claude: AsyncAnthropic,
    bot: Bot,
    settings: Settings,
) -> None:
    threshold = datetime.now(timezone.utc) - timedelta(hours=settings.watch_check_interval_hours)
    async with sessionmaker() as session:
        stmt = select(Watch).where(
            Watch.status == "active",
            (Watch.last_checked_at.is_(None)) | (Watch.last_checked_at < threshold),
        )
        watches = list((await session.scalars(stmt)).all())
    logger.info("scheduler tick: %d watch(es) due", len(watches))
    for w in watches:
        async with sessionmaker() as session:
            fresh = await session.get(Watch, w.id)
            if fresh is None or fresh.status != "active":
                continue
            await check_watch(session, serpapi, claude, bot, settings, fresh)


async def run_scheduler(
    sessionmaker: async_sessionmaker[AsyncSession],
    serpapi: SerpAPIClient,
    claude: AsyncAnthropic,
    bot: Bot,
    settings: Settings,
) -> None:
    logger.info("scheduler started; tick=%ds", settings.scheduler_tick_seconds)
    while True:
        try:
            await tick(sessionmaker, serpapi, claude, bot, settings)
        except Exception:
            logger.exception("scheduler tick crashed")
        await asyncio.sleep(settings.scheduler_tick_seconds)
