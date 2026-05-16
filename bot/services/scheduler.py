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
    extract_price_insights,
    find_best_flight_in_window,
    find_best_hotel_in_window,
    format_flight,
    format_hotel,
)

FLEX_FLIGHT_WEEKDAYS = (1, 3)
HIGH_STREAK_BACKOFF_THRESHOLD = 2
HIGH_STREAK_BACKOFF_DAYS = 7


def _is_due(watch: Watch, now_utc: datetime, default_hours: int) -> bool:
    if watch.kind == "flight" and watch.params.get("window_start"):
        if now_utc.weekday() not in FLEX_FLIGHT_WEEKDAYS:
            return False
        if watch.last_checked_at is None:
            return True
        if (watch.high_streak or 0) >= HIGH_STREAK_BACKOFF_THRESHOLD:
            return now_utc - watch.last_checked_at >= timedelta(days=HIGH_STREAK_BACKOFF_DAYS)
        return watch.last_checked_at.date() < now_utc.date()
    if watch.last_checked_at is None:
        return True
    return now_utc - watch.last_checked_at >= timedelta(hours=default_hours)

logger = logging.getLogger(__name__)


async def check_watch(
    session: AsyncSession,
    serpapi: SerpAPIClient,
    claude: AsyncAnthropic,
    bot: Bot,
    settings: Settings,
    watch: Watch,
) -> None:
    chosen_ci: str | None = None
    chosen_co: str | None = None
    chosen_dep: str | None = None
    chosen_ret: str | None = None
    insights: dict | None = None
    try:
        if watch.kind == "flight":
            if watch.params.get("window_start") and watch.params.get("nights"):
                dests = watch.params.get("destination_iatas") or (
                    [watch.params["destination_iata"]]
                    if watch.params.get("destination_iata")
                    else []
                )
                flex = await find_best_flight_in_window(
                    serpapi,
                    watch.params["origin_iata"],
                    dests,
                    watch.params["window_start"],
                    watch.params["window_end"],
                    int(watch.params["nights"]),
                    adults=watch.params.get("adults", 1),
                    currency=watch.currency,
                )
                if flex is not None:
                    price, payload, chosen_dep, chosen_ret, _, insights = flex
                    best = (price, payload)
                else:
                    best = None
            else:
                single_dest = watch.params.get("destination_iata") or (
                    (watch.params.get("destination_iatas") or [""])[0]
                )
                raw = await serpapi.search_flights(
                    origin_iata=watch.params["origin_iata"],
                    destination_iata=single_dest,
                    depart_date=watch.params["depart_date"],
                    return_date=watch.params.get("return_date"),
                    adults=watch.params.get("adults", 1),
                    currency=watch.currency,
                )
                best = extract_best_flight(raw)
                insights = extract_price_insights(raw)
        elif watch.kind == "hotel":
            if watch.params.get("nights") and watch.params.get("window_start"):
                flex = await find_best_hotel_in_window(
                    serpapi,
                    watch.params["location"],
                    watch.params["window_start"],
                    watch.params["window_end"],
                    int(watch.params["nights"]),
                    adults=watch.params.get("adults", 2),
                    currency=watch.currency,
                )
                if flex is not None:
                    price, payload, chosen_ci, chosen_co = flex
                    best = (price, payload)
                else:
                    best = None
            else:
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

    fire, reason = should_alert(watch, price, settings.alert_cooldown_hours, insights)
    watch.last_price = price
    if watch.min_price_seen is None or price < watch.min_price_seen:
        watch.min_price_seen = price

    level = (insights or {}).get("price_level") if isinstance(insights, dict) else None
    watch.high_streak = (watch.high_streak or 0) + 1 if level == "high" else 0

    if fire:
        headline = await compose_alert_message(claude, settings, watch, price, reason)
        details = (
            format_flight(price, payload, chosen_dep, chosen_ret, insights)
            if watch.kind == "flight"
            else format_hotel(price, payload, chosen_ci, chosen_co)
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
    now_utc = datetime.now(timezone.utc)
    async with sessionmaker() as session:
        stmt = select(Watch).where(Watch.status == "active")
        all_active = list((await session.scalars(stmt)).all())

    due: list[Watch] = [
        w for w in all_active
        if _is_due(w, now_utc, settings.watch_check_interval_hours)
    ]

    logger.info("scheduler tick: %d watch(es) due (of %d active)", len(due), len(all_active))
    for w in due:
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
