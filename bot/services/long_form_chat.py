from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from aiogram.types import Message
from anthropic import AsyncAnthropic

from bot.config import Settings
from bot.services.long_form import StreamResult, _safe_edit, _split_index

logger = logging.getLogger(__name__)

CONTEXT_TTL = timedelta(minutes=30)
MAX_HISTORY_TURNS = 6
TELEGRAM_LIMIT = 3800
EDIT_INTERVAL = 1.5

FOLLOWUP_SYSTEM = """Você está respondendo perguntas de follow-up sobre uma resposta anterior sua (um roteiro de viagem ou um guia de compras).

Regras:
- Responda DIRETO e CURTO, focado só na nova pergunta.
- Use o conteúdo anterior como contexto — não repita o que já foi dito.
- HTML do Telegram permitido: <b>, <i>. NÃO use markdown.
- Não invente dados que não estão na conversa.
- Para qualquer lugar com nome próprio que mencionar (loja, atração, restaurante, bairro), envolva em [[Nome|Cidade]] — será convertido em link clicável pro Google Maps.
- Se a pergunta sair completamente do tema (ex: outra cidade, outro produto), diga que pra isso é melhor usar /roteiro ou /compras de novo.
"""


@dataclass
class LongFormContext:
    kind: Literal["roteiro", "compras"]
    messages: list[dict[str, Any]] = field(default_factory=list)
    last_activity: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def touch(self) -> None:
        self.last_activity = datetime.now(timezone.utc)

    def is_stale(self) -> bool:
        return datetime.now(timezone.utc) - self.last_activity > CONTEXT_TTL


class LongFormStore:
    def __init__(self) -> None:
        self._contexts: dict[int, LongFormContext] = {}

    def save_initial(
        self, user_id: int, kind: Literal["roteiro", "compras"], question: str, answer: str
    ) -> None:
        self._contexts[user_id] = LongFormContext(
            kind=kind,
            messages=[
                {"role": "user", "content": question},
                {"role": "assistant", "content": answer},
            ],
        )

    def get(self, user_id: int) -> LongFormContext | None:
        ctx = self._contexts.get(user_id)
        if ctx is None:
            return None
        if ctx.is_stale():
            self._contexts.pop(user_id, None)
            return None
        return ctx

    def append_turn(self, user_id: int, question: str, answer: str) -> None:
        ctx = self._contexts.get(user_id)
        if ctx is None:
            return
        ctx.messages.append({"role": "user", "content": question})
        ctx.messages.append({"role": "assistant", "content": answer})
        ctx.messages = ctx.messages[-MAX_HISTORY_TURNS * 2 :]
        ctx.touch()

    def clear(self, user_id: int) -> None:
        self._contexts.pop(user_id, None)


async def stream_followup_to_telegram(
    client: AsyncAnthropic,
    settings: Settings,
    ctx: LongFormContext,
    user_text: str,
    placeholder: Message,
    store: LongFormStore,
    user_id: int,
) -> StreamResult:
    import time

    import anthropic

    request_messages = ctx.messages + [{"role": "user", "content": user_text}]

    try:
        async with client.messages.stream(
            model=settings.sonnet_model,
            max_tokens=4000,
            system=FOLLOWUP_SYSTEM,
            messages=request_messages,
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

            final = await stream.get_final_message()
            if current.strip():
                await _safe_edit(messages[-1], current)
                chunks.append(current.strip())

            if final.stop_reason == "refusal":
                await _safe_edit(
                    placeholder,
                    "🙅 A IA recusou esse pedido por questões de política. Reformule.",
                )
                return StreamResult(error="refusal", truncated=False)

            full = "\n\n".join(chunks).strip()
            if full:
                store.append_turn(user_id, user_text, full)

            return StreamResult(error=None, truncated=final.stop_reason == "max_tokens")

    except anthropic.APITimeoutError:
        await _safe_edit(placeholder, "⏱️ A IA demorou demais pra responder. Tenta de novo.")
        return StreamResult(error="timeout", truncated=False)
    except anthropic.RateLimitError:
        await _safe_edit(placeholder, "🚦 Limite de uso da IA. Espera alguns minutos.")
        return StreamResult(error="rate_limit", truncated=False)
    except anthropic.APIStatusError as e:
        logger.exception("anthropic api status error")
        msg = (
            "🛠️ Instabilidade na IA. Tenta de novo daqui a pouco."
            if e.status_code >= 500
            else f"❌ Erro da IA ({e.status_code})."
        )
        await _safe_edit(placeholder, msg)
        return StreamResult(error="api_status", truncated=False)
    except anthropic.APIConnectionError:
        await _safe_edit(placeholder, "🌐 Falha de conexão com a IA. Tenta de novo.")
        return StreamResult(error="connection", truncated=False)
    except Exception:
        logger.exception("followup unexpected failure")
        await _safe_edit(placeholder, "❌ Algo deu errado. Tenta de novo.")
        return StreamResult(error="unknown", truncated=False)
