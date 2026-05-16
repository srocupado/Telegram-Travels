from __future__ import annotations

import json
import logging
from datetime import date
from typing import Literal

from anthropic import AsyncAnthropic
from pydantic import BaseModel, ValidationError

from bot.config import Settings

logger = logging.getLogger(__name__)


class ParsedWatch(BaseModel):
    kind: Literal["flight", "hotel", "unclear"]
    origin_iata: str | None = None
    destination_iata: str | None = None
    destination_iatas: list[str] | None = None
    location: str | None = None
    depart_date: str | None = None
    return_date: str | None = None
    check_in: str | None = None
    check_out: str | None = None
    window_start: str | None = None
    window_end: str | None = None
    nights: int | None = None
    adults: int = 1
    max_price_brl: float | None = None
    currency: str = "BRL"
    summary: str = ""
    clarification_needed: str | None = None


SYSTEM_PROMPT = """Você é o parser de pedidos de monitoramento de viagens. O usuário escreve em português livre e você extrai os parâmetros estruturados em JSON.

Regras:
- Identifique se é PASSAGEM (kind="flight") ou HOTEL (kind="hotel"). Se não der pra inferir, use kind="unclear" e preencha clarification_needed com UMA pergunta curta em português pedindo o que falta.
- Para passagens: origin_iata e destination_iata são códigos IATA de 3 letras (ex: GRU, GIG, BSB, EZE, JFK, LIS). Se a cidade tiver vários aeroportos, escolha o principal (São Paulo → GRU, Rio → GIG, Buenos Aires → EZE).
- Se o usuário citar MAIS DE UM aeroporto de destino (ex: "Haneda ou Narita") ou um país/região sem especificar aeroporto (ex: "Japão"), preencha destination_iatas com a lista (ex: ["NRT","HND"]) e deixe destination_iata nulo. Para "Japão" use ["NRT","HND"]; para "EUA" peça clarificação.
- Modos de data pra passagem:
  (a) DATAS FIXAS: preencha depart_date (obrigatório) e return_date (opcional, null se one-way).
  (b) JANELA FLEXÍVEL: preencha window_start, window_end e nights (duração da estadia em dias). Use quando o usuário disser "ficando N dias" / "N dias de viagem" dentro de um intervalo (ex: "entre 9/9 e 30/11, ficando 20 dias"). Não preencha depart_date/return_date nesse caso.
- Para hotéis: location é texto livre (ex: "Buenos Aires", "Centro de Lisboa"). Existem dois modos:
  (a) datas fixas: preencha check_in e check_out (datas exatas). Use quando o usuário definir início e fim da estadia.
  (b) janela flexível: preencha window_start, window_end e nights (número de noites a procurar dentro da janela). Use quando o usuário disser algo como "2 noites entre 8 e 12 de julho", "qualquer 3 diárias na primeira semana de agosto", "uma diária entre dia 5 e 10". Não preencha check_in/check_out nesse caso.
  Regra: se a duração explicitada (nights) é MENOR que o tamanho da janela (window_end - window_start), use modo (b). Se for IGUAL, use modo (a).
- adults default 1 pra passagem, 2 pra hotel.
- max_price_brl: se o usuário mencionar teto de preço (ex: "até R$ 2000", "até 1500 reais"), converta pra número. Sem teto → null.
- currency sempre "BRL" salvo se o usuário pedir outra moeda.
- summary: frase curta (até 80 chars) descrevendo o monitoramento, ex: "GRU → EZE em 12/jul, até R$ 1800".
- Se faltar info crítica (destino, datas), kind="unclear" + clarification_needed.

Retorne apenas o JSON, sem texto adicional.
"""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["flight", "hotel", "unclear"]},
        "origin_iata": {"type": ["string", "null"]},
        "destination_iata": {"type": ["string", "null"]},
        "destination_iatas": {"type": ["array", "null"], "items": {"type": "string"}},
        "location": {"type": ["string", "null"]},
        "depart_date": {"type": ["string", "null"]},
        "return_date": {"type": ["string", "null"]},
        "check_in": {"type": ["string", "null"]},
        "check_out": {"type": ["string", "null"]},
        "window_start": {"type": ["string", "null"]},
        "window_end": {"type": ["string", "null"]},
        "nights": {"type": ["integer", "null"]},
        "adults": {"type": "integer"},
        "max_price_brl": {"type": ["number", "null"]},
        "currency": {"type": "string"},
        "summary": {"type": "string"},
        "clarification_needed": {"type": ["string", "null"]},
    },
    "required": ["kind", "adults", "currency", "summary"],
    "additionalProperties": False,
}


def _system_prompt() -> str:
    return SYSTEM_PROMPT.format(today=date.today().isoformat())


JSON_INSTRUCTION = (
    "\n\nResponda APENAS com um objeto JSON válido seguindo este schema, "
    "sem texto antes ou depois, sem ```json:\n"
    + json.dumps(OUTPUT_SCHEMA, ensure_ascii=False, indent=2)
)


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.lstrip("`").lstrip()
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
        if text.endswith("```"):
            text = text[:-3].rstrip()
    return text.strip()


async def parse_watch(client: AsyncAnthropic, settings: Settings, text: str) -> ParsedWatch:
    fast_client = client.with_options(timeout=30.0, max_retries=1)
    response = await fast_client.messages.create(
        model=settings.haiku_model,
        max_tokens=1024,
        system=_system_prompt() + JSON_INSTRUCTION,
        messages=[{"role": "user", "content": text}],
    )

    raw_text = next((b.text for b in response.content if b.type == "text"), "")
    raw_text = _strip_code_fence(raw_text)

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        logger.warning("parser returned non-JSON: %r", raw_text[:200])
        return ParsedWatch(
            kind="unclear",
            clarification_needed="Não consegui interpretar. Pode dar mais detalhes (origem, destino, datas)?",
        )

    try:
        return ParsedWatch.model_validate(data)
    except ValidationError:
        logger.warning("parser returned invalid schema: %s", data)
        return ParsedWatch(
            kind="unclear",
            clarification_needed="Não consegui interpretar. Pode dar mais detalhes (origem, destino, datas)?",
        )
