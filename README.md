# Hermes Memory Proxy

**Model-agnostic second-brain memory layer for [Hermes Agent](https://github.com/NousResearch/hermes-agent).**

Hermes talks OpenAI-compatible to this proxy; the proxy stores memory + knowledge
in Postgres+pgvector, injects context, and forwards to the real LLM provider.
**Swap providers by config only — no code change.** Memory survives model swaps
and session restarts because it lives here, not in the model or in Hermes internals.

> Status: production-grade for single-user / single-machine. Used in production by
> the author. Multi-tenant and a reranker are intentionally out of scope for v1.

---

## What it does

- **Memory**: facts extracted from your conversations, stored per-user in Postgres+pgvector,
  recalled semantically and injected into the next request automatically.
- **Identity**: a structured `SOUL.md` + `USER.md` (template included) injected every turn.
- **Knowledge Base** (optional): separate RAG over static docs — never mixed with personal memory.
- **Self-improvement loops**: a Hermes cron job calls the proxy to consolidate / reflect
  on memory periodically (the "second brain" behaviour).
- **Model-agnostic**: provider (OpenAI / Nous / Anthropic / Gemini / Ollama / vLLM) is
  chosen in config. The core pipeline never imports a concrete provider.

---

## Architecture

```
Hermes  ──HTTP/OpenAI──▶  Proxy (127.0.0.1:8899)  ──▶  LLM Provider (Nous/OpenAI/Anthropic/…)
                             │
                ┌────────────┼─────────────────┐
          Identity       Memory (pgvector)   Knowledge (pgvector)
          SOUL+USER      facts per user_id    static doc chunks
```

Pipeline (9 fixed steps): parse → identity → retrieve memory → retrieve knowledge →
assemble → budget → inject → forward (stream) → async write memory.

---

## Concepts & philosophy

Why does this exist, and when should you use it? See **[CONCEPTS.md](CONCEPTS.md)**.

## Install (drop-in)

### 1. Engine (this repo)

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

# Database (native Postgres 16 + pgvector, or Docker):
docker compose up -d db

cp .env.example .env          # edit .env — see below
python -m memory_proxy.storage.migrations   # or apply migrations/ manually

uvicorn memory_proxy.api.main:build_default_app --factory --host 127.0.0.1 --port 8899
```

### 2. Point Hermes at the proxy

In `~/.hermes/config.yaml`:

```yaml
model:
  default: <your-model>
  provider: custom:memory-proxy
custom_providers:
  - name: Memory Proxy
    provider_key: memory-proxy
    base_url: http://127.0.0.1:8899/v1
    api_mode: openai_chat
    model: ''
```

### 3. Plugin (auto-inject memory into the system prompt)

```bash
# Option A: copy directly (becomes part of Hermes)
cp -r hermes-plugin/memory-proxy ~/.hermes/plugins/model-providers/memory-proxy
# Option B: symlink (auto-sync with this repo)
ln -s "$(pwd)/hermes-plugin/memory-proxy" ~/.hermes/plugins/model-providers/memory-proxy
```
> Hermes location: `~/.hermes/plugins/model-providers/memory-proxy/`

### 4. Skill (tell the agent how to use memory)

```bash
cp -r hermes-skill/memory-proxy ~/.hermes/skills/memory-proxy
# or: ln -s "$(pwd)/hermes-skill/memory-proxy" ~/.hermes/skills/memory-proxy
```
> Hermes location: `~/.hermes/skills/memory-proxy/SKILL.md`

### 5. Enable the plugin + restart the gateway

```yaml
# in ~/.hermes/config.yaml
plugins:
  enabled:
    - memory-proxy
```
Then restart the Hermes gateway manually, and pick **Memory Proxy** in `/model`.

---

## Self-improvement loops (optional)

The proxy exposes two endpoints the agent can call on a schedule:

- `POST /v1/consolidate` — summarise recent facts into a durable profile (LLM).
- `POST /v1/reflect` — score importance of recent facts.

Wire them as Hermes cron jobs (flat prompt, **never** `brain_loop(...)`):

```bash
hermes cron create "every 1h" "POST http://127.0.0.1:8899/v1/consolidate?user=<your-id>" --name loop_memory_consolidate
hermes cron create "every 3h" "POST http://127.0.0.1:8899/v1/reflect?user=<your-id>" --name loop_memory_reflect
```

---

## Install via your agent (zero-touch)

Hand this to any agent (including Hermes itself) and it will install the whole
thing unattended — full steps in **[FOR_AGENT.md](FOR_AGENT.md)**:

> Clone `https://github.com/zeroknowledge0x/hermes-memory-proxy` and follow
> `FOR_AGENT.md` exactly: install the engine, start Postgres+pgvector, configure
> `.env`, run the proxy on `127.0.0.1:8899`, wire it into Hermes via
> `custom_providers`, copy the plugin + skill, then verify memory works.
> Report status when done.

Copy-paste prompt you can send your agent:

```
Install Hermes Memory Proxy from https://github.com/zeroknowledge0x/hermes-memory-proxy.
Read FOR_AGENT.md in that repo and execute every step in order.
Use a flat, direct report style. When finished, confirm the proxy answers
"what is my name?" from memory after you tell it your name once.
```

---

## Backup

Backups are **plain SQL** (`.sql`) — human-readable, greppable, and restorable
with `psql` (no `pg_restore` needed).

- `scripts/backup.sh` dumps the DB locally (14-day retention).
- `scripts/backup_to_github.sh` force-pushes the dump to a **separate private repo**
  (branch `latest`) so memory survives a total VPS loss. Restore with:
  ```bash
  psql "$DATABASE_URL" -f latest.sql
  ```

---

## Configure (`.env`)

| Var | Meaning |
|-----|----------|
| `DATABASE_URL` | Postgres connection string |
| `UPSTREAM_BASE_URL` | **Real provider base URL, MUST include `/v1`** (e.g. `https://inference-api.nousresearch.com/v1`) |
| `UPSTREAM_API_KEY` | Real provider API key — API-key mode |
| `NOUS_AUTH_FILE` | Path to a Nous OAuth JSON — OAuth mode |
| `PROVIDER_TYPE` | `openai` or `anthropic` |
| `EMBEDDING_MODEL` | local multilingual model (default: `paraphrase-multilingual-MiniLM-L12-v2`, dim 384) |
| `EXTRACTION_ENABLED` | enable automatic fact extraction |
| `EXTRACTION_MODEL` | model used for extraction/consolidation |

## License

MIT — see [LICENSE](LICENSE).
