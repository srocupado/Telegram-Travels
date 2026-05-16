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
router = Router(name="roteiro")

ROTEIRO_SYSTEM = """Você cria roteiros de viagem em português brasileiro, prontos pra serem lidos em um app de mensagens.

Formato obrigatório:
- 1 frase curta de abertura sobre o destino (sem título).
- Depois, para cada dia: linha com <b>Dia N — &lt;tema do dia&gt;</b>, seguida de três blocos rotulados <b>Manhã</b>, <b>Tarde</b> e <b>Noite</b>, cada um com 1–3 sugestões específicas (nome do lugar/bairro e por que vale a pena, em 1 frase).
- Ao final, uma seção <b>Dicas</b> com 3 a 5 itens curtos (transporte, segurança, comida típica, melhor horário, etc).

Regras:
- HTML do Telegram permitido: &lt;b&gt;, &lt;i&gt;, &lt;u&gt;. NÃO use markdown (sem **, sem #).
- Sem estimativas de custo, sem links.
- Use bullets com "•" no início da linha quando listar.
- Linha em branco entre dias e antes de Dicas.
- Se a duração não for dita, assuma 5 dias.
- Se o usuário deu interesses (gastronomia, museus, natureza, vida noturna, com crianças, etc), use isso pra calibrar as sugestões.
- Nomes de lugares devem ser reais e reconhecíveis.
- Para cada lugar específico que mencionar (atração, restaurante, museu, bairro famoso, parque, mirante), envolva o nome usando colchetes duplos no formato: dois colchetes de abertura, depois Nome do Lugar, depois pipe, depois Cidade, depois dois colchetes de fechamento. Exemplo exato (siga este formato literalmente, sem tags HTML em volta): [[Castelo de São Jorge|Lisboa]]. Esses marcadores serão convertidos em links clicáveis pro Google Maps. NÃO use tags HTML como &lt;code&gt; ou &lt;b&gt; em volta dos marcadores — só os colchetes duplos puros. Use marcadores APENAS em nomes próprios reais; não em textos genéricos como "almoço típico" ou "a praia local".
"""


@router.message(Command("roteiro"))
async def cmd_roteiro(
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
            "Uso: /roteiro &lt;destino e detalhes&gt;\n"
            "Ex: <i>/roteiro 5 dias em Lisboa em outubro, casal, gastronomia e arquitetura</i>"
        )
        return

    placeholder = await message.answer("🗺️ Montando o roteiro… acompanhe abaixo:")

    result = await stream_long_form_to_telegram(
        claude, settings, ROTEIRO_SYSTEM, command.args, placeholder, max_tokens=32000
    )

    if result.truncated:
        await message.answer(
            "⚠️ O roteiro era grande demais e foi cortado no meio. "
            "Tenta pedir menos dias por vez (ex: divida em 2 partes de 10 dias)."
        )

    if result.error is None and result.text:
        long_form_store.save_initial(
            message.from_user.id, "roteiro", command.args, result.text
        )
        await message.answer(
            "💬 Quer perguntar algo sobre esse roteiro? Use <code>/seguir &lt;pergunta&gt;</code>."
        )
