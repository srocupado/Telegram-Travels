from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aiogram import Router
from aiogram.filters import Command
from aiogram.filters.command import CommandObject
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import User, Watch

router = Router(name="manage")


async def _user_watch(
    session: AsyncSession, message: Message, watch_id: int
) -> Watch | None:
    if message.from_user is None:
        return None
    user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
    if user is None:
        return None
    watch = await session.get(Watch, watch_id)
    if watch is None or watch.user_id != user.id:
        return None
    return watch


def _parse_id(command: CommandObject) -> int | None:
    if not command.args:
        return None
    parts = command.args.split()
    if not parts:
        return None
    try:
        return int(parts[0])
    except ValueError:
        return None


@router.message(Command("list"))
async def cmd_list(message: Message, session: AsyncSession) -> None:
    if message.from_user is None:
        return
    user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
    if user is None:
        await message.answer("Você não tem nenhum monitoramento. Mande um pedido em texto pra criar.")
        return
    watches = list(
        (await session.scalars(select(Watch).where(Watch.user_id == user.id).order_by(Watch.id))).all()
    )
    if not watches:
        await message.answer("Nenhum monitoramento. Mande um pedido em texto pra criar.")
        return
    lines = ["<b>Seus monitoramentos:</b>"]
    for w in watches:
        emoji = "✈️" if w.kind == "flight" else "🏨"
        status = "▶️" if w.status == "active" else "⏸️"
        teto = f" (até R$ {w.max_price:.0f})" if w.max_price else ""
        last = f" — último: R$ {w.last_price:.2f}" if w.last_price else ""
        lines.append(f"{status} {emoji} #{w.id} {w.summary}{teto}{last}")
    await message.answer("\n".join(lines))


@router.message(Command("pause"))
async def cmd_pause(message: Message, command: CommandObject, session: AsyncSession) -> None:
    wid = _parse_id(command)
    if wid is None:
        await message.answer("Uso: /pause <id>")
        return
    watch = await _user_watch(session, message, wid)
    if watch is None:
        await message.answer("Monitoramento não encontrado.")
        return
    watch.status = "paused"
    await session.commit()
    await message.answer(f"⏸️ #{wid} pausado.")


@router.message(Command("resume"))
async def cmd_resume(message: Message, command: CommandObject, session: AsyncSession) -> None:
    wid = _parse_id(command)
    if wid is None:
        await message.answer("Uso: /resume <id>")
        return
    watch = await _user_watch(session, message, wid)
    if watch is None:
        await message.answer("Monitoramento não encontrado.")
        return
    watch.status = "active"
    await session.commit()
    await message.answer(f"▶️ #{wid} retomado.")


@router.message(Command("delete"))
async def cmd_delete(message: Message, command: CommandObject, session: AsyncSession) -> None:
    wid = _parse_id(command)
    if wid is None:
        await message.answer("Uso: /delete <id>")
        return
    watch = await _user_watch(session, message, wid)
    if watch is None:
        await message.answer("Monitoramento não encontrado.")
        return
    await session.delete(watch)
    await session.commit()
    await message.answer(f"🗑️ #{wid} apagado.")


@router.message(Command("snooze"))
async def cmd_snooze(message: Message, command: CommandObject, session: AsyncSession) -> None:
    if not command.args:
        await message.answer("Uso: /snooze <id> <horas>")
        return
    parts = command.args.split()
    if len(parts) < 2:
        await message.answer("Uso: /snooze <id> <horas>")
        return
    try:
        wid = int(parts[0])
        hours = int(parts[1])
    except ValueError:
        await message.answer("ID e horas precisam ser números.")
        return
    if hours <= 0:
        await message.answer("Horas precisa ser positivo.")
        return
    watch = await _user_watch(session, message, wid)
    if watch is None:
        await message.answer("Monitoramento não encontrado.")
        return
    watch.snooze_until = datetime.now(timezone.utc) + timedelta(hours=hours)
    await session.commit()
    await message.answer(f"🔕 #{wid} silenciado por {hours}h.")
