from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import anthropic
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import Message
from anthropic import AsyncAnthropic

from bot.config import Settings

logger = logging.getLogger(__name__)

TELEGRAM_LIMIT = 3800
EDIT_INTERVAL = 1.5


@dataclass
class StreamResult:
    error: str | None
    truncated: bool


def _split_index(text: str, limit: int) -> int:
    if len(text) <= limit:
        return len(text)
    candidates = [text.rfind("\n\n", 0, limit), text.rfind("\n", 0, limit), text.rfind(". ", 0, limit)]
    best = max(c for c in candidates if c >= 0) if any(c >= 0 for c in candidates) else -1
    return best if best > 200 else limit


async def _safe_edit(msg: Message, text: str) -> None:
    if not text.strip():
        return
    try:
        await msg.edit_text(text)
    except TelegramRetryAfter as e:
        logger.info("telegram rate limited; retry after %ss", e.retry_after)
    except TelegramBadRequest as e:
        msg_text = str(e).lower()
        if "not modified" in msg_text or "can't parse" in msg_text or "can't find" in msg_text:
            return
        logger.warning("edit_text failed: %s", e)


async def stream_long_form_to_telegram(
    client: AsyncAnthropic,
    settings: Settings,
    system: str,
    user_text: str,
    placeholder: Message,
    max_tokens: int = 16000,
) -> StreamResult:
    try:
        async with client.messages.stream(
            model=settings.sonnet_model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_text}],
        ) as stream:
            messages: list[Message] = [placeholder]
            current = ""
            last_edit = 0.0

            async for delta in stream.text_stream:
                current += delta

                while len(current) > TELEGRAM_LIMIT:
                    split = _split_index(current, TELEGRAM_LIMIT)
                    await _safe_edit(messages[-1], current[:split].rstrip())
                    current = current[split:].lstrip()
                    new_msg = await placeholder.answer(current or "…")
                    messages.append(new_msg)
                    last_edit = time.monotonic()

                now = time.monotonic()
                if now - last_edit >= EDIT_INTERVAL and current.strip():
                    await _safe_edit(messages[-1], current)
                    last_edit = now

            final = await stream.get_final_message()
            if current.strip():
                await _safe_edit(messages[-1], current)

            if final.stop_reason == "refusal":
                await _safe_edit(
                    placeholder,
                    "🙅 A IA recusou esse pedido por questões de política. Reformule sem temas sensíveis.",
                )
                return StreamResult(error="refusal", truncated=False)

            return StreamResult(error=None, truncated=final.stop_reason == "max_tokens")

    except anthropic.APITimeoutError:
        await _safe_edit(placeholder, "⏱️ A IA demorou demais pra responder. Tenta de novo.")
        return StreamResult(error="timeout", truncated=False)
    except anthropic.RateLimitError:
        await _safe_edit(
            placeholder,
            "🚦 Estamos no limite de uso da IA agora. Espera uns minutos e tenta de novo.",
        )
        return StreamResult(error="rate_limit", truncated=False)
    except anthropic.AuthenticationError:
        logger.exception("anthropic auth error")
        await _safe_edit(placeholder, "🔑 Problema de autenticação com a IA. Avise o admin.")
        return StreamResult(error="auth", truncated=False)
    except anthropic.APIStatusError as e:
        logger.exception("anthropic api status error")
        msg = (
            "🛠️ Instabilidade na IA. Tenta de novo daqui a pouco."
            if e.status_code >= 500
            else f"❌ Erro da IA ({e.status_code}). Tenta reformular."
        )
        await _safe_edit(placeholder, msg)
        return StreamResult(error="api_status", truncated=False)
    except anthropic.APIConnectionError:
        await _safe_edit(placeholder, "🌐 Falha de conexão com a IA. Tenta de novo.")
        return StreamResult(error="connection", truncated=False)
    except Exception:
        logger.exception("long_form unexpected failure")
        await _safe_edit(placeholder, "❌ Algo deu errado. Tenta de novo.")
        return StreamResult(error="unknown", truncated=False)
