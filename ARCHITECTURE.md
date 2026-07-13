# ARCHITECTURE — Hermes Memory Proxy

> Status: FINAL (design-locked). All decisions are evidenced — see `DECISIONS.md`.
> Core principle: **model-agnostic**. The core pipeline must not know which provider is active.

---

## 1. System Overview

The Memory Proxy is an **OpenAI-compatible endpoint** that sits between Hermes (client) and the LLM provider. The proxy is fully responsible for memory, the knowledge base (RAG), and context injection. Hermes is merely a client — all memory intelligence resides outside Hermes.

```
┌──────────┐   OpenAI Chat Completions      ┌─────────────────┐   wire per-provider   ┌──────────────┐
│  Hermes  │ ─────────────────────────────▶ │  Memory Proxy   │ ────────────────────▶ │ LLM Provider │
│ (client) │ ◀───────── SSE stream ──────── │  (this repo)    │ ◀──── SSE stream ──── │ (swappable)  │
└──────────┘                                └─────────────────┘                       └──────────────┘
                                                    │ async (non-blocking)
                                                    ▼
                                            ┌─────────────────┐
                                            │ Postgres+pgvector│
                                            │ memory+knowledge │
                                            └─────────────────┘
```

**Feasibility evidence** (verified against Hermes source `/usr/local/lib/hermes-agent/`):
- Hermes can be pointed at a custom `base_url` — `config.yaml:4` already uses `base_url`.
- Hermes uses the `AsyncOpenAI` SDK (`agent/auxiliary_client.py:4377`) → all traffic flows through a single endpoint.
- SSE streaming is used (`agent/chat_completion_helpers.py:2214` → `"stream": True`).
- Providers are a plugin registry (`providers/__init__.py`) → 29 built-in providers, including `custom` (OpenAI-compat / Ollama / local).

---

## 2. Hermes-Side Prerequisites (REQUIRED)

So that memory moves 100% to the proxy with no double-injection:

```yaml
# ~/.hermes/config.yaml
model:
  base_url: http://127.0.0.1:8000/v1   # point Hermes at the proxy
memory:
  memory_enabled: false          # disable Hermes internal MEMORY.md
  user_profile_enabled: false    # disable Hermes internal USER.md
```

Evidence: `agent/context_breakdown.py:72` checks the `_memory_enabled` flag before injecting the memory block into the system prompt. Flag `false` → the block is empty from the start, with no live re-read (cached at startup, `agent_init.py:1347`). If not disabled, local Hermes memory and proxy memory collide (double source).

---

## 3. Pipeline (fixed order — changes must be recorded in DECISIONS.md)

```
1. Parse request (OpenAI Chat Completions payload)
2. Load identity (SOUL.md + USER.md, cache in-memory, load once)
3. Retrieve memory      (pgvector, filter per user_id)
4. Retrieve knowledge   (pgvector, knowledge_chunks — SEPARATE from memory)
5. Assemble context     (order §5)
6. Budget context       (token estimate, trim history first)
7. Forward to provider  (via ProviderAdapter — core does not import a specific provider)
8. Stream response      (SSE passthrough bit-exact to client)
9. Async memory writer  (fire-and-forget, single-writer queue)
```

---

## 4. Components

| Component | Responsibility | Key Decision |
|---|---|---|
| **API Layer** | FastAPI, endpoint `/v1/chat/completions` + `/v1/models`, no business logic | canonical wire = OpenAI Chat Completions |
| **Identity Loader** | SOUL.md + USER.md, cache in-memory, reload via `/admin/reload-identity` | loaded once at startup |
| **Memory Retrieval** | semantic search table `memories`, filter `user_id` | pgvector, dim 384 |
| **Knowledge Retrieval** | semantic search `knowledge_chunks` | NEVER mixed with memory in a single query |
| **Context Assembler** | merge sources in fixed order | deterministic |
| **Token Budgeter** | trim context if over budget | estimate `len//3` + margin, not an accurate tokenizer |
| **Provider Adapter** | forward + inject_context + extract_latest_user_message | OpenAI-compat first; Anthropic/Codex later phase |
| **Async Memory Writer** | extract facts + embed + store | separate small model, async, ADD-only |
| **Embedding Service** | bge-small-en-v1.5 via fastembed (ONNX) | local, dim 384, no PyTorch |

---

## 5. Context Assembler — Order (fixed)

```
1. SOUL
2. USER
3. Memory      (semantic search `memories`, filtered per user_id)
4. Knowledge   (semantic search `knowledge_chunks`)
5. Recent Messages (from conversations, limited to N turns/tokens)
6. Current User Prompt
```

**Mandatory principle:** `memories` (user data, personal) and `knowledge_chunks` (static documents, generic) **must never be mixed in a single retrieval query** — they are fetched separately and merged in the assembler so per-source guardrails can be distinguished.

---

## 6. Token Budgeter

Priority when context exceeds budget (left items are retained longer):

```
SOUL → USER → Memory → Knowledge → Chat History
```

Chat History is trimmed first. Token estimation uses `len(text)//3` + a large `reserved_pct` (0.25–0.3). `total_context_window` is configured per active provider/model, not hardcoded.

---

## 7. Provider Adapter (model-agnostic abstraction)

```python
class ProviderAdapter(ABC):
    async def forward(self, payload, stream) -> AsyncIterator[bytes] | dict: ...
    def inject_context(self, payload, context_block) -> dict: ...       # return new, do not mutate
    def extract_latest_user_message(self, payload) -> str: ...
```

The core (`orchestrator.py`) only talks to the interface — it never imports a specific provider. Changing the model = changing `provider.active` in the config.

**Wire-format map (evidence, Task 8):**

| Provider | Wire | v1? |
|---|---|---|
| openai, openrouter, ollama, vLLM, LM Studio, custom | Chat Completions | ✅ |
| Anthropic | Messages API (separate system) | phase 2 |
| Gemini | OpenAI-compat mode | phase 2 |
| Codex/Responses API | entirely different | ❌ (avoid) |

---

## 8. Database Schema (Postgres + pgvector)

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    display_name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_active_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL CHECK (role IN ('user','assistant','system')),
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_conversations_session ON conversations(session_id, created_at);

CREATE TABLE memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    content TEXT NOT NULL,
    source TEXT,
    embedding VECTOR(384),               -- bge-small-en-v1.5, LOCKED
    embedding_model TEXT NOT NULL,       -- track model+version for safe migration
    valid_from TIMESTAMPTZ NOT NULL DEFAULT now(),
    valid_until TIMESTAMPTZ,             -- NULL = still valid (validity window à la Zep)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_memories_embedding ON memories USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_memories_user ON memories(user_id) WHERE valid_until IS NULL;

CREATE TABLE knowledge_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_uri TEXT,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE knowledge_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES knowledge_documents(id),
    chunk_index INT NOT NULL,
    content TEXT NOT NULL,
    embedding VECTOR(384),
    embedding_model TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_knowledge_chunks_embedding ON knowledge_chunks USING hnsw (embedding vector_cosine_ops);
```

---

## 9. Fact Extraction (Async Memory Writer)

```
chat turn → heuristic gate (discard 50-70% empty turns)
          → SEPARATE SMALL LLM extract (not the main model)
          → rule-normalization → dedupe (cosine similarity)
          → ADD-only store (LLM does not choose UPDATE/DELETE)
per-turn: async fire-and-forget (non-blocking)
end-of-session: consolidation (dedupe/merge/invalidate via valid_until)
```

Extraction output is tightly constrained: a list of short facts, `response_format=json_object` + parser fallback (small Ollama models often produce malformed JSON).

---

## 10. Backup & DR

- **GitHub = code/config/migration/docker only.** Memory/DB is NEVER committed to git.
- **Daily pg_dump** (`-Fc`) → upload off-VPS (Backblaze B2 / S3 via rclone).
- Recovery: `git clone → docker compose up -d → pg_restore`.
- WAL/PITR = overkill v1.

---

## 11. Metrics

```json
{"timestamp":"...","session_id":"...","provider":"...","context_tokens_used":412,
 "context_budget":2000,"memory_chunks_retrieved":3,"knowledge_chunks_retrieved":2,
 "facts_written":1,"latency_ms":890,"streamed":true}
```
