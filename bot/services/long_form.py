from __future__ import annotations

import logging
from dataclasses import dataclass

import anthropic
from anthropic import AsyncAnthropic

from bot.config import Settings

logger = logging.getLogger(__name__)


@dataclass
class LongFormResult:
    text: str
    error: str | None
    truncated: bool


async def generate_long_form(
    client: AsyncAnthropic,
    settings: Settings,
    system: str,
    user_text: str,
    max_tokens: int = 16000,
) -> LongFormResult:
    try:
        async with client.messages.stream(
            model=settings.sonnet_model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_text}],
        ) as stream:
            message = await stream.get_final_message()
    except anthropic.APITimeoutError:
        return LongFormResult("", "⏱️ A IA demorou demais pra responder. Tenta de novo.", False)
    except anthropic.RateLimitError:
        return LongFormResult(
            "", "🚦 Estamos no limite de uso da IA agora. Espera uns minutos e tenta de novo.", False
        )
    except anthropic.AuthenticationError:
        logger.exception("anthropic auth error")
        return LongFormResult(
            "", "🔑 Problema de autenticação com a IA. Avise o admin.", False
        )
    except anthropic.APIStatusError as e:
        logger.exception("anthropic api status error")
        if e.status_code >= 500:
            return LongFormResult("", "🛠️ Instabilidade na IA. Tenta de novo daqui a pouco.", False)
        return LongFormResult("", f"❌ Erro da IA ({e.status_code}). Tenta reformular.", False)
    except anthropic.APIConnectionError:
        return LongFormResult("", "🌐 Falha de conexão com a IA. Tenta de novo.", False)
    except Exception:
        logger.exception("long_form unexpected failure")
        return LongFormResult("", "❌ Algo deu errado. Tenta de novo.", False)

    if message.stop_reason == "refusal":
        return LongFormResult(
            "", "🙅 A IA recusou esse pedido por questões de política. Reformule sem temas sensíveis.", False
        )

    text = next((b.text for b in message.content if b.type == "text"), "").strip()
    truncated = message.stop_reason == "max_tokens"

    if not text:
        return LongFormResult("", "A IA voltou vazia. Tenta de novo com mais detalhes.", False)

    return LongFormResult(text=text, error=None, truncated=truncated)
