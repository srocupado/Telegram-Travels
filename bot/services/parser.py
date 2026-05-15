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
    location: str | None = None
    depart_date: str | None = None
    return_date: str | None = None
    check_in: str | None = None
    check_out: str | None = None
    adults: int = 1
    max_price_brl: float | None = None
    currency: str = "BRL"
    summary: str = ""
    clarification_needed: str | None = None


SYSTEM_PROMPT = """Você é o parser de pedidos de monitoramento de viagens. O usuário escreve em português livre e você extrai os parâmetros estruturados em JSON.

Regras:
- Identifique se é PASSAGEM (kind="flight") ou HOTEL (kind="hotel"). Se não der pra inferir, use kind="unclear" e preencha clarification_needed com UMA pergunta curta em português pedindo o que falta.
- Para passagens: origin_iata e destination_iata são códigos IATA de 3 letras (ex: GRU, GIG, BSB, EZE, JFK, LIS). Se a cidade tiver vários aeroportos, escolha o principal (São Paulo → GRU, Rio → GIG, Buenos Aires → EZE).
- Datas no formato YYYY-MM-DD. Hoje é {today}. Se o usuário disser "julho" sem ano, assuma o próximo julho a partir de hoje. Se só uma data, é one-way (return_date null).
- Para hotéis: location é texto livre (ex: "Buenos Aires", "Centro de Lisboa"). check_in e check_out obrigatórios.
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
        "location": {"type": ["string", "null"]},
        "depart_date": {"type": ["string", "null"]},
        "return_date": {"type": ["string", "null"]},
        "check_in": {"type": ["string", "null"]},
        "check_out": {"type": ["string", "null"]},
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


async def parse_watch(client: AsyncAnthropic, settings: Settings, text: str) -> ParsedWatch:
    try:
        response = await client.messages.create(
            model=settings.haiku_model,
            max_tokens=1024,
            system=_system_prompt(),
            messages=[{"role": "user", "content": text}],
            output_config={
                "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}
            },
        )
    except TypeError:
        response = await client.messages.create(
            model=settings.haiku_model,
            max_tokens=1024,
            system=_system_prompt() + "\nResponda apenas com JSON válido seguindo o schema combinado.",
            messages=[{"role": "user", "content": text}],
        )

    raw_text = next((b.text for b in response.content if b.type == "text"), "").strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        if raw_text.lower().startswith("json"):
            raw_text = raw_text[4:].strip()

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
