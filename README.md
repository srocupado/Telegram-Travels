# Telegram-Travels

Bot do Telegram que funciona como agente pessoal de viagens. Monitora preços de passagens e hotéis, alerta quando cai, gera roteiros dia-a-dia, sugere onde fazer compras no destino, e responde em português natural usando IA.

Roda numa VM micro grátis (Google Cloud `e2-micro`, Oracle AMD `E2.1.Micro` ou similar) — 1 GB RAM já basta.

## Funcionalidades

- **Conversa stateful em português** — você escreve livremente (*"quero ir pra Buenos Aires em julho, até R$ 2000"*); o bot pergunta o que faltar, propõe um resumo e cria o monitoramento depois de confirmar.
- **Alertas de preço** — checagem automática 1x/dia via SerpAPI (Google Flights + Google Hotels). Dispara quando o preço fica abaixo do teto definido ou bate uma nova mínima histórica (≥10% abaixo), com cooldown de 12h e silenciamento manual.
- **Roteiros sob medida** — `/roteiro` gera itinerário dia a dia (Manhã/Tarde/Noite) usando Sonnet 4.6, com streaming ao vivo no chat. Comporta viagens de 30+ dias.
- **Guia de compras** — `/compras` retorna onde encontrar produtos específicos em uma cidade, agrupado por bairro/shopping/mercado.
- **Acesso protegido** — senha única configurável; usuários não autorizados recebem prompt de senha e nada mais.
- **Isolamento por usuário** — cada um vê e gerencia só seus próprios monitoramentos; alertas vão pro chat do dono.
- **Backup diário** — dump SQLite gzipado, retenção de 14 dias.

## Stack

- **Python 3.12** + **aiogram 3** (Telegram long polling)
- **SQLAlchemy 2** async + **aiosqlite** (SQLite com volume Docker)
- **Anthropic SDK** — Claude Haiku 4.5 (parser conversacional, redação de alertas) + Sonnet 4.6 (roteiros e guias longos)
- **SerpAPI** — Google Flights e Google Hotels
- **httpx**, **pydantic-settings**, **python-json-logger**
- Tudo num único container, sem dependências externas além das APIs acima

## Comandos

| Comando | O que faz |
|---|---|
| `/start` | Mensagem de boas-vindas |
| `/help` | Lista os comandos disponíveis |
| `/ping` | Testa a conexão com a Claude API |
| `/roteiro <destino e detalhes>` | Gera roteiro dia a dia (até ~30 dias) |
| `/compras <o que> em <cidade>` | Guia de onde comprar no destino |
| `/search <pedido>` | Consulta preço agora, sem criar alerta |
| `/list` | Lista seus monitoramentos |
| `/pause <id>` | Pausa um monitoramento |
| `/resume <id>` | Retoma |
| `/delete <id>` | Apaga |
| `/snooze <id> <horas>` | Silencia alertas por N horas |

Texto livre (sem `/`) entra no modo conversa, que cria novos monitoramentos.

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

O esquema do banco é criado automaticamente no primeiro boot. Uma micro-migração idempotente também cuida da coluna de autorização quando você atualiza versões.

### Variáveis de ambiente (.env)

| Variável | Descrição | Default |
|---|---|---|
| `BOT_TOKEN` | Token do BotFather | — |
| `ANTHROPIC_API_KEY` | Claude API | — |
| `SERPAPI_KEY` | SerpAPI | — |
| `ACCESS_PASSWORD` | Senha pra liberar acesso a novos usuários | — |
| `DATABASE_PATH` | Caminho do SQLite no container | `/data/travels.db` |
| `LOG_LEVEL` | `DEBUG`/`INFO`/`WARNING` | `INFO` |
| `LOG_JSON` | Logs em JSON estruturado | `true` |
| `SCHEDULER_TICK_SECONDS` | Frequência do loop do scheduler | `3600` |
| `WATCH_CHECK_INTERVAL_HOURS` | Idade mínima pra rechecar um watch | `24` |
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
├── runner.py                # bootstrap: engine, sessionmaker, dispatcher, scheduler
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
│   ├── search.py            # /search
│   ├── manage.py            # /list, /pause, /resume, /delete, /snooze
│   └── watch.py             # texto livre → conversa stateful
├── middlewares/
│   ├── auth.py              # gate de senha
│   └── db.py                # injeta session + deps em todos os handlers
└── services/
    ├── claude_client.py     # construtor do AsyncAnthropic
    ├── serpapi_client.py    # wrapper httpx + extratores de melhor preço
    ├── parser.py            # parser one-shot (uso interno + /search)
    ├── chat.py              # conversa stateful com TTL em memória
    ├── long_form.py         # geração com streaming ao vivo no Telegram
    ├── alerts.py            # regra de disparo + compositor de mensagem
    └── scheduler.py         # loop assíncrono que cheka watches devidos
```

### Modelo de dados

- **`users`** — registro do Telegram + flag de autorização.
- **`watches`** — um monitoramento (passagem ou hotel). Params como JSON pra acomodar os dois tipos.
- **`price_snapshots`** — histórico de preços observados, com payload bruto da SerpAPI.
- **`alerts`** — registro de cada alerta disparado, ligado ao snapshot que motivou.

Schema é mantido via `Base.metadata.create_all` no boot — suficiente enquanto evolui só por adição. Migrations destrutivas exigiriam Alembic.

### Fluxo de um monitoramento

```
Texto livre → AuthMiddleware → DepsMiddleware (sessão SQLA)
            → handle_free_text → chat.chat_turn(Claude Haiku)
            → resposta em <CREATE>{...}</CREATE> quando confirmado
            → grava Watch (status=active)
            → scheduler tick (a cada hora) seleciona watches due
            → SerpAPI fetch → snapshot → should_alert()
            → compose_alert_message(Claude Haiku) → bot.send_message
```

## Custos

Operação típica de uso pessoal/família (5–20 usuários, dezenas de watches):

- **VM Google Cloud `e2-micro`** — gratuita no Always Free Tier (us-east1/us-west1/us-central1).
- **SerpAPI** — começa no free (100 buscas/mês ≈ 3 watches ativos). Plano *Developer* USD 50/mês cobre folgadamente.
- **Anthropic API** — Haiku 4.5 (parser e alertas) ~USD 0,001 por mensagem; Sonnet 4.6 (roteiros) ~USD 0,10–0,18 por roteiro extenso.

## Limites conhecidos

- **Não tem FSM persistente** — sessões de conversa ficam só em RAM (TTL 30 min). Reiniciar o container apaga conversas em andamento (não os monitoramentos).
- **Códigos IATA via IA** — depende do Claude conhecer o aeroporto. Cidades pequenas podem não funcionar; nesse caso, o usuário pode digitar o IATA direto.
- **Schema sem migrations** — mudanças destrutivas na tabela exigem trabalho manual ou adoção de Alembic.
- **Sem testes automatizados** — escala pessoal; quando crescer, vale adicionar pytest + factory_boy.

## Licença

Privado.
