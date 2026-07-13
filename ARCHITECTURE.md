# ARCHITECTURE — Hermes Memory Proxy

> Status: FINAL (design-locked). Semua keputusan berbukti — lihat `DECISIONS.md`.
> Prinsip inti: **model-agnostic**. Core pipeline tidak boleh tahu provider mana yang aktif.

---

## 1. Ringkasan Sistem

Memory Proxy adalah **OpenAI-compatible endpoint** yang duduk di antara Hermes (client) dan LLM provider. Proxy bertanggung jawab penuh atas memory, knowledge base (RAG), dan context injection. Hermes cuma jadi client — semua kecerdasan memory keluar dari Hermes.

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

**Bukti feasibility** (diverifikasi ke source Hermes `/usr/local/lib/hermes-agent/`):
- Hermes bisa diarahkan ke custom `base_url` — `config.yaml:4` sudah pakai `base_url`.
- Hermes pakai `AsyncOpenAI` SDK (`agent/auxiliary_client.py:4377`) → semua traffic lewat satu endpoint.
- Streaming SSE dipakai (`agent/chat_completion_helpers.py:2214` → `"stream": True`).
- Provider adalah plugin registry (`providers/__init__.py`) → 29 provider bawaan, termasuk `custom` (OpenAI-compat / Ollama / local).

---

## 2. Prasyarat di Sisi Hermes (WAJIB)

Supaya memory 100% pindah ke proxy dan tidak ada double-injection:

```yaml
# ~/.hermes/config.yaml
model:
  base_url: http://127.0.0.1:8000/v1   # arahkan Hermes ke proxy
memory:
  memory_enabled: false          # matikan MEMORY.md internal Hermes
  user_profile_enabled: false    # matikan USER.md internal Hermes
```

Bukti: `agent/context_breakdown.py:72` cek flag `_memory_enabled` sebelum inject block memory ke system prompt. Flag `false` → block kosong dari awal, tidak ada live re-read (di-cache saat startup, `agent_init.py:1347`). Kalau tidak dimatikan, memory Hermes lokal + memory proxy tabrakan (double source).

---

## 3. Pipeline (urutan tetap — perubahan wajib dicatat di DECISIONS.md)

```
1. Parse request (OpenAI Chat Completions payload)
2. Load identity (SOUL.md + USER.md, cache in-memory, load sekali)
3. Retrieve memory      (pgvector, filter per user_id)
4. Retrieve knowledge   (pgvector, knowledge_chunks — TERPISAH dari memory)
5. Assemble context     (urutan §5)
6. Budget context       (estimasi token, potong dari history dulu)
7. Forward ke provider  (via ProviderAdapter — core tidak import provider spesifik)
8. Stream response      (SSE passthrough bit-exact ke client)
9. Async memory writer  (fire-and-forget, single-writer queue)
```

---

## 4. Komponen

| Komponen | Tanggung jawab | Keputusan kunci |
|---|---|---|
| **API Layer** | FastAPI, endpoint `/v1/chat/completions` + `/v1/models`, no business logic | wire kanonik = OpenAI Chat Completions |
| **Identity Loader** | SOUL.md + USER.md, cache in-memory, reload via `/admin/reload-identity` | load sekali saat startup |
| **Memory Retrieval** | semantic search tabel `memories`, filter `user_id` | pgvector, dim 384 |
| **Knowledge Retrieval** | semantic search `knowledge_chunks` | TIDAK PERNAH dicampur dengan memory dalam satu query |
| **Context Assembler** | gabung sumber sesuai urutan tetap | deterministik |
| **Token Budgeter** | potong context jika lewat budget | estimasi `len//3` + margin, bukan tokenizer akurat |
| **Provider Adapter** | forward + inject_context + extract_latest_user_message | OpenAI-compat duluan; Anthropic/Codex fase lanjut |
| **Async Memory Writer** | extract fakta + embed + simpan | model kecil TERPISAH, async, ADD-only |
| **Embedding Service** | bge-small-en-v1.5 via fastembed (ONNX) | lokal, dim 384, no PyTorch |

---

## 5. Context Assembler — Urutan (tetap)

```
1. SOUL
2. USER
3. Memory      (semantic search `memories`, filtered per user_id)
4. Knowledge   (semantic search `knowledge_chunks`)
5. Recent Messages (dari conversations, dibatasi N turn/token)
6. Current User Prompt
```

**Prinsip wajib:** `memories` (data user, personal) dan `knowledge_chunks` (dokumen statis, generic) **tidak boleh dicampur dalam satu query retrieval** — diambil terpisah, digabung di assembler, supaya guardrail per-sumber bisa dibedakan.

---

## 6. Token Budgeter

Prioritas saat context melebihi budget (item kiri dipertahankan lebih lama):

```
SOUL → USER → Memory → Knowledge → Chat History
```

Chat History dipotong duluan. Estimasi token pakai `len(text)//3` + `reserved_pct` besar (0.25–0.3). `total_context_window` dikonfigurasi per provider/model aktif, bukan hardcode.

---

## 7. Provider Adapter (abstraksi model-agnostic)

```python
class ProviderAdapter(ABC):
    async def forward(self, payload, stream) -> AsyncIterator[bytes] | dict: ...
    def inject_context(self, payload, context_block) -> dict: ...       # return baru, jangan mutate
    def extract_latest_user_message(self, payload) -> str: ...
```

Core (`orchestrator.py`) hanya bicara ke interface — tidak pernah import provider spesifik. Ganti model = ganti `provider.active` di config.

**Wire-format map (bukti Task 8):**

| Provider | Wire | v1? |
|---|---|---|
| openai, openrouter, ollama, vLLM, LM Studio, custom | Chat Completions | ✅ |
| Anthropic | Messages API (system terpisah) | fase 2 |
| Gemini | OpenAI-compat mode | fase 2 |
| Codex/Responses API | beda total | ❌ (jangan) |

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
    embedding_model TEXT NOT NULL,       -- track model+versi utk migrasi aman
    valid_from TIMESTAMPTZ NOT NULL DEFAULT now(),
    valid_until TIMESTAMPTZ,             -- NULL = masih berlaku (validity window ala Zep)
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
chat turn → heuristic gate (buang 50-70% turn kosong)
          → LLM KECIL TERPISAH extract (bukan model utama)
          → rule-normalisasi → dedupe (cosine similarity)
          → ADD-only store (LLM tidak memilih UPDATE/DELETE)
per-turn: async fire-and-forget (tidak blocking)
end-of-session: consolidation (dedupe/merge/invalidate via valid_until)
```

Output extraction dibatasi ketat: list fakta pendek, `response_format=json_object` + parser fallback (Ollama kecil suka ngaco JSON).

---

## 10. Backup & DR

- **GitHub = code/config/migration/docker only.** Memory/DB TIDAK PERNAH di git.
- **pg_dump harian** (`-Fc`) → upload off-VPS (Backblaze B2 / S3 via rclone).
- Recovery: `git clone → docker compose up -d → pg_restore`.
- WAL/PITR = overkill v1.

---

## 11. Metrics

```json
{"timestamp":"...","session_id":"...","provider":"...","context_tokens_used":412,
 "context_budget":2000,"memory_chunks_retrieved":3,"knowledge_chunks_retrieved":2,
 "facts_written":1,"latency_ms":890,"streamed":true}
```
