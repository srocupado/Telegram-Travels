from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from anthropic import AsyncAnthropic
from pydantic import ValidationError

from bot.config import Settings
from bot.services.parser import ParsedWatch

logger = logging.getLogger(__name__)

SESSION_TTL = timedelta(minutes=30)
MAX_TURNS = 12

CHAT_SYSTEM = """Você é um assistente que ajuda o usuário a criar um monitoramento de preços de passagem ou hotel para um bot do Telegram, em português brasileiro.

Hoje é {today}.

Seu trabalho:
1. Identificar se o pedido é PASSAGEM ou HOTEL.
2. Coletar os dados necessários, fazendo UMA pergunta curta por vez quando faltar algo:
   - Passagem: origem (cidade ou IATA), destino, data de ida (YYYY-MM-DD), data de volta (opcional, se não disser nada assuma só ida), adultos (default 1), teto de preço opcional em BRL.
   - Hotel: cidade/região, check-in, check-out, adultos (default 2), teto opcional por diária em BRL.
3. Cidades com vários aeroportos: assuma o principal (São Paulo → GRU, Rio → GIG, Buenos Aires → EZE, Lisboa → LIS). Se quiser confirmar, pergunte.
4. Datas: se o usuário falar mês sem ano, use o próximo mês desse nome a partir de hoje. Se falar "semana que vem", calcule.

Quando tiver TUDO, apresente um resumo curto e pergunte "Confirma? (sim/não)".

Quando o usuário confirmar (sim/ok/confirma/pode/manda/cria), responda APENAS com este bloco, sem nada antes ou depois:

<CREATE>
{{"kind": "flight" ou "hotel", "origin_iata": "XXX" ou null, "destination_iata": "XXX" ou null, "location": "string" ou null, "depart_date": "YYYY-MM-DD" ou null, "return_date": "YYYY-MM-DD" ou null, "check_in": "YYYY-MM-DD" ou null, "check_out": "YYYY-MM-DD" ou null, "adults": número, "max_price_brl": número ou null, "currency": "BRL", "summary": "frase curta de até 80 chars"}}
</CREATE>

Quando o usuário cancelar/desistir (cancela/esquece/deixa pra lá/não), responda APENAS com:
<CANCEL/>

Regras de estilo:
- Mensagens curtas, no máximo 3 linhas.
- Sem markdown, texto puro.
- Não use emoji.
"""

CREATE_RE = re.compile(r"<CREATE>\s*(\{.*?\})\s*</CREATE>", re.DOTALL)


@dataclass
class ChatSession:
    messages: list[dict[str, Any]] = field(default_factory=list)
    last_activity: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def touch(self) -> None:
        self.last_activity = datetime.now(timezone.utc)

    def is_stale(self) -> bool:
        return datetime.now(timezone.utc) - self.last_activity > SESSION_TTL


class ChatStore:
    def __init__(self) -> None:
        self._sessions: dict[int, ChatSession] = {}

    def get(self, user_id: int) -> ChatSession:
        s = self._sessions.get(user_id)
        if s is None or s.is_stale():
            s = ChatSession()
            self._sessions[user_id] = s
        return s

    def clear(self, user_id: int) -> None:
        self._sessions.pop(user_id, None)


@dataclass
class ChatTurn:
    reply: str | None
    watch: ParsedWatch | None
    cancelled: bool


def _system_prompt() -> str:
    return CHAT_SYSTEM.format(today=date.today().isoformat())


async def chat_turn(
    client: AsyncAnthropic,
    settings: Settings,
    store: ChatStore,
    user_id: int,
    user_text: str,
) -> ChatTurn:
    session = store.get(user_id)
    session.messages.append({"role": "user", "content": user_text})
    session.messages = session.messages[-MAX_TURNS * 2 :]
    session.touch()

    response = await client.messages.create(
        model=settings.haiku_model,
        max_tokens=600,
        system=_system_prompt(),
        messages=session.messages,
    )
    text = next((b.text for b in response.content if b.type == "text"), "").strip()

    if "<CANCEL" in text:
        store.clear(user_id)
        return ChatTurn(reply="Tudo bem, cancelado.", watch=None, cancelled=True)

    match = CREATE_RE.search(text)
    if match:
        try:
            data = json.loads(match.group(1))
            watch = ParsedWatch.model_validate(data)
        except (json.JSONDecodeError, ValidationError):
            logger.warning("invalid <CREATE> payload: %r", match.group(1)[:200])
            session.messages.append({"role": "assistant", "content": text})
            return ChatTurn(
                reply="Tive um problema validando os dados. Pode repetir o pedido?",
                watch=None,
                cancelled=False,
            )
        store.clear(user_id)
        return ChatTurn(reply=None, watch=watch, cancelled=False)

    session.messages.append({"role": "assistant", "content": text})
    return ChatTurn(reply=text or "Pode reformular?", watch=None, cancelled=False)
