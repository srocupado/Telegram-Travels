# Telegram-Travels

Bot do Telegram que funciona como agente pessoal de viagens. Monitora preços de passagens e hotéis, alerta quando cai, gera roteiros dia-a-dia, sugere onde fazer compras no destino, e responde em português natural usando IA.

Roda numa VM micro grátis (Google Cloud `e2-micro`, Oracle AMD `E2.1.Micro` ou similar) — 1 GB RAM já basta.

## Funcionalidades

- **Conversa stateful em português** — você escreve livremente (*"quero ir pra Buenos Aires em julho, até R$ 2000"*); o bot pergunta o que faltar, propõe um resumo e cria o monitoramento depois de confirmar.
- **Alertas com detalhes completos** — checagem automática via SerpAPI (Google Flights + Google Hotels). Cada alerta inclui **todos os detalhes** do voo (companhia, número, horários, aeroportos, duração, conexões) ou do hotel (estrelas, avaliação, comodidades, check-in/out, ponto de referência), além do **price level do Google** (🟢 baixo / 🟡 normal / 🔴 alto) com faixa típica.
- **Datas flexíveis** — funciona pra passagens E hotéis. Pedidos como *"2 noites entre 8 e 12 de julho"* ou *"voo GRU pra Japão (Narita ou Haneda), 20 dias entre 9/9 e 30/11"* são suportados — o bot testa combinações dentro da janela e devolve a mais barata.
- **Múltiplos aeroportos de destino** — *"Haneda ou Narita"* ou *"Japão"* viram busca em ambos os aeroportos, escolhendo o mais barato.
- **Alerta inteligente** — só dispara no primeiro check se o Google classifica como "low" (ou bate seu teto); evita notificação de preço normal disfarçado de novidade.
- **Back-off adaptativo** — em rotas crônicamente caras (preço "high" em 2 checks seguidos), o bot espaça as buscas pra economizar SerpAPI.
- **Roteiros sob medida** — `/roteiro` gera itinerário dia a dia (Manhã/Tarde/Noite) usando Sonnet 4.6, com **streaming ao vivo** no chat (você vê o texto sendo escrito). Comporta viagens de 30+ dias.
- **Guia de compras** — `/compras` retorna onde encontrar produtos específicos em uma cidade, agrupado por bairro/shopping/mercado.
- **Follow-up** — `/seguir <pergunta>` faz perguntas adicionais sobre a última `/roteiro` ou `/compras` aproveitando o contexto da resposta anterior (até 6 turnos, expira em 30 min).
- **Acesso protegido por senha** — qualquer usuário precisa enviar a senha configurada antes de qualquer comando; uma vez autorizado, fica liberado pra sempre.
- **Isolamento por usuário** — cada um vê e gerencia só seus próprios monitoramentos; alertas vão pro chat do dono.
- **Multi-provedor de IA** — escolha entre Anthropic Claude, OpenAI ou Google Gemini via `.env` (`AI_PROVIDER`). Default é Anthropic; a troca afeta todas as chamadas (parser, chat, alertas, roteiros, compras, seguir, ping). Sem fallback automático: se o provider falhar, o erro é específico.
- **Backup diário** — dump SQLite gzipado, retenção de 14 dias.
- **Robustez** — timeouts curtos nas chamadas da IA, fallback de mensagem em texto puro se o HTML quebrar, validação prévia que pergunta o que falta antes de chamar a SerpAPI, post-processing de datas (datas no passado são automaticamente bumpadas pra próximo ano).

## Stack

- **Python 3.12** + **aiogram 3** (Telegram long polling)
- **SQLAlchemy 2** async + **aiosqlite** (SQLite com volume Docker)
- **Multi-LLM** — Anthropic Claude, OpenAI, Google Gemini. Dois tiers por provider: `fast` (parser/chat/alertas/ping) e `slow` (roteiros/compras/seguir). Defaults: Haiku 4.5 + Sonnet 4.6 / GPT-5-mini + GPT-5 / Gemini 2.5 Flash + 2.5 Pro.
- **SerpAPI** — Google Flights e Google Hotels (incluindo `price_insights`)
- **httpx**, **pydantic-settings**, **python-json-logger**
- Tudo num único container, sem dependências externas além das APIs acima

## Comandos

| Comando | O que faz |
|---|---|
| `/start` | Mensagem de boas-vindas |
| `/help` | Lista os comandos disponíveis |
| `/ping` | Testa a conexão com a IA (mostra provider e modelo ativos) |
| `/roteiro <destino e detalhes>` | Gera roteiro dia a dia (até ~30 dias) |
| `/compras <o que> em <cidade>` | Guia de onde comprar no destino |
| `/seguir <pergunta>` | Follow-up sobre o último `/roteiro` ou `/compras` |
| `/pesquisa <pedido>` | Consulta preço agora, sem criar alerta — retorna detalhes completos do voo/hotel |
| `/list` | Lista seus monitoramentos |
| `/pause <id>` | Pausa um monitoramento |
| `/resume <id>` | Retoma |
| `/delete <id>` | Apaga |
| `/snooze <id> <horas>` | Silencia alertas por N horas |

Texto livre (sem `/`) entra no modo conversa, que cria novos monitoramentos.

### Exemplos de pedidos em texto livre

- *"passagem GRU pra Buenos Aires em 15/07, até R$ 2000"* — datas fixas, com teto
- *"hotel em Lisboa de 8 a 12 de julho"* — datas fixas
- *"2 noites entre 8 e 12 de julho em Buenos Aires"* — janela flexível de hotel
- *"voo de São Paulo pra Japão (Haneda ou Narita), 20 dias entre 9/9 e 30/11"* — janela flexível de voo + multi-aeroporto

## Frequência de checagem

| Tipo de monitoramento | Cadência | Observações |
|---|---|---|
| Passagem ou hotel com datas fixas | A cada `WATCH_CHECK_INTERVAL_HOURS` (default **24h**) | Tick horário; verifica se está "due" |
| Hotel com janela flexível | A cada `WATCH_CHECK_INTERVAL_HOURS` | Testa até 14 combinações de check-in dentro da janela |
| Passagem com janela flexível | **Terça e quinta** (UTC), 1x/dia | Capta atualizações de tarifas semanais; sample de 5 datas × destinos |
| Qualquer watch com 2 checks "high" seguidos | A cada **7 dias** (back-off) | Reseta quando o preço deixar de ser "high" |

Alertas têm cooldown de `ALERT_COOLDOWN_HOURS` (default **12h**) por watch, prorrogado se cair mais de 5% durante o cooldown.

## Pré-requisitos

1. **Conta no Telegram BotFather** — gere um token (`BOT_TOKEN`).
2. **API key Anthropic** — [console.anthropic.com](https://console.anthropic.com) → Settings → API Keys → Create. Recomendado pré-pagar uns USD 5–10.
3. **API key SerpAPI** — [serpapi.com](https://serpapi.com) → signup → Dashboard. Free tier dá 100 buscas/mês; *Developer* a USD 50/mês dá 5 000.
4. **Docker e Docker Compose** instalados na VM.

## Deploy

```bash
git clone git@github.com:srocupado/Telegram-Travels.git
cd Telegram-Travels
cp .env.example .env
nano .env                          # preencha as 4 chaves
docker compose up -d --build
docker compose logs -f bot
```

O esquema do banco é criado automaticamente no primeiro boot. Micro-migrações idempotentes adicionam colunas novas (`users.is_authorized`, `watches.high_streak`) quando você atualiza versões; usuários já existentes são "grandfathered" como autorizados.

### Variáveis de ambiente (.env)

| Variável | Descrição | Default |
|---|---|---|
| `BOT_TOKEN` | Token do BotFather | — |
| `SERPAPI_KEY` | SerpAPI | — |
| `ACCESS_PASSWORD` | Senha pra liberar acesso a novos usuários | — |
| `AI_PROVIDER` | `anthropic`, `openai` ou `gemini` | `anthropic` |
| `ANTHROPIC_API_KEY` | Chave da Anthropic (obrigatória só se `AI_PROVIDER=anthropic`) | — |
| `OPENAI_API_KEY` | Chave da OpenAI (obrigatória só se `AI_PROVIDER=openai`) | — |
| `GEMINI_API_KEY` | Chave do Gemini (obrigatória só se `AI_PROVIDER=gemini`) | — |
| `HAIKU_MODEL` / `SONNET_MODEL` | Modelos Anthropic fast/slow | `claude-haiku-4-5` / `claude-sonnet-4-6` |
| `OPENAI_FAST_MODEL` / `OPENAI_SLOW_MODEL` | Modelos OpenAI fast/slow | `gpt-5-mini` / `gpt-5` |
| `GEMINI_FAST_MODEL` / `GEMINI_SLOW_MODEL` | Modelos Gemini fast/slow | `gemini-2.5-flash` / `gemini-2.5-pro` |
| `DATABASE_PATH` | Caminho do SQLite no container | `/data/travels.db` |
| `LOG_LEVEL` | `DEBUG`/`INFO`/`WARNING` | `INFO` |
| `LOG_JSON` | Logs em JSON estruturado | `true` |
| `SCHEDULER_TICK_SECONDS` | Frequência do loop do scheduler | `3600` |
| `WATCH_CHECK_INTERVAL_HOURS` | Idade mínima pra rechecar watch comum | `24` |
| `ALERT_COOLDOWN_HOURS` | Cooldown entre alertas do mesmo watch | `12` |

## Operação

### Atualizar

```bash
git pull
docker compose up -d --build
```

### Logs

```bash
docker compose logs -f bot          # stream
docker compose logs --tail=100 bot  # últimas 100 linhas
```

### Backup manual

```bash
bash scripts/backup.sh
```

Gera `~/backups/travels/travels-YYYYMMDDTHHMMSSZ.sql.gz`. Restaurar:

```bash
gunzip -c backup.sql.gz | docker compose exec -T bot sqlite3 /data/travels.db
```

### Backup automático (cron)

```cron
0 3 * * * /bin/bash /home/SEU_USER/Telegram-Travels/scripts/backup.sh >> /home/SEU_USER/backups/travels/cron.log 2>&1
```

O script já apaga backups com mais de 14 dias.

## Arquitetura

```
bot/
├── __main__.py              # entrypoint
├── runner.py                # bootstrap: engine, sessionmaker, dispatcher, scheduler, migrações
├── config.py                # Settings via pydantic-settings
├── logging_setup.py         # logger JSON estruturado
├── db/
│   ├── base.py              # declarative Base
│   ├── models.py            # User, Watch, PriceSnapshot, Alert
│   └── session.py           # async engine / sessionmaker
├── handlers/                # routers aiogram, um por área
│   ├── start.py             # /start, /help
│   ├── ping.py              # /ping
│   ├── roteiro.py           # /roteiro
│   ├── compras.py           # /compras
│   ├── followup.py          # /seguir
│   ├── search.py            # /pesquisa (com detalhes completos + price level)
│   ├── manage.py            # /list, /pause, /resume, /delete, /snooze
│   └── watch.py             # texto livre → conversa stateful
├── middlewares/
│   ├── auth.py              # gate de senha
│   └── db.py                # injeta session + deps em todos os handlers
└── services/
    ├── llm/                 # abstração multi-provider
    │   ├── base.py          # LLMClient Protocol + exceções unificadas
    │   ├── factory.py       # make_llm(settings) escolhe a impl
    │   ├── anthropic_impl.py
    │   ├── openai_impl.py
    │   └── gemini_impl.py
    ├── serpapi_client.py    # wrapper httpx + extratores + flex search + price insights + formatadores
    ├── parser.py            # parser one-shot + bump de datas no passado
    ├── chat.py              # conversa stateful (criação de watch)
    ├── long_form.py         # streaming ao vivo de /roteiro e /compras
    ├── long_form_chat.py    # contexto de follow-up pra /seguir
    ├── alerts.py            # regra de disparo (com price_insights) + compositor de mensagem
    └── scheduler.py         # tick com intervalo por watch, back-off adaptativo, agenda Tue/Thu pra flex flight
```

### Modelo de dados

- **`users`** — registro do Telegram + flag `is_authorized`.
- **`watches`** — um monitoramento (passagem ou hotel, datas fixas ou janela flexível). `params` é JSON pra acomodar variações; `high_streak` controla back-off; `snooze_until` controla silenciamento.
- **`price_snapshots`** — histórico de preços observados, com payload bruto da SerpAPI (incluindo `price_insights`).
- **`alerts`** — registro de cada alerta disparado, ligado ao snapshot que motivou.

Schema é mantido via `Base.metadata.create_all` no boot + migrações idempotentes pra colunas novas. Migrations destrutivas exigiriam Alembic.

### Fluxo de um monitoramento

```
Texto livre → AuthMiddleware → DepsMiddleware (sessão SQLA)
            → handle_free_text → chat.chat_turn(Claude Haiku, prompt com {today})
            → resposta em <CREATE>{...}</CREATE> quando confirmado
            → _bump_past_dates(parsed)
            → grava Watch (status=active)
            → scheduler tick (1/hora) seleciona watches due por tipo
              · datas fixas: a cada 24h
              · hotel flex: a cada 24h, testa combinações na janela
              · voo flex: terças e quintas, sample de 5 datas × destinos
              · high_streak ≥ 2: a cada 7 dias
            → SerpAPI fetch → snapshot + price_insights
            → should_alert (considera price_level pra primeiro check)
            → compose_alert_message(Claude Haiku) + format_flight/format_hotel
            → bot.send_message (headline + bloco completo + price level)
              · fallback texto puro se HTML falhar
```

## Custos

Operação típica de uso pessoal/família (5–20 usuários, dezenas de watches):

- **VM Google Cloud `e2-micro`** — gratuita no Always Free Tier (us-east1/us-west1/us-central1).
- **SerpAPI** — começa no free (100 buscas/mês ≈ 1 watch flex ou 3 watches comuns). Plano *Developer* USD 50/mês (5 000 buscas) cobre folgadamente. O back-off adaptativo e a amostragem em watches flex reduzem o consumo em rotas estáveis.
- **Anthropic API** — Haiku 4.5 (parser, alertas, conversa, follow-up) ~USD 0,001 por mensagem; Sonnet 4.6 (roteiros, guias) ~USD 0,10–0,18 por roteiro extenso.

## Decisões deliberadas

- **Voo em milhas (Smiles, Livelo) não é suportado.** Não tem API pública, e scraping autenticado é frágil/viola ToS. Cotação estimada via valor de mercado da milha não captaria promoções relâmpago (Domingo Smiles, queima de Livelo com bônus), então foi descartado.
- **`/roteiro` usa Sonnet 4.6, não Haiku.** Roteiros precisam de raciocínio mais elaborado pra calibrar a duração, conectar dias, e produzir sugestões específicas. Custo extra justificado.
- **Schema sem Alembic.** Enquanto a evolução for só por adição, `create_all` + migrações inline na boot bastam. Vira Alembic quando precisar mudar/remover colunas.
- **Sem cache de SerpAPI.** Cada `/pesquisa` queima 1 busca. Considerado adicionar TTL de 6h, mas não foi necessário ainda.

## Limites conhecidos

- **Não tem FSM persistente** — sessões de conversa e contexto de `/seguir` ficam só em RAM (TTL 30 min). Reiniciar o container apaga conversas em andamento (não os monitoramentos).
- **Códigos IATA via IA** — depende do Claude conhecer o aeroporto. Cidades pequenas podem não funcionar; nesse caso, o usuário pode digitar o IATA direto.
- **Schema sem migrations destrutivas** — mudanças destrutivas exigem trabalho manual ou adoção de Alembic.
- **Sem testes automatizados** — escala pessoal; quando crescer, vale adicionar pytest + factory_boy.
- **Hotéis sem price_insights** — Google Hotels não retorna `price_insights` no mesmo formato; só voos têm a classificação 🟢/🟡/🔴.

## Licença

Privado.
