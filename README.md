# Hermes Memory Proxy

**A model-agnostic, self-hostable memory layer that gives any LLM agent long-term memory — swap the model, keep the brain.**

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Postgres + pgvector](https://img.shields.io/badge/store-Postgres%20%2B%20pgvector-336791.svg)](https://github.com/pgvector/pgvector)
[![OpenAI-compatible](https://img.shields.io/badge/API-OpenAI--compatible-412991.svg)](https://platform.openai.com/docs/api-reference/chat)
[![Docker build](https://github.com/zeroknowledge0x/hermes-memory-proxy/actions/workflows/docker-smoke.yml/badge.svg)](https://github.com/zeroknowledge0x/hermes-memory-proxy/actions/workflows/docker-smoke.yml)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

Your agent sits behind an OpenAI-compatible endpoint. This proxy transparently
**remembers facts from every conversation**, stores them in Postgres + pgvector,
and **injects the relevant ones back** into the next request — then forwards to
the real LLM provider. The model becomes a replaceable syscall; the memory is
yours and it survives model swaps, provider outages, and session restarts.

> Built for [Hermes Agent](https://github.com/NousResearch/hermes-agent), but works with
> **anything that speaks OpenAI Chat Completions** — point your `base_url` at the proxy.

---

## Why this exists

LLMs are stateless — they forget the moment a session ends. The two usual fixes both hurt:

| Approach | Problem |
|----------|---------|
| Stuff everything into the system prompt | Blows the context window, no retrieval, no forgetting |
| Generic RAG over a doc folder | Mixes *your facts* with *reference docs*, no per-user recall, no self-improvement |

Hermes Memory Proxy is a dedicated **memory tier** between the agent and the model.
Intelligence lives in **state + retrieval + loops**, not in the weights.

```
┌────────┐   OpenAI Chat    ┌──────────────────────┐   forward    ┌─────────────┐
│ Agent  │ ───────────────▶ │  Memory Proxy :8899  │ ───────────▶ │ LLM Provider│
│(Hermes)│ ◀─── stream ──── │  memory + identity   │ ◀── stream ─ │ (swappable) │
└────────┘                  └──────────┬───────────┘              └─────────────┘
                                       │ async write
                              ┌────────▼─────────┐
                              │ Postgres+pgvector│
                              │ memory + knowledge│
                              └──────────────────┘
```

---

## Features

- 🧠 **Automatic memory** — facts extracted from conversations, embedded locally, recalled semantically, injected automatically. No manual "save" calls.
- 🔌 **Model-agnostic** — OpenAI / Nous / Anthropic / Gemini / Ollama / vLLM by config only. The core never imports a concrete provider.
- 🔍 **Two separate vector stores** — personal **Memory** (per user) vs static **Knowledge** (shared docs). Never mixed — the #1 RAG mistake, avoided by design.
- ♻️ **Self-improvement loops** — `consolidate` (compress facts → durable profile) and `reflect` (score importance) run on a schedule.
- 🌍 **Multilingual** — default embedding handles many languages (incl. Bahasa Indonesia) out of the box.
- 📦 **One dependency** — just Postgres + pgvector. No extra vector DB, no vendor lock-in.
- 🔁 **Memory survives model swaps** — swap `gpt-4o` for `claude` or a local model; your agent keeps its memories.

---

## How it compares

| | Hermes Memory Proxy | Prompt-stuffing | mem0 / LangChain memory |
|---|---|---|---|
| Transparent proxy (no app code change) | ✅ | ❌ | ❌ (library calls in your code) |
| Model-agnostic by config | ✅ | ✅ | ⚠️ varies |
| Personal memory vs reference docs isolated | ✅ | ❌ | ⚠️ often mixed |
| Self-hosted, single dependency | ✅ pgvector | — | ⚠️ often needs a managed store |
| Self-improvement loops (consolidate/reflect) | ✅ | ❌ | ⚠️ partial |
| Survives model / provider swap | ✅ | ❌ | ⚠️ depends |

---

## Quickstart (Docker — full stack, one command)

```bash
git clone https://github.com/zeroknowledge0x/hermes-memory-proxy
cd hermes-memory-proxy
cp .env.example .env      # edit UPSTREAM_BASE_URL + UPSTREAM_API_KEY
docker compose up -d      # starts Postgres+pgvector AND the proxy on :8899

curl http://127.0.0.1:8899/health      # {"status":"ok"}
```

That's it — the proxy is live at `http://127.0.0.1:8899/v1` (OpenAI-compatible).

### Try it (30-second smoke test)

```bash
# tell it a fact
curl -s http://127.0.0.1:8899/v1/chat/completions -H 'content-type: application/json' -d '{
  "model":"gpt-4o-mini",
  "messages":[{"role":"user","content":"my name is Sam and I love hiking"}]
}' >/dev/null

# ask it back in a NEW request — memory is injected automatically
curl -s http://127.0.0.1:8899/v1/chat/completions -H 'content-type: application/json' -d '{
  "model":"gpt-4o-mini",
  "messages":[{"role":"user","content":"what is my name and what do I like?"}]
}'
# → the model answers "Sam" + "hiking" from memory
```

---

## Manual install (no Docker)

<details>
<summary>Run the engine directly on the host</summary>

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

# Postgres 16 + pgvector — via Docker for just the DB:
docker compose up -d db
# ...or a native install; then apply migrations:
psql "$DATABASE_URL" -f migrations/001_init.sql
psql "$DATABASE_URL" -f migrations/002_loops.sql

cp .env.example .env          # edit .env
uvicorn memory_proxy.api.main:build_default_app --factory --host 127.0.0.1 --port 8899
```
</details>

---

## Wire it into Hermes Agent

<details>
<summary>config.yaml + plugin + skill</summary>

**1. Point Hermes at the proxy** (`~/.hermes/config.yaml`):

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

**2. Plugin** (auto-inject memory into the system prompt):

```bash
cp -r hermes-plugin/memory-proxy ~/.hermes/plugins/model-providers/memory-proxy
```

**3. Skill** (tell the agent how to use memory):

```bash
cp -r hermes-skill/memory-proxy ~/.hermes/skills/memory-proxy
```

**4. Enable + restart the gateway:**

```yaml
plugins:
  enabled:
    - memory-proxy
```

See [`examples/`](examples/) for ready-to-copy config snippets.
</details>

---

## Run as a service (auto-start + auto-restart)

```bash
sudo cp scripts/memory-proxy.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now memory-proxy
# logs: journalctl -u memory-proxy
```

Loads `.env`, starts after Postgres, and **restarts automatically on crash or reboot**.

---

## Self-improvement loops (optional)

The proxy exposes endpoints you can call on a schedule:

- `POST /v1/consolidate` — summarise recent facts into a durable profile (LLM).
- `POST /v1/reflect` — score importance of recent facts (better retrieval ranking).
- `POST /v1/admin/dedupe` — expire exact-duplicate facts + keep one consolidated profile.

Wire them as Hermes cron jobs (flat prompt — **never** `brain_loop(...)`):

```bash
hermes cron create "every 6h" "POST http://127.0.0.1:8899/v1/consolidate?user=<your-id>" --name loop_memory_consolidate
hermes cron create "every 3h" "POST http://127.0.0.1:8899/v1/reflect?user=<your-id>"     --name loop_memory_reflect
```

---

## Single-user vs multi-user

By default the proxy runs in **single-user mode** (`SINGLE_USER_MODE=true`): every
request maps to one canonical brain, so memory never fragments across id formats.
For true multi-tenant isolation set `SINGLE_USER_MODE=false` — each opaque `user`
value is hashed to a stable per-user UUID.

---

## Backup

Backups are **plain SQL** (`.sql`) — human-readable, greppable, restorable with `psql`:

- `scripts/backup.sh` — local dump (14-day retention).
- `scripts/backup_to_github.sh` — force-push the dump to a **separate private repo**
  (branch `latest`) so memory survives a total host loss. Restore:
  ```bash
  psql "$DATABASE_URL" -f latest.sql
  ```

---

## Configure (`.env`)

| Var | Meaning |
|-----|---------|
| `DATABASE_URL` | Postgres connection string |
| `UPSTREAM_BASE_URL` | **Real provider base URL, MUST include `/v1`** (e.g. `https://api.openai.com/v1`) |
| `UPSTREAM_API_KEY` | Real provider API key (API-key mode) |
| `NOUS_AUTH_FILE` | Path to a Nous OAuth JSON (OAuth mode) |
| `PROVIDER_TYPE` | `openai` or `anthropic` |
| `EMBEDDING_MODEL` | local multilingual model (default: `paraphrase-multilingual-MiniLM-L12-v2`, dim 384) |
| `EXTRACTION_ENABLED` | enable automatic fact extraction |
| `EXTRACTION_MODEL` | model used for extraction/consolidation |
| `SINGLE_USER_MODE` | `true` (default) = one brain; `false` = per-user isolation |
| `DEFAULT_USER_ID` | canonical user UUID in single-user mode |

Full walkthrough: [CONCEPTS.md](CONCEPTS.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [FOR_AGENT.md](FOR_AGENT.md)

---

## Install via your agent (zero-touch)

Hand this prompt to any capable agent (including Hermes itself):

```
Install Hermes Memory Proxy from https://github.com/zeroknowledge0x/hermes-memory-proxy.
Read FOR_AGENT.md in that repo and execute every step in order.
When finished, confirm the proxy answers "what is my name?" from memory
after you tell it your name once.
```

---

## Contributing

PRs and issues welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). Good first areas:
Anthropic adapter parity, a reranker, Working/Short memory tiers, and more provider examples.

## License

MIT — see [LICENSE](LICENSE).
