#!/usr/bin/env bash
# backup_to_github.sh — dump memory_proxy DB lalu force-push ke repo backup terpisah.
# Branch `latest` HANYA simpan 1 file (latest.dump) — gak numpuk history.
# Cron: 0 4 * * * /root/memory-proxy/scripts/backup_to_github.sh >> /root/memory-proxy/backup/gh.log 2>&1
set -euo pipefail

DB_URL="${DATABASE_URL:-postgresql://proxy:***@localhost:5432/memory_proxy}"
REPO_URL="${BACKUP_REPO:-https://github.com/zeroknowledge0x/memory-proxy-backup.git}"
WORK="${BACKUP_WORK:-/root/memory-proxy/backup/gh_repo}"
DUMP="/root/memory-proxy/backup/latest.dump"

echo "[$(date -u +%FT%TZ)] dumping -> $DUMP"
pg_dump -Fc "$DB_URL" -f "$DUMP"

rm -rf "$WORK"
if git clone --quiet --branch latest "$REPO_URL" "$WORK" 2>/dev/null; then
  : # branch latest sudah ada
else
  git clone --quiet "$REPO_URL" "$WORK"
  git -C "$WORK" checkout --orphan latest
fi

cp "$DUMP" "$WORK/latest.dump"
git -C "$WORK" add latest.dump
if git -C "$WORK" -c user.name="memory-proxy" -c user.email="mp@localhost" \
     commit -q -m "backup $(date -u +%FT%TZ)"; then
  echo "[$(date -u +%FT%TZ)] committed"
else
  echo "[$(date -u +%FT%TZ)] nothing new (skip push)"
  exit 0
fi
# force-push branch latest aja (gak sentuh main)
git -C "$WORK" push --force origin latest
echo "[$(date -u +%FT%TZ)] pushed to $REPO_URL (branch latest)"
