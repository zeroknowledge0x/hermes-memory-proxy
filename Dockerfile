# Dockerfile — Hermes Memory Proxy engine
FROM python:3.11-slim

# System deps for psycopg/asyncpg + build + wait-for-db
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl postgresql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install deps first (better layer caching)
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -e ".[dev]"

# App code (config package is inside src/memory_proxy/config)
COPY migrations ./migrations
COPY identity ./identity
# Wait for Postgres before starting (used by docker-compose healthcheck flow)
COPY scripts/wait_for_db.sh /usr/local/bin/wait_for_db.sh
RUN chmod +x /usr/local/bin/wait_for_db.sh

EXPOSE 8899

# The DB pool + writer start in the FastAPI lifespan handler.
# wait_for_db.sh blocks until the db service accepts connections.
CMD ["sh", "-c", "wait_for_db.sh && uvicorn memory_proxy.api.main:build_default_app --factory --host 0.0.0.0 --port 8899"]
