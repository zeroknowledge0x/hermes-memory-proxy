# Changelog — Hermes Memory Proxy

All notable changes to this project are documented here. The format is based on
keeping a simple, dated log of features and fixes.

## [Unreleased]

### Added
- `POST /v1/memory` — write a fact directly without an LLM forward (returns
  `{status:ok,id}` or `{status:duplicate}`). Useful for programmatic memory and
  for testing the pipeline without a provider key.
- `GET /v1/memory?q=` — query-aware semantic retrieval (the Hermes plugin sends
  the latest user message as `q` so retrieval is contextual, not a fixed probe).
- `POST /v1/admin/dedupe` — one-shot cleanup of exact-text duplicates and stale
  consolidated profiles.
- GitHub Actions CI: `docker compose build` + a full write→recall smoke test
  (no API key required) so `docker compose up` is proven end-to-end on every push.
- `docker-compose.yml` full stack (Postgres+pgvector + proxy) and a
  `Dockerfile` based on `python:3.11-slim`.

### Changed
- `fastembed` is now a core dependency (the proxy needs local embeddings to run).
- `add_fact` now ensures the user row exists before insert (fixes an FK
  violation on a fresh database).
- Single-user mode is the default (`SINGLE_USER_MODE=true`); the canonical user
  UUID is derived deterministically so memory never splits across ids.

### Fixed (mini-training quality pass, 2026-07-13)
- Consolidation cron no longer writes near-identical profiles (skips near-dups,
  expires old ones, keep 1); frequency reduced from 60m to 6h.
- Exact-text dedupe on insert; importance now actually weights retrieval ranking.
- Stream path buffers the SSE so the fact extractor receives the assistant message.

## [0.1.0] — 2026-07-11

### Added
- Initial MVP: OpenAI-compatible proxy in front of any LLM provider, with
  Postgres+pgvector memory storage, multilingual local embeddings, identity
  injection (SOUL/USER), token budgeting, and async fact extraction (ADD-only).
- Multi-provider support (OpenAI / OpenRouter / Anthropic / Ollama / vLLM /
  LM Studio) via a model-agnostic adapter layer.
- Hermes plugin + skill that auto-inject memory and a retrieve→plan→execute→
  review behavior loop into every chat.
- Backup script (`scripts/backup.sh`) with pg_dump + off-VPS upload.
