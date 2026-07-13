#!/bin/sh
# scripts/wait_for_db.sh — block until Postgres is ready (used in container start).
# Reads DATABASE_URL (or PGHOST/PGPORT) and polls pg_isready.
set -e

# Parse DATABASE_URL if present
if [ -n "${DATABASE_URL:-}" ]; then
  # postgresql://user:pass@host:port/db
  HOST=$(echo "$DATABASE_URL" | sed -E 's#.*@([^:/]+).*#\1#')
  PORT=$(echo "$DATABASE_URL" | sed -E 's#.*:([0-9]+)/.*#\1#')
fi
HOST="${HOST:-${PGHOST:-db}}"
PORT="${PORT:-${PGPORT:-5432}}"

echo "wait_for_db: waiting for $HOST:$PORT ..."
for i in $(seq 1 30); do
  if pg_isready -h "$HOST" -p "$PORT" >/dev/null 2>&1; then
    echo "wait_for_db: ready after ${i}s"
    exit 0
  fi
  sleep 1
done
echo "wait_for_db: TIMEOUT waiting for database" >&2
exit 1
