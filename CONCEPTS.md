# Concepts — Why Hermes Memory Proxy Exists

This document explains the *why*, not the *how* (see `README.md` / `FOR_AGENT.md`
for the *how*). Read it if you are deciding whether this tool fits your problem.

---

## 1. The core problem

LLMs are **stateless**. An agent (Hermes, or any other) "forgets" the moment a
session ends. Two common workarounds each have a flaw:

| Approach | Flaw |
|----------|------|
| Stuff everything into the system prompt | blows the context window; no retrieval; no forgetting |
| Generic RAG over a doc folder | mixes *your facts* with *reference docs*; no per-user isolation; no self-improvement |

Hermes Memory Proxy is the **memory layer** that sits between the agent and the
model. The model becomes a replaceable syscall; **intelligence lives in state,
retrieval, and loops** — not in the weights.

---

## 2. Key idea: the model is a syscall, memory is the brain

```
agent ──▶ proxy (memory + identity + loops) ──▶ model
```

- The **model** answers one turn. It is swappable (OpenAI / Nous / Anthropic /
  Gemini / Ollama / vLLM) by config only — the pipeline never imports a concrete
  provider.
- The **proxy** owns durable memory, structured identity, and periodic
  self-improvement. Memory survives model swaps and session restarts because
  it lives here, not in the model or in Hermes internals.

> If you swap `tencent/hy3` for `claude`, your agent keeps its memories. Try
> that with prompt-stuffing.

---

## 3. Memory vs Knowledge (do not mix them)

| | Memory | Knowledge |
|---|--------|-----------|
| Source | conversations with the user | static docs you ingest |
| Examples | "my name is X", "I prefer Y" | API docs, manuals, wiki |
| Store | `memories` (per-user) | `knowledge` (shared) |
| Retrieved by | user_id + semantic search | query + semantic search |
| Lifetime | until forgotten/consolidated | until you re-ingest |

Mixing them is the #1 RAG mistake: personal facts leak into shared recall, and
reference noise pollutes identity. This proxy keeps two separate vector stores.

---

## 4. Why model-agnostic matters

You should not have to rewrite your agent when you change providers. The proxy
speaks **OpenAI Chat Completions** on both sides (canonical wire format). The
provider is a config value (`PROVIDER_TYPE` + `UPSTREAM_BASE_URL`). Extraction,
consolidation, and reflection use the *same* upstream model — no second bill
unless you point them elsewhere.

This also means **portability**: the engine runs anywhere Python + Postgres run.
No vendor lock-in.

---

## 5. Self-improvement loops (the "second brain")

Memory is not just recall — it is *compounding*. Two loops run on a schedule
(via Hermes cron, flat prompts — never `brain_loop(...)`):

- **Consolidate** (`/v1/consolidate`): summarise recent facts into a durable
  profile (Long-term memory). Prevents context bloat from 10,000 raw facts.
- **Reflect** (`/v1/reflect`): score importance of recent facts so retrieval
  ranks what matters.

Without loops, memory is a flat pile. With loops, it *improves* over time —
the behaviour the-fool / hermes-loop specs call "the agent's brain".

---

## 6. When you SHOULD use this

- You run an agent that talks to users and must remember them across sessions.
- You want memory to survive model swaps / provider outages.
- You want structured identity (SOUL/USER) injected automatically.
- You want self-improvement without hand-rolling cron + DB + embeddings.

## 7. When you should NOT

- You only need one-shot Q&A over a doc set → plain RAG is simpler.
- You need multi-tenant isolation at scale → this is single-user / single-machine
  by design (per-user columns exist, but multi-tenant auth is out of scope for v1).
- You cannot run Postgres + pgvector → that is the only hard dependency.

---

## 8. Design principles (non-negotiable)

1. **Verify, don't assume.** Every claim in docs is backed by a runnable test
   or a real endpoint check.
2. **Provider = config.** No code change to swap models.
3. **Memory < model.** The model is dumb; the brain is the proxy.
4. **Loops are external.** The proxy reacts; the agent (Hermes cron) drives time.
5. **Backup or it didn't happen.** Daily dump → local + off-VPS (separate private repo).

---

## 9. Relationship to the-fool / hermes-loop

This project is **inspired by** (not a fork of) the `the-fool` "Hermes Brain"
specs (RFC-0001/0002/0006) and `hermes-loop`. We take the **pola** — memory
taxonomy, loop types, ranker/compressor, plugin format — and **NOT** the skill
implementations (those are the author's private agents). Three repos stay
separate: engine (`memory-proxy`), plugin (`-plugin`), skill (`-skill`).
