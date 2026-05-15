# Telegram-Travels

Bot do Telegram para viagens. Stack: Python 3.12 + aiogram 3 + Postgres 16, empacotado em Docker Compose. Modo long polling (sem porta exposta).

## Deploy rápido (na VM Oracle Free Tier)

```bash
git clone git@github.com:srocupado/Telegram-Travels.git
cd Telegram-Travels
cp .env.example .env && nano .env
docker compose build
docker compose up -d db
docker compose run --rm bot alembic upgrade head
docker compose up -d bot
docker compose logs -f bot
```

Detalhes completos no plano em `/root/.claude/plans/` (passo a passo desde criar a VM até backup automático).

## Stack
- aiogram 3 (Telegram)
- SQLAlchemy 2 async + asyncpg (Postgres)
- Alembic (migrações)
- pydantic-settings (config via `.env`)

## Atualizar o bot

```bash
git pull
docker compose build bot
docker compose run --rm bot alembic upgrade head   # só se mexeu em models
docker compose up -d bot
```
