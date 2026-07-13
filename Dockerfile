# Dockerfile — Hermes Memory Proxy engine
FROM python:3.11-slim

# System deps for psycopg/asyncpg + build
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install deps first (better layer caching)
COPY pyproject.toml ./
COPY src ./src
COPY config ./config
RUN pip install --no-cache-dir -e ".[dev]"

# App code
COPY migrations ./migrations
COPY identity ./identity

EXPOSE 8899

# The DB pool + writer start in the FastAPI lifespan handler.
CMD ["uvicorn", "memory_proxy.api.main:build_default_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8899"]
