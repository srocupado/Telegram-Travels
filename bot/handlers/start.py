from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import User

router = Router(name="start")


WELCOME = (
    "Olá! Sou seu agente de viagens. Monitoro preços de passagens e hotéis e te aviso quando cair.\n\n"
    "Como usar: me mande uma mensagem como\n"
    "• <i>passagem GRU → EZE em 12 de julho, até R$ 1800</i>\n"
    "• <i>hotel em Buenos Aires de 12 a 15 de julho, até R$ 400 a diária</i>\n\n"
    "Use /help pra ver todos os comandos."
)

HELP = (
    "<b>Como usar</b>\n"
    "Mande o pedido em português livre — eu vou perguntando o que falta até montar o monitoramento. "
    "A conversa fica salva por 30 minutos. Diga <i>cancela</i> pra desistir.\n\n"
    "<b>Comandos</b>\n"
    "/start - boas-vindas\n"
    "/help - esta ajuda\n"
    "/ping - testa a conexão com a IA\n"
    "/roteiro &lt;destino e detalhes&gt; - gera roteiro dia a dia\n"
    "/compras &lt;o que e onde&gt; - guia de onde comprar\n"
    "/seguir &lt;pergunta&gt; - pergunta de follow-up sobre o último /roteiro ou /compras\n"
    "/pesquisa &lt;texto&gt; - busca preço agora, sem criar alerta\n"
    "/list - seus monitoramentos ativos\n"
    "/pause &lt;id&gt; - pausa um monitoramento\n"
    "/resume &lt;id&gt; - retoma\n"
    "/delete &lt;id&gt; - apaga\n"
    "/snooze &lt;id&gt; &lt;horas&gt; - silencia alertas por N horas\n"
    "/congresso_on - resumo semanal de MPs do Congresso (segunda 07:00 BRT)\n"
    "/congresso_off - cancela o resumo semanal\n"
    "/congresso_at H - muda hora do digest de MPs (ex: /congresso_at 8); sem arg = default\n"
    "/congresso_reset - re-dispara o digest da semana no próximo tick\n"
    "/congresso_now - consulta a agenda de MPs da semana agora\n"
    "/trafego_on - resumo diário de trânsito casa→trabalho (seg-sex 07:20 BRT)\n"
    "/trafego_off - cancela o resumo diário\n"
    "/trafego_at HH:MM - muda horário do digest de trânsito; sem arg = default\n"
    "/trafego_reset - re-dispara o digest de hoje no próximo tick\n"
    "/trafego_now casa - tempo agora pro trajeto trabalho→casa (com alternativa)\n"
    "/trafego_now trabalho - tempo agora pro trajeto casa→trabalho (com alternativa)\n"
)


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession) -> None:
    if message.from_user is None:
        return
    tg_id = message.from_user.id
    existing = await session.scalar(select(User).where(User.telegram_id == tg_id))
    if existing is None:
        session.add(
            User(
                telegram_id=tg_id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
            )
        )
        await session.commit()
    await message.answer(WELCOME)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP)
