from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.filters.command import CommandObject
from aiogram.types import Message
from anthropic import AsyncAnthropic

from bot.config import Settings
from bot.services.long_form import stream_long_form_to_telegram
from bot.services.long_form_chat import LongFormStore

logger = logging.getLogger(__name__)
router = Router(name="compras")

COMPRAS_SYSTEM = """Você é um guia de compras para viajantes, em português brasileiro, pronto pra ser lido em um app de mensagens.

O usuário diz o que quer comprar e onde (cidade ou país). Você responde com onde encontrar.

Formato obrigatório:
- 1 frase de abertura curta sobre o cenário de compras do destino pra esse tipo de produto.
- Depois, para cada bairro/região/mercado/shopping relevante: linha com <b>&lt;Nome do lugar&gt; — &lt;tipo: bairro, shopping, mercado, rua, etc&gt;</b>, seguida de 1–3 bullets com "•". Cada bullet: o que comprar ali + por que é o lugar certo (1 frase). Inclua nomes de lojas/marcas reconhecíveis quando fizer sentido.
- Mínimo 3, máximo 6 lugares. Priorize variedade (bairro local + shopping turístico + mercado/feira, por exemplo).
- Ao final, uma seção <b>Dicas</b> com 3 a 5 bullets curtos sobre: tax-free/reembolso de imposto se aplicável, formas de pagamento (cartão/dinheiro/moeda local), horários típicos, segurança/bairros a evitar, dias da semana melhores, pechincha sim/não.

Regras:
- HTML do Telegram permitido: &lt;b&gt;, &lt;i&gt;, &lt;u&gt;. NÃO use markdown.
- Sem estimativas de preço, sem links.
- Linha em branco entre lugares e antes de Dicas.
- Se o usuário não disse o que quer comprar (só citou cidade), peça UMA pergunta curta de clarificação no lugar de gerar o guia.
- Nomes de lugares e lojas devem ser reais e atuais.
- Para cada lugar com nome próprio (shopping, mercado, loja, bairro, rua famosa), envolva usando colchetes duplos no formato: dois colchetes de abertura, Nome, pipe, Cidade, dois colchetes de fechamento. Exemplo exato (siga literalmente, sem tags HTML em volta): [[Shopping Patio Bullrich|Buenos Aires]]. Esses marcadores viram links clicáveis pro Google Maps. NÃO use tags HTML como &lt;code&gt; ou &lt;b&gt; em volta dos marcadores — só os colchetes puros. Não envolva descritivos genéricos ("uma loja qualquer", "vários shoppings").
"""


@router.message(Command("compras"))
async def cmd_compras(
    message: Message,
    command: CommandObject,
    claude: AsyncAnthropic,
    settings: Settings,
    long_form_store: LongFormStore,
) -> None:
    if message.from_user is None:
        return
    if not command.args:
        await message.answer(
            "Uso: /compras &lt;o que comprar&gt; em &lt;cidade/país&gt;\n"
            "Ex: <i>/compras roupas e perfumes em Buenos Aires</i>\n"
            "Ex: <i>/compras eletrônicos em Miami</i>"
        )
        return

    placeholder = await message.answer("🛍️ Pesquisando lugares… acompanhe abaixo:")

    result = await stream_long_form_to_telegram(
        claude, settings, COMPRAS_SYSTEM, command.args, placeholder, max_tokens=8000
    )

    if result.truncated:
        await message.answer(
            "⚠️ A resposta era grande demais e foi cortada. "
            "Tenta reduzir o escopo (uma cidade ou um tipo de produto por vez)."
        )

    if result.error is None and result.text:
        long_form_store.save_initial(
            message.from_user.id, "compras", command.args, result.text
        )
        await message.answer(
            "💬 Quer perguntar algo mais (ex: qual mais barato, qual fica perto de X)? "
            "Use <code>/seguir &lt;pergunta&gt;</code>."
        )
