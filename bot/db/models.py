from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from bot.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(128))
    is_authorized: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    congress_subscribed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0"
    )
    last_congress_digest_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    congress_hour: Mapped[int | None] = mapped_column(Integer)
    congress_minute: Mapped[int | None] = mapped_column(Integer)
    traffic_subscribed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0"
    )
    last_traffic_digest_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    traffic_hour: Mapped[int | None] = mapped_column(Integer)
    traffic_minute: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Watch(Base):
    __tablename__ = "watches"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    params: Mapped[dict[str, Any]] = mapped_column(JSON)
    max_price: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8), default="BRL")
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    summary: Mapped[str] = mapped_column(String(256), default="")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_price: Mapped[float | None] = mapped_column(Float)
    last_alert_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    min_price_seen: Mapped[float | None] = mapped_column(Float)
    snooze_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    high_streak: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PriceSnapshot(Base):
    __tablename__ = "price_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    watch_id: Mapped[int] = mapped_column(ForeignKey("watches.id"), index=True)
    price: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8))
    raw: Mapped[dict[str, Any]] = mapped_column(JSON)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    watch_id: Mapped[int] = mapped_column(ForeignKey("watches.id"), index=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("price_snapshots.id"))
    price: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String(64))
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
