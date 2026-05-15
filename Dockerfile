# syntax=docker/dockerfile:1.7
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        tini \
        sqlite3 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 bot \
    && mkdir -p /data \
    && chown bot:bot /data

WORKDIR /app

RUN pip install \
        "aiogram~=3.13" \
        "sqlalchemy[asyncio]~=2.0.36" \
        "aiosqlite~=0.20" \
        "pydantic-settings~=2.6" \
        "python-json-logger~=2.0"

COPY --chown=bot:bot . .

USER bot
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "bot"]
