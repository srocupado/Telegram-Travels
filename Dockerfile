# syntax=docker/dockerfile:1.7
FROM python:3.12-slim-bookworm AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
RUN pip install --prefix=/install \
        "aiogram~=3.13" \
        "sqlalchemy[asyncio]~=2.0.36" \
        "asyncpg~=0.30" \
        "alembic~=1.14" \
        "pydantic-settings~=2.6" \
        "python-json-logger~=2.0"


FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        tini \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 bot

COPY --from=builder /install /usr/local

WORKDIR /app
COPY --chown=bot:bot . .

USER bot
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "bot"]
