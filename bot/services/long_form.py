from __future__ import annotations

import html
import logging
import re
import time
from dataclasses import dataclass
from urllib.parse import quote_plus

from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import Message

from bot.config import Settings
from bot.services.llm import (
    LLMAuth,
    LLMBadRequest,
    LLMClient,
    LLMConnection,
    LLMRateLimit,
    LLMServerError,
    LLMTimeout,
)

logger = logging.getLogger(__name__)

TELEGRAM_LIMIT = 3800
EDIT_INTERVAL = 1.5

_LINK_MARKER_RE = re.compile(r"\[\[([^|\]\[]+)\|([^\]\[]+)\]\]")


def linkify_places(text: str) -> str:
    def repl(m: re.Match[str]) -> str:
        name = m.group(1).strip()
        city = m.group(2).strip()
        query = quote_plus(f"{name} {city}")
        return (
            f'<a href="https://www.google.com/maps/search/?api=1&amp;query={query}">'
            f"{html.escape(name)}</a>"
        )

    return _LINK_MARKER_RE.sub(repl, text)


@dataclass
class StreamResult:
    error: str | None
    truncated: bool
    text: str = ""


def _split_index(text: str, limit: int) -> int:
    if len(text) <= limit:
        return len(text)
    candidates = [text.rfind("\n\n", 0, limit), text.rfind("\n", 0, limit), text.rfind(". ", 0, limit)]
    best = max(c for c in candidates if c >= 0) if any(c >= 0 for c in candidates) else -1
    return best if best > 200 else limit


async def _safe_edit(msg: Message, text: str) -> None:
    text = linkify_places(text)
    if not text.strip():
        return
    try:
        await msg.edit_text(text, disable_web_page_preview=True)
    except TelegramRetryAfter as e:
        logger.info("telegram rate limited; retry after %ss", e.retry_after)
    except TelegramBadRequest as e:
        msg_text = str(e).lower()
        if "not modified" in msg_text or "can't parse" in msg_text or "can't find" in msg_text:
            return
        logger.warning("edit_text failed: %s", e)


async def stream_long_form_to_telegram(
    llm: LLMClient,
    settings: Settings,
    system: str,
    user_text: str,
    placeholder: Message,
    max_tokens: int = 16000,
) -> StreamResult:
    try:
        async with llm.stream(
            speed="slow",
            system=system,
            messages=[{"role": "user", "content": user_text}],
            max_tokens=max_tokens,
        ) as stream:
            messages: list[Message] = [placeholder]
            current = ""
            chunks: list[str] = []
            last_edit = 0.0

            async for delta in stream.text_stream:
                current += delta

                while len(current) > TELEGRAM_LIMIT:
                    split = _split_index(current, TELEGRAM_LIMIT)
                    finalized = current[:split].rstrip()
                    await _safe_edit(messages[-1], finalized)
                    chunks.append(finalized)
                    current = current[split:].lstrip()
                    new_msg = await placeholder.answer(
                        current or "…", disable_web_page_preview=True
                    )
                    messages.append(new_msg)
                    last_edit = time.monotonic()

                now = time.monotonic()
                if now - last_edit >= EDIT_INTERVAL and current.strip():
                    await _safe_edit(messages[-1], current)
                    last_edit = now

            final = await stream.get_final()
            if current.strip():
                await _safe_edit(messages[-1], current)
                chunks.append(current.strip())

            if final.stop_reason == "refusal":
                await _safe_edit(
                    placeholder,
                    "🙅 A IA recusou esse pedido por questões de política. Reformule sem temas sensíveis.",
                )
                return StreamResult(error="refusal", truncated=False, text="")

            return StreamResult(
                error=None,
                truncated=final.stop_reason == "max_tokens",
                text="\n\n".join(chunks).strip(),
            )

    except LLMTimeout:
        await _safe_edit(placeholder, "⏱️ A IA demorou demais pra responder. Tenta de novo.")
        return StreamResult(error="timeout", truncated=False)
    except LLMRateLimit:
        await _safe_edit(
            placeholder,
            "🚦 Estamos no limite de uso da IA agora. Espera uns minutos e tenta de novo.",
        )
        return StreamResult(error="rate_limit", truncated=False)
    except LLMAuth:
        logger.exception("LLM auth error")
        await _safe_edit(placeholder, "🔑 Problema de autenticação com a IA. Avise o admin.")
        return StreamResult(error="auth", truncated=False)
    except LLMServerError as e:
        logger.exception("LLM server error")
        await _safe_edit(
            placeholder,
            f"🛠️ Instabilidade na IA ({e.status_code}). Tenta de novo daqui a pouco.",
        )
        return StreamResult(error="server", truncated=False)
    except LLMBadRequest as e:
        logger.exception("LLM bad request")
        await _safe_edit(placeholder, f"❌ Erro da IA ({e.status_code}). Tenta reformular.")
        return StreamResult(error="bad_request", truncated=False)
    except LLMConnection:
        await _safe_edit(placeholder, "🌐 Falha de conexão com a IA. Tenta de novo.")
        return StreamResult(error="connection", truncated=False)
    except Exception:
        logger.exception("long_form unexpected failure")
        await _safe_edit(placeholder, "❌ Algo deu errado. Tenta de novo.")
        return StreamResult(error="unknown", truncated=False)
