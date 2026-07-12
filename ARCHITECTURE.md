# ARCHITECTURE — Hermes Memory Proxy

Reference architecture: the `the-fool` / `hermes-loop` "Hermes Brain"
specs (RFC-0001/0002/0006). We take the **pola** (memory taxonomy,
loop types, ranker/compressor, plugin format) and **NOT** the skill
implementations (those are the user's private agents).

## 1. Goal

A drop-in OpenAI-compatible proxy that owns **durable memory** so the agent
remembers across sessions and model swaps. The model is a replaceable
syscall; intelligence lives in state, retrieval, and loops.

## 2. Layers

```
Hermes  ──HTTP/OpenAI──▶  Proxy (127.0.0.1:8899)  ──▶  LLM Provider
                             │
                ┌────────────┼─────────────────┐
          Identity       Memory (pgvector)   Knowledge (pgvector)
          SOUL+USER      facts per user_id    static doc chunks
```

## 3. Memory taxonomy (from RFC-0002)

| Type | Store | Status in this repo |
|------|-------|----------------------|
| Working | in-mem | ⏸ not yet |
| Short | Postgres | ⏸ not yet |
| Conversation | Postgres (`conversations`) | ⚠ schema exists, not wired |
| Semantic | Postgres+pgvector | ✅ `memories` (tier=semantic) |
| Long | Postgres+pgvector | ✅ produced by `/v1/consolidate` (tier=long) |
| Episodic | Postgres+ts | ⏸ not yet |
| Reflection | Postgres | ⏸ not yet |

`memories` has `importance`, `tier`, `consolidated` columns + an append-only
`events` table (audit).

## 4. Components

- **Orchestrator** — single write path; enforces per-user scope.
- **Repository** — pgvector search, add_fact (ADD-only), consolidate, reflect.
- **Embedder** — local multilingual MiniLM (dim 384), async on write.
- **Ranker** — `importance` scoring for retrieval prioritisation.
- **Compressor** — `/v1/consolidate` summarises recent facts → Long (LLM).
- **Event log** — `events` table + `logs/memory.log`.

## 5. Loop types

| Type | Where | Status |
|------|-------|--------|
| Turn-based | proxy per chat (inject + extract) | ✅ |
| Time-based | Hermes cron → `/v1/consolidate`, `/v1/reflect` | ✅ (flat prompt, verified) |
| Proactive | user trigger "catat X" | ⚠ extractor captures |
| Goal-based | the agent (Hermes) | out of proxy scope |

Planning loops are the **agent's** job, not the proxy's. The proxy only
supplies memory to that loop.

## 6. Security

- Auth token + rate limit on the proxy (`security.py`).
- `custom_providers` in Hermes config (NOT the plugin folder) makes the
  provider selectable in `/model`.
- Provider swap = config only; the core pipeline never imports a concrete provider.

## 7. Backup

`pg_dump` daily → local (14d retention) + force-push to a **separate
private repo** (branch `latest`). Survives total VPS loss.
