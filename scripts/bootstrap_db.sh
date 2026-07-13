#!/usr/bin/env bash
# scripts/bootstrap_db.sh — one-shot DB bootstrap for Memory Proxy.
#
# Applies every migration in order, creates the `proxy` role if missing, and
# grants the sequence privileges the proxy needs (events_id_seq, etc.) so
# endpoints like /v1/consolidate and /v1/reflect don't fail with
# "permission denied for sequence".
#
# Usage (apply migrations only, role already exists):
#   DATABASE_URL=postgresql://proxy:proxy@127.0.0.1:5432/memory_proxy \
#     bash scripts/bootstrap_db.sh
#
# Usage (fresh DB — also create the role + grant):
#   DB_ADMIN_URL=postgresql://postgres@127.0.0.1:5432/memory_proxy \
#   DB_USER=proxy DB_PASSWORD=proxy \
#     bash scripts/bootstrap_db.sh
set -euo pipefail

DB_URL="${DATABASE_URL:?DATABASE_URL is required (e.g. postgresql://proxy:proxy@127.0.0.1:5432/memory_proxy)}"
ADMIN_URL="${DB_ADMIN_URL:-$DB_URL}"
DB_USER="${DB_USER:-proxy}"
DB_PASSWORD="${DB_PASSWORD:-proxy}"
MIG_DIR="${MIG_DIR:-src/memory_proxy/storage/migrations}"

echo "[$(date -u +%FT%TZ)] applying migrations from $MIG_DIR"
for f in "$MIG_DIR"/*.sql; do
  echo "  -> $f"
  psql "$DB_URL" -v ON_ERROR_STOP=1 -f "$f"
done

# If an admin URL differs from the app URL, ensure the proxy role exists + owns sequences.
if [ "${DB_ADMIN_URL:-}" != "" ]; then
  echo "[$(date -u +%FT%TZ)] granting role + sequence privileges via admin"
  psql "$ADMIN_URL" -v ON_ERROR_STOP=1 <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$DB_USER') THEN
    CREATE ROLE $DB_USER LOGIN PASSWORD '$DB_PASSWORD';
  END IF;
END \$\$;
GRANT USAGE, SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO $DB_USER;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO $DB_USER;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO $DB_USER;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO $DB_USER;
SQL
  echo "[$(date -u +%FT%TZ)] role + sequence grants applied"
else
  echo "[$(date -u +%FT%TZ)] skipping role grant (no DB_ADMIN_URL set; assuming role + grants already exist)"
fi

echo "[$(date -u +%FT%TZ)] bootstrap done"
