# Telegram-Travels

Bot do Telegram para viagens. Stack: Python 3.12 + aiogram 3 + SQLite, empacotado em Docker. Modo long polling (sem porta exposta).

Pensado pra rodar numa VM micro grátis (Google Cloud `e2-micro`, Oracle AMD `E2.1.Micro`, ou similar) — 1 GB RAM já basta.

## Deploy rápido

```bash
git clone git@github.com:srocupado/Telegram-Travels.git
cd Telegram-Travels
cp .env.example .env && nano .env   # preencha BOT_TOKEN
docker compose up -d --build
docker compose logs -f bot
```

Esquema do banco é criado automaticamente na primeira execução (`Base.metadata.create_all`).

## Stack
- aiogram 3 (Telegram)
- SQLAlchemy 2 async + aiosqlite (SQLite)
- pydantic-settings (config via `.env`)

## Atualizar

```bash
git pull
docker compose up -d --build
```

## Backup

```bash
bash scripts/backup.sh
```

Gera `~/backups/travels/travels-YYYYMMDDTHHMMSSZ.sql.gz`. Restaurar:

```bash
gunzip -c backup.sql.gz | docker compose exec -T bot sqlite3 /data/travels.db
```
