# DECISIONS — Hermes Memory Proxy

> Log of all design decisions that are **LOCKED** before implementation, along with evidence/rationale.
> Format: each decision = context → decision → rationale/evidence → consequence. Future changes must be added as new entries; never delete old ones.

---

## D-001 — Transparent proxy architecture FEASIBLE

- **Decision:** Proceed. No fatal blockers.
- **Evidence (from Hermes source `/usr/local/lib/hermes-agent/`):**
  - Custom `base_url` is supported → `~/.hermes/config.yaml:4` already uses `base_url: https://inference-api.nousresearch.com/v1`.
  - Client = `AsyncOpenAI` SDK → `agent/auxiliary_client.py:4377` (`return AsyncOpenAI(**async_kwargs)`).
  - The `custom` provider plugin for OpenAI-compatible/Ollama/local endpoints → `plugins/model-providers/custom/plugin.yaml`.
- **Consequence:** STOP-condition #1 in the initial plan (base_url not possible) is REFUTED. Safe to proceed.

## D-002 — Canonical wire-format = OpenAI Chat Completions

- **Decision:** The core proxy speaks **one** canonical wire-format: OpenAI Chat Completions. Adapters translate to other providers.
- **Rationale:** Hermes defaults to the `AsyncOpenAI` SDK. The SDK validates/parses the response → the format must be perfectly valid, not "almost right".
- **Consequence:** Malformed responses are rejected by the SDK (not Hermes). Streaming must be SSE `data: {...}` + `data: [DONE]` bit-exact.

## D-003 — OpenAI-compatible adapter built FIRST (not Anthropic)

- **Decision:** Reverse the order from initial plan §10. OpenAI-compat adapter is #1, Anthropic is phase 2.
- **Rationale:** Hermes's default path = OpenAI SDK → base_url. Building Anthropic first would target a path unused in v1.

## D-004 — Hermes internal memory DISABLED

- **Decision:** Set `memory.memory_enabled: false` and `memory.user_profile_enabled: false` in `~/.hermes/config.yaml`.
- **Evidence:** `agent/context_breakdown.py:72` checks the `_memory_enabled` flag before injecting the block into the system prompt; `agent_init.py:1336-1347` gates memory in config. Current config `memory_enabled: true` (active) → MUST be disabled.
- **Rationale:** Otherwise, local Hermes memory (MEMORY.md/USER.md) + proxy memory = DOUBLE injection.
- **Consequence:** All dynamic memory comes from the proxy. SOUL.md/USER.md for identity are still loaded by the proxy (not Hermes).

## D-005 — Vector DB = PostgreSQL + pgvector

- **Decision:** pgvector, not Qdrant/Weaviate/Chroma/Milvus.
- **Rationale:** Already using Postgres for relational data → zero additional services; single-door backup (`pg_dump` relational+vector); OSS, no lock-in; HNSW is mature; scaling to thousands–tens of thousands of vectors is lightweight.
- **Consequence:** Switch to Qdrant only if data exceeds hundreds of thousands–millions of vectors + needs quantization/multitenancy. (Research: `/root/laporan-vector-db-memory-proxy.md`)

## D-006 — Embedding = bge-small-en-v1.5 (dim 384) via fastembed

- **Decision:** `bge-small-en-v1.5`, dimension **384**, library **fastembed (ONNX)**.
- **Rationale:** Best retrieval in the lightweight class (MTEB retrieval 46.1), safe on a 1–2GB VPS, 384-dim (small index), fastembed avoids PyTorch ~2GB. Local = model-agnostic (embeddings don't depend on the LLM provider).
- **Consequence:** Schema `VECTOR(384)` LOCKED. Changing the embedding model = re-embed all data. Store `embedding_model` in DB metadata. Upgrade to bge-base (768) only if the VPS has 2GB to spare. (Research: `/root/embed_research/LAPORAN_EMBEDDING_RAG.md`)

## D-007 — Fact Extraction = lightweight hybrid, separate small model, async, ADD-only

- **Decision:**
  - Use a **separate small model** (local Ollama 7B / gpt-4o-mini), NOT the main model.
  - Hybrid flow: heuristic gate → small LLM extraction → normalization → dedupe (cosine) → ADD-only store.
  - Timing: per-turn async fire-and-forget + end-of-session consolidation.
  - Strict output: list of short facts, `response_format=json_object` + parser fallback.
- **Rationale:** Running extraction on the main model = 2x cost + latency. A separate small model is cheap. ADD-only (borrowing from mem0) avoids the fragile part (LLM choosing UPDATE/DELETE). Validity window (borrowing from Zep) lets facts change without deleting history.
- **Consequence:** Extraction MUST be optional & configurable (can be disabled; the proxy still runs as passthrough+retrieval). (Research: `/root/riset-fact-extraction.md`)

## D-008 — Token Budgeter uses estimation, not an accurate tokenizer

- **Decision:** Estimate `len(text)//3` + a large `reserved_pct` (0.25–0.3). Per-provider accurate tokenizer is deferred.
- **Rationale:** An accurate tokenizer = heavy dependency (tiktoken/SentencePiece) + network call (Anthropic count_tokens) in the hot path. Budgeting is coarse (drops turn history), doesn't need ±1 token precision. The model-agnostic requirement makes a single tokenizer inaccurate for all.
- **Consequence:** If metrics show budgeting frequently misses → revisit in the hardening phase.

## D-009 — test_passthrough: what's identical = PAYLOAD, not response content

- **Decision:** The acceptance criterion "identical result" is redefined as a **byte-level payload** forwarded to the provider being identical (with/without injection off), not the response content.
- **Rationale:** LLMs are non-deterministic; same request ≠ same output (except temp=0+seed, and not all providers honor the seed).

## D-010 — Memory writer = single-writer queue; test awaits, prod eventual consistency

- **Decision:** A single async worker sequentially consumes the queue. In test mode `await` write completion; in prod accept EXPLICIT eventual consistency (documented).
- **Rationale:** Non-blocking async writer → the acceptance "turn-1 facts appear at turn 2" can be flaky if the write hasn't committed. Single-writer avoids read/write races.

## D-011 — Backup = daily pg_dump off-VPS; git = code only

- **Decision:** `pg_dump -Fc` daily via cron → upload to Backblaze B2/S3 (rclone). WAL/PITR is overkill for v1. GitHub holds ONLY code/config/migration/docker.
- **Consequence:** `.gitignore` must cover: `.env`, `*.dump`, `backup/`, data volumes. Monthly restore drills.

## D-012 — Provider v1 = OpenAI-compat only

- **Decision:** v1 supports OpenAI-compat (openai, openrouter, ollama, vLLM, LM Studio, custom). Anthropic & Gemini = phase 2. Codex/Responses API = unsupported.
- **Evidence:** `providers/__init__.py` plugin registry; Anthropic uses `agent/anthropic_adapter.py` (different wire), Codex uses `agent/codex_runtime.py` (entirely different).

## D-013 — Identity single-user hardcoded for v1

- **Rationale:** v1 = single hardcoded `user_id` + `session_id` per process (an explicit known limitation, not a hidden bug).
- **Rationale:** Need to verify whether Hermes sends user/session identity (Phase 0 point 6). Until verified, default to single-user.
- **Status:** VERIFY during implementation — check whether the Hermes request carries a `user` field / identity header.

## D-014 — Embedding model = paraphrase-multilingual-MiniLM-L12-v2 (REVISION of D-006)

- **Decision:** Change from `bge-small-en-v1.5` to `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`. Dimension STAYS 384 (schema unchanged).
- **Rationale:** bge-small is English-only. User communicates in Indonesian. Cosine evidence (measured directly, query "what is the user's favorite drink?"):
  - bge-small-en: kopi ranking #3 (0.532) ❌
  - paraphrase-multilingual-MiniLM: kopi ranking #1 (0.568), clear separation vs #2 (0.293) ✅
  - multilingual-e5-large (1024, 2.24GB): kopi #1 but thin separation (0.859 vs 0.837) + too large for the VPS
- **Consequence:** dim 384 stays → schema safe. Model ~0.22GB (lightweight). The fastembed mean-pooling warning is benign.
- **Swap-ability:** Model changes remain supported forever — set `EMBEDDING_MODEL` in config, then run `scripts/reembed.py` to re-encode old data. The per-row `embedding_model` column tracks which model was used. If the new model has a different dimension, change `EMBEDDING_DIM` + run the `ALTER ... VECTOR(n)` migration first.

## D-015 — Verification: Hermes does NOT send user/session identity in the request

- **Decision:** Confirms D-013 — v1 single hardcoded `user_id` + `session_id` is correct. Hermes does not send a `user` field or identity header in the OpenAI Chat Completions request.
- **Evidence:** Source `agent/transports/chat_completions.py:494` `_build_kwargs_from_profile()` — no `api_kwargs["user"]`, no identity header. `session_id` (params:276,572,582) is only passed to `profile.build_extra_body()` / `build_api_kwargs_extras()` → goes into `extra_body` ONLY, and only if the provider profile emits it (e.g. OpenRouter). For the Nous profile (active provider), session_id does not become a user identity on the wire.
- **Verification method:** No need to restart the gateway/server. Just read the source. The live-capture approach via a proxy probe (8900) is blocked because the gateway doesn't reconnect to a new server without a full Hermes restart — but the source already provides conclusive evidence.
- **Deployment implication:** The proxy hardcodes 1 user_id per process. For per-session, read env `HERMES_SESSION_USER_ID` on the PROXY SIDE (not from the Hermes request).

## D-016 — Ollama (local) not installed on VPS → verify via wire simulation

- **Decision:** Ollama is not installed on this VPS (curl localhost:11434 failed). Verification is done via **upstream simulation** that mimics Ollama's wire quirks (SSE `data:` + `[DONE]`, empty keep-alive chunk `choices:[]`, content string). The OpenAI-compat adapter already handles all of this (byte-exact passthrough).
- **Evidence:** `tests/test_ollama.py` — 2 tests pass: stream passthrough (including keep-alive), non-stream JSON. Forward to `/v1/chat/completions` untouched.
- **Consequence:** Gemini / vLLM / LM Studio = OpenAI-compat → use the same adapter (ProviderAdapter interface). Anthropic needs its own adapter (D-002, already exists).
- **Note:** A REAL Ollama test needs Ollama installed (download GB-sized models). Defer until you want it — not a blocker for v1 (the adapter is already correct in wire terms).

## D-017 — Backup strategy (Postgres only, git = code)

- **Decision:** Backup = `pg_dump -Fc` daily via cron → local + `rclone` to B2/S3. Git holds ONLY source/config/migration. Memory/DB is **NOT** in git (`.gitignore` covers `*.dump`, `pgdata/`, `backup/`).
- **Evidence/implication:** `scripts/backup.sh` already exists, 14-day local retention. Recovery: `git clone` → `docker compose up` / native pg → `rclone copy` → `pg_restore`. WAL/PITR is intentionally skipped (overkill for single-user v1).
- **Consequence:** If the VPS dies → clone repo + restore dump = back up. Periodic restore tests are recommended but out of v1 automated scope.

## D-018 — Proxy model-list from upstream (not empty)

- **Decision:** The proxy's `/v1/models` and `/v1/models/{model}` routes **forward the GET to the real upstream** (reading the token via CredentialProvider), rather than returning an empty list.
- **Evidence:** When Hermes registers/checks a provider it probes `/v1/models` → if empty, it warns "model X not found in model listing" (ERR-008). After the proxy forwards to upstream, Hermes sees 278 real models → the warning disappears.
- **Consequence:** The proxy stays model-agnostic (list is taken from the active upstream). The OpenAI adapter gains `list_models()` + `get_model()` (the base adapter has a default no-op).

## D-019 — Registering provider in Hermes picker = `custom_providers:` in config.yaml

- **Decision:** For a proxy/provider to appear in Hermes's `/model` picker, register it as a `custom_providers:` entry (list of dict) in `~/.hermes/config.yaml`. Fields: `name`, `provider_key`, `base_url`, `api_mode: openai_chat`, `model`.
- **Evidence:** The plugin folder `~/.hermes/plugins/model-providers/<n>` is **NOT** used by the picker (only internal `list_providers()`). `hermes config set custom_providers '[{...}]'` stores it as a STRING (not parsed). The correct way = write the YAML list directly to config.yaml via script/python (ERR-007).
- **Consequence:** Switching provider in the picker = select that name; `base_url` automatically points to the proxy. No Hermes restart needed to switch between already-registered providers (config is just re-read per `/model`).
  - GUARD NOTE: the agent must NOT `patch`/`write` config.yaml via tool (security guard). Edit via terminal python (root) or have the user edit it.

## D-020 — Auto-refresh OAuth token on stale (401/403/404)

- **Decision:** `OpenAICompatibleAdapter.forward()` on a 401/403/404 from the upstream OAuth, calls `CredentialProvider.refresh_now()` then retries ONCE. No proxy restart needed on every token expiry.
- **Evidence:** Before the fix, a Nous token expired → proxy returned 404 → 1 request failed (ERR-010). The pattern repeated every few minutes. After the fix, the stale token is auto-refreshed within the same request.
- **Consequence:** The proxy is resilient to token expiry. `refresh_now()` force-refreshes, bypassing the expiry check; if the refresh fails, it falls back to the cached token (best-effort). Applies to oauth mode only (api_key doesn't need refresh).

## D-021 — Hermes internal memory migrated to Proxy DB

- **Decision:** The contents of `~/.hermes/memories/MEMORY.md` + `USER.md` are migrated to the `memories` table in the Proxy DB (source=`hermes_migration`), then the Hermes files are renamed to `m1.md`/`m2.md` so Hermes truly doesn't read them (only `MEMORY.md`/`USER.md` are recognized).
- **Evidence:** After the rename, you ask "Does the VPS use Docker?" → the proxy answers correctly (100% match with `m1.md`) → proves the proxy reads from the DB, NOT Hermes internal. Memory is now 100% in the Proxy (Postgres).
- **Consequence:** Hermes internal memory is disabled (files not recognized). Single source of truth = Proxy DB. To revert, rename `m1.md`→`MEMORY.md`.

## D-022 — Reference the-fool / hermes-loop: take PATTERNS, 3 separate repos

- **Decision:** Future memory-proxy is guided by `the-fool` (RFC-0002 Memory Engine: taxonomy Working/Short/Conversation/Semantic/Episodic/Reflection, Ranker, Compressor, Event Log) + `hermes-loop` (plugin.yaml + hooks pre_llm_call/on_session_start). **Take the PATTERNS, not the SKILL** — don't copy skill contents (core_evo, project_manager, growth_manager), brain/learnings, or the agent-os RFC. Target structure = **3 separate repos**: `memory-proxy/` (engine), `memory-proxy-plugin/` (inject memory into Hermes), `memory-proxy-skill/` (generic behavior). Each is cloned separately → just plug in.
- **Evidence:** `the-fool` is far more complete than `hermes-loop` (a living vault: hundreds of learnings, RFCs for memory/knowledge/context/router/learning, 4 loop_types categories). RFC-0002 memory taxonomy = a valid architecture reference. `hermes-loop` plugin format (plugin.yaml + hooks) = the correct Hermes plugin reference.
- **Consequence:** The memory-proxy repo = a generic EMPTY framework; persona/facts filled by the user (empty SOUL/USER templates). The DB is now non-critical → prioritize building architecture, not backup. The backup cron is DEFERRED. The agent planning-loop stays in Hermes; the proxy only does memory + behavior injection.

## D-023 — the-fool/hermes-loop loop mechanism (cron + plugin, not in proxy)

- **Decision:** "Smart second brain + loop" = a combination of (1) a plugin injecting behavior each chat (turn-based, ALREADY in `inject_memory`), AND (2) a **Hermes cron job** running the loop periodically (time-based). Not in the proxy. The proxy only does memory store + extract + consolidate API.
- **Evidence (from the-fool):** 30+ cron jobs (`loop_evolve`, `loop_intake`, `loop_daily_digest`, etc.) run on a schedule (hourly / */5). Each job = a **flat prompt** ("self-reflection"), NOT calling `brain_loop(...)` (that's HTTP 400 — their pitfall). Use `hermes cron run <id>` to verify. Learning: "when fixing fleet-wide config, verify ALL jobs, not just examples".
- **Evidence (from hermes-loop core skill):** `core` = the sole decision-maker; other skills are passive executors (don't call other skills, don't write session). Workflow: Load Session → Discover Goal → Plan → Select Skill → Execute → Validate → Review → Loop Control → Update Session → Escalate → Respond. Default max_iterations = 5.
- **Architecture (RFC-0001/0002/0006 the-fool):** LLM = syscall (not a product). Memory Engine = tiers (Working/Short/Conversation/Long/Semantic/Episodic/Reflection) + Ranker + Compressor + Event Log. Learning Engine = Experience → Reflection → Self-Critique → Score → Propose → Gate → Apply. **Auto-merge is opt-in, gated.**
- **Consequences for memory-proxy:** (a) the plugin ALREADY injects memory+planning (turn-based). (b) ADD Hermes cron jobs that call the proxy endpoints `/v1/consolidate` (summarize memory) + `/v1/reflect` (review facts) — flat prompt, verify each job. (c) Don't copy skill internals (core_evo/project_manager); just patterns. (d) Cron jobs need explicit user permission (rule), and don't auto-resurrect R&D loops without permission (the maintainer's lesson: income > R&D loops).
- **Evidence (verify):** consolidate actually LLM-summarizes 6 facts → the maintainer's profile summary (stored tier=long, logged to events+file). reflect scored 7 facts. 54 tests green.

## D-024 — DB backup off-VPS (private GitHub, not just local)

- **Decision:** Daily `pg_dump` backup → (1) local `/root/memory-proxy/backup/` (14-day retention, restore test already succeeded: 56 memories+4 events recovered), AND (2) **force-push to the private repo `memory-proxy-backup`, branch `latest`** (1 file `latest.dump`, no history buildup). If the VPS is totally lost → clone the `latest` branch → restore. Private repo = the maintainer's data doesn't leak.
- **Evidence:** `scripts/backup_to_github.sh` runs (dump 96694 bytes → push latest branch, verified via gh API size). Cron `loop_db_backup_gh` (daily 4AM) verified succeeded. `rclone` B2/S3 skipped (not installed) — GitHub becomes the off-VPS carrier.
- **Consequence:** "DB won't be lost" is safe even if the VPS dies. Note: the dump does NOT contain API keys/credentials (only memory+events). The main `memory-proxy` repo REMAINS pure code (backup is in a separate repo, per the rule "GitHub = source/config, NOT user memory" — but in this case the user explicitly permitted GitHub for off-VPS DB backup).

## D-025 — Mini-training quality pass (2026-07-13)

Live audit + code review: memory-proxy **already** resembles mini-training (RAG + extract + inject + loops), but there are quality gaps that make the "brain" noisy / less accurate.

### Problems found (evidence)

| # | Problem | Evidence | Impact |
|---|---------|----------|--------|
| 1 | **Consolidate spam** | Hourly cron adds near-identical profiles → **28** active `source=consolidated` rows | Top-k flooded with duplicate text; wastes tokens + LLM cost |
| 2 | **Exact-text duplicates** | Test/production facts pile up exact strings | Noise in DB |
| 3 | **Plugin not query-aware** | `GET /v1/memory` hardcodes query `"important user facts"` | Injection doesn't relate to the user's question |
| 4 | **Stream path blind extraction** | `assistant_msg=""` when `stream=True` | Extraction only from user turn |
| 5 | **Importance ranking idle** | `reflect` writes `importance`, search only does `ORDER BY distance` | Reflect loop nearly useless |
| 6 | **User-id split** | Many facts on default UUID; consolidate on telegram hash | Memory split across paths |

### Fixes (implementation)

1. Consolidate anti-spam — skip if cosine < 0.08; `expire_old_consolidated(keep=1)`.
2. Exact-text gate in `add_fact` + `expire_exact_duplicates`.
3. `GET /v1/memory?q=` query-aware + diversity profile facts.
4. Plugin sends latest user message as `q`.
5. Stream buffer SSE → writer + conversation log.
6. Ranking: `distance - 0.12 * importance`.
7. `POST /v1/admin/dedupe` + `scripts/dedupe_memories.py`.
8. Cron consolidate 60m → 6h (Hermes cron).
9. DB cleanup one-shot: active 208→181; consolidated 28→1.

### Intentionally unchanged

- Hermes gateway not restarted (permission: proxy only).
- Bulk merge default-UUID → telegram user (needs a decision).
- Enforce TEST_DATABASE_URL separate from prod.

### Post-restart verification

- `/health` ok; `/v1/memory?...&q=` returns `query_used`; `/v1/admin/dedupe` ok.

See also: `docs/AUDIT-2026-07-13-mini-training.md`.

## D-026 — Single-user brain (anti split user_id) — 2026-07-13

### Problem
Extract/retrieve can land in a **different UUID** because `_resolve_user_id` hashes the `user` field (telegram vs empty vs test). Result: 2+ "brain pockets" (default UUID ~141 facts vs `telegram:<your-user-id>` ~9 + consolidated).

### Decision
Deployment **single-user** (default):
1. `SINGLE_USER_MODE=true` (default) → all requests map to `DEFAULT_USER_ID` (ignore the `user` payload).
2. `DEFAULT_USER_ID` = stable hash `telegram:<your-user-id>` = `<canonical-user-uuid>`.
3. One-shot DB merge: all `memories` / `sessions` / `events` → canonical UUID; expire exact-dups.
4. Multi-tenant: set `SINGLE_USER_MODE=false` (hash opaque user again).

### Evidence
- Merge: memories UPDATE 177, sessions 520, active_on_others=0, active_on_canonical=155.
- API: `user=telegram:…` / `user=totally-different` / empty → **same** top facts.
- Tests: `tests/test_user_id.py` 4 passed.

### Ops
- Script: `scripts/merge_to_single_user.py`
- Restart `memory-proxy.service` after env change (gateway untouched).
