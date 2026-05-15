#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# shellcheck disable=SC1091
source "$PROJECT_DIR/.env"

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
OUT="${BACKUP_DIR:-$HOME/backups/travels}"
mkdir -p "$OUT"

docker compose -f "$PROJECT_DIR/docker-compose.yml" exec -T db \
    pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB" \
    > "$OUT/travels-$STAMP.dump"

find "$OUT" -name 'travels-*.dump' -mtime +14 -delete

echo "[$(date -u +%FT%TZ)] backup ok: $OUT/travels-$STAMP.dump"
