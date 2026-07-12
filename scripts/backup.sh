#!/usr/bin/env bash
# scripts/backup.sh — daily Postgres dump of memory_proxy -> local then rclone to B2/S3.
# Cron: 17 3 * * * /root/memory-proxy/scripts/backup.sh >> /root/memory-proxy/backup/cron.log 2>&1
set -euo pipefail

DB_URL="${DATABASE_URL:-postgresql://proxy:proxy@localhost:5432/memory_proxy}"
BACKUP_DIR="${BACKUP_DIR:-/root/memory-proxy/backup}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
REMOTE="${REMOTE:-b2:mybucket/backups}"   # set REMOTE="" to skip off-VPS upload

mkdir -p "$BACKUP_DIR"
STAMP="$(date +%F-%H%M)"
DUMP="$BACKUP_DIR/mp_$STAMP.dump"

echo "[$(date -u +%FT%TZ)] dumping -> $DUMP"
pg_dump -Fc "$DB_URL" -f "$DUMP"

# local retention
find "$BACKUP_DIR" -name 'mp_*.dump' -mtime "+$RETENTION_DAYS" -delete || true

if [ -n "$REMOTE" ]; then
  echo "[$(date -u +%FT%TZ)] uploading -> $REMOTE"
  rclone copy "$DUMP" "$REMOTE/" && echo "[$(date -u +%FT%TZ)] uploaded ok"
fi
echo "[$(date -u +%FT%TZ)] done"
