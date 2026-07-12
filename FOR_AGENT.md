# FOR_AGENT.md — self-install guide for an AI agent

If you are an agent tasked with installing **Hermes Memory Proxy**, follow this
exact sequence. Do NOT improvise config paths. Verify each step before the next.

## Prerequisites
- Python 3.10+, `pip`, `psql` (Postgres 16 + pgvector) or Docker.
- A running Postgres (native or `docker compose up -d db`).
- Hermes Agent installed; write access to `~/.hermes/`.

## Steps

### 1. Clone + install engine
```bash
git clone <this-repo> hermes-memory-proxy && cd hermes-memory-proxy
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Database
```bash
docker compose up -d db        # OR: native Postgres 16 + pgvector 0.6+
psql "$DATABASE_URL" -f src/memory_proxy/storage/migrations/001_init.sql
psql "$DATABASE_URL" -f src/memory_proxy/storage/migrations/002_loops.sql
```

### 3. Configure
```bash
cp .env.example .env
# edit .env: DATABASE_URL, UPSTREAM_BASE_URL (MUST include /v1),
#   UPSTREAM_API_KEY or NOUS_AUTH_FILE, PROVIDER_TYPE, EXTRACTION_*
```

### 4. Run the proxy
```bash
uvicorn memory_proxy.api.main:build_default_app --factory --host 127.0.0.1 --port 8899
# verify: curl http://127.0.0.1:8899/health  -> {"status":"ok"}
```

### 5. Wire Hermes (edit ~/.hermes/config.yaml — use `hermes config set` or a python yaml edit, NOT a raw overwrite)
```yaml
model:
  default: <model>
  provider: custom:memory-proxy
custom_providers:
  - name: Memory Proxy
    provider_key: memory-proxy
    base_url: http://127.0.0.1:8899/v1
    api_mode: openai_chat
    model: ''
```

### 6. Plugin + Skill
```bash
cp -r hermes-plugin/memory-proxy ~/.hermes/plugins/model-providers/memory-proxy
cp -r hermes-skill/memory-proxy ~/.hermes/skills/memory-proxy
```
Then add to `~/.hermes/config.yaml`:
```yaml
plugins:
  enabled:
    - memory-proxy
```

### 7. Restart the Hermes gateway manually (do NOT auto-restart without the user's say-so)
```bash
hermes gateway restart
```

### 8. Verify
- Open `/model` in Hermes → pick **Memory Proxy**.
- Send a fact: "my name is X, I study Y".
- Ask back: "what is my name?" → should answer from memory.
- Check DB: `SELECT content FROM memories ORDER BY created_at DESC LIMIT 5;`

## Optional: self-improvement loops
```bash
hermes cron create "every 1h" "POST http://127.0.0.1:8899/v1/consolidate?user=<id>" --name loop_memory_consolidate
hermes cron create "every 3h" "POST http://127.0.0.1:8899/v1/reflect?user=<id>" --name loop_memory_reflect
```
> Use a FLAT prompt. Never call `brain_loop(...)` inside a cron prompt.

## Backup
```bash
bash scripts/backup.sh                 # local, 14-day retention
bash scripts/backup_to_github.sh       # force-push dump to a separate private repo (branch latest)
```
