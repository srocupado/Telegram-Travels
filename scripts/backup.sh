#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
OUT="${BACKUP_DIR:-$HOME/backups/travels}"
mkdir -p "$OUT"

docker compose -f "$PROJECT_DIR/docker-compose.yml" exec -T bot \
    sqlite3 /data/travels.db .dump \
    | gzip > "$OUT/travels-$STAMP.sql.gz"

find "$OUT" -name 'travels-*.sql.gz' -mtime +14 -delete

echo "[$(date -u +%FT%TZ)] backup ok: $OUT/travels-$STAMP.sql.gz"
