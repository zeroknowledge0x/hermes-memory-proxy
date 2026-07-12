#!/usr/bin/env bash
# scripts/backup.sh — daily Postgres dump (plain SQL) of memory_proxy.
# Plain SQL (.sql) is human-readable, greppable, and restorable with `psql`
# (no pg_restore needed). Cron:
#   17 3 * * * /root/memory-proxy/scripts/backup.sh >> /root/memory-proxy/backup/cron.log 2>&1
set -euo pipefail

DB_URL="${DATABASE_URL:-postgresql://proxy:proxy@localhost:5432/memory_proxy}"
BACKUP_DIR="${BACKUP_DIR:-/root/memory-proxy/backup}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
REMOTE="${REMOTE:-}"   # set REMOTE="b2:mybucket/backups" to also upload off-VPS (needs rclone)

mkdir -p "$BACKUP_DIR"
STAMP="$(date +%F-%H%M)"
SQL="$BACKUP_DIR/mp_$STAMP.sql"

echo "[$(date -u +%FT%TZ)] dumping -> $SQL"
pg_dump "$DB_URL" -f "$SQL"

# local retention
find "$BACKUP_DIR" -name 'mp_*.sql' -mtime "+$RETENTION_DAYS" -delete || true

if [ -n "$REMOTE" ]; then
  echo "[$(date -u +%FT%TZ)] uploading -> $REMOTE"
  rclone copy "$SQL" "$REMOTE/" && echo "[$(date -u +%FT%TZ)] uploaded ok"
fi
echo "[$(date -u +%FT%TZ)] done"
