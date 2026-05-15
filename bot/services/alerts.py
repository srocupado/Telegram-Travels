from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from anthropic import AsyncAnthropic

from bot.config import Settings
from bot.db.models import Watch

logger = logging.getLogger(__name__)


def should_alert(watch: Watch, new_price: float, cooldown_hours: int) -> tuple[bool, str]:
    now = datetime.now(timezone.utc)
    if watch.snooze_until and watch.snooze_until > now:
        return False, "snoozed"
    if watch.last_alert_at and now - watch.last_alert_at < timedelta(hours=cooldown_hours):
        if watch.last_price is None or new_price >= watch.last_price * 0.95:
            return False, "cooldown"
    if watch.max_price is not None and new_price <= watch.max_price:
        return True, "below_max"
    if watch.min_price_seen is None:
        return True, "first_check"
    if new_price <= watch.min_price_seen * 0.9:
        return True, "new_low"
    return False, "no_trigger"


COMPOSER_SYSTEM = """Você redige alertas curtos de queda de preço de passagens/hotéis pra um bot do Telegram, em português brasileiro, tom amigável e direto.

Regras:
- Máximo 4 linhas. Inclua: rota/destino, data, preço atual (com R$), comparação com mínimo anterior se houver, motivo do alerta.
- Use 1 emoji no início (✈️ para passagem, 🏨 para hotel).
- Não invente dados. Use só os fatos do JSON.
- Não use markdown — texto puro.
"""


async def compose_alert_message(
    client: AsyncAnthropic,
    settings: Settings,
    watch: Watch,
    new_price: float,
    reason: str,
) -> str:
    facts = {
        "kind": watch.kind,
        "summary": watch.summary,
        "params": watch.params,
        "new_price": new_price,
        "currency": watch.currency,
        "previous_min": watch.min_price_seen,
        "max_price_target": watch.max_price,
        "reason": reason,
    }
    try:
        response = await client.messages.create(
            model=settings.haiku_model,
            max_tokens=400,
            system=COMPOSER_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(facts, ensure_ascii=False)}],
        )
        text = next((b.text for b in response.content if b.type == "text"), "")
        if text.strip():
            return text.strip()
    except Exception:
        logger.exception("compose_alert_message failed; falling back to template")
    emoji = "✈️" if watch.kind == "flight" else "🏨"
    return (
        f"{emoji} Alerta de preço: {watch.summary}\n"
        f"Agora: R$ {new_price:.2f}"
    )
