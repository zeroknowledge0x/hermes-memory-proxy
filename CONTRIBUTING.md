# Contributing to Hermes Memory Proxy

Thanks for your interest! This is a small, focused project: a memory **tier** that sits
between an agent and its LLM. We keep the core pipeline provider-agnostic and minimal —
features belong in the proxy, not baked into a specific model SDK.

## Ways to help

- **Bug reports / feature requests** — open an issue. Tell us your provider, how you run it
  (Docker vs host), and a minimal repro.
- **Provider examples** — got it working with a new OpenAI-compatible endpoint? Add a snippet
  under `examples/`.
- **Code** — see "Good first areas" below.
- **Docs** — README clarity, CONCEPTS, architecture notes.

## Dev setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
docker compose up -d db          # Postgres + pgvector
cp .env.example .env             # set UPSTREAM_BASE_URL + UPSTREAM_API_KEY
psql "$DATABASE_URL" -f migrations/001_init.sql
psql "$DATABASE_URL" -f migrations/002_loops.sql
uvicorn memory_proxy.api.main:build_default_app --factory --host 127.0.0.1 --port 8899
```

Run the test suite:

```bash
pytest -q
```

## Principles

1. **Model-agnostic core.** The pipeline must never `import openai` / `import anthropic`
   directly. Add providers via `providers/` adapters + `PROVIDER_TYPE` config.
2. **One dependency for memory.** Postgres + pgvector only. Don't pull in a second vector DB.
3. **Personal memory ≠ reference docs.** `memories` (per-user facts) and `knowledge`
   (shared static chunks) stay in separate stores and never mix in retrieval.
4. **ADD-only writes.** `add_fact` never updates in place — corrections create new rows with
   `valid_until` expiry. Audit everything in `events`.
5. **Single-user default.** `SINGLE_USER_MODE=true` keeps one canonical brain. Multi-tenant
   must be an explicit opt-in (`SINGLE_USER_MODE=false`).

## Good first areas

- Anthropic adapter parity (streaming, tool calls).
- A reranker stage after pgvector top-k.
- Working / Short memory tiers (in-memory + short-lived Postgres).
- More `examples/` provider configs (Ollama, vLLM, Gemini, local Nous).
- Docker Healthcheck + graceful shutdown hardening.

## PR checklist

- [ ] Tests pass (`pytest -q`).
- [ ] No PII / real user ids / chat ids committed (use `<your-user-id>` placeholders in docs).
- [ ] New env var? Document it in `.env.example` **and** `README.md` config table.
- [ ] New endpoint? Add it to `ARCHITECTURE.md` + README "Self-improvement loops" section.
- [ ] Keep the core provider-agnostic (Principle 1).

## Code style

- `ruff` for lint/format (config in `pyproject.toml`).
- Type hints on public functions.
- Prefer explicit errors over silent fallbacks in the pipeline.

## License

By contributing, you agree your contributions are licensed under MIT (see `LICENSE`).
