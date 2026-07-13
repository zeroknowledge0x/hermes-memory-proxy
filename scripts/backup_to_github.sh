#!/usr/bin/env bash
# backup_to_github.sh — dump the memory_proxy DB (plain SQL) then force-push it
# to a separate backup repo. The `latest` branch keeps only one file
# (latest.sql) so history doesn't pile up.
# Cron: 0 4 * * * /root/memory-proxy/scripts/backup_to_github.sh >> /root/memory-proxy/backup/gh.log 2>&1
set -euo pipefail

DB_URL="${DATABASE_URL:-postgresql://proxy:proxy@localhost:5432/memory_proxy}"
REPO_URL="${BACKUP_REPO:-https://github.com/zeroknowledge0x/memory-proxy-backup.git}"
WORK="${BACKUP_WORK:-/root/memory-proxy/backup/gh_repo}"
SQL="/root/memory-proxy/backup/latest.sql"

echo "[$(date -u +%FT%TZ)] dumping -> $SQL"
pg_dump "$DB_URL" -f "$SQL"

rm -rf "$WORK"
if git clone --quiet --branch latest "$REPO_URL" "$WORK" 2>/dev/null; then
  : # latest branch already exists
else
  git clone --quiet "$REPO_URL" "$WORK"
  git -C "$WORK" checkout --orphan latest
fi

cp "$SQL" "$WORK/latest.sql"
git -C "$WORK" add latest.sql
if git -C "$WORK" -c user.name="zeroknowledge0x" -c user.email="184744018+zeroknowledge0x@users.noreply.github.com" \
     commit -q -m "backup $(date -u +%FT%TZ)"; then
  echo "[$(date -u +%FT%TZ)] committed"
else
  echo "[$(date -u +%FT%TZ)] nothing new (skip push)"
  exit 0
fi
# force-push only the latest branch (don't touch main)
git -C "$WORK" push --force origin latest
echo "[$(date -u +%FT%TZ)] pushed to $REPO_URL (branch latest)"
