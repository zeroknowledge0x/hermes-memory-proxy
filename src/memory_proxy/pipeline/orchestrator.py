"""Pipeline orchestrator — full 9-step pipeline (ARCHITECTURE §3).

1. Parse request      6. Budget context
2. Load identity      7. Inject + forward to provider
3. Retrieve memory    8. Stream response
4. Retrieve knowledge 9. Async memory write (fire-and-forget)
5. Assemble context

Memory and knowledge are retrieved SEPARATELY and never mixed (guardrail).
Retrieval/writer are optional — if not wired, pipeline degrades to pure
passthrough (Phase 1.2 behaviour).
"""
from __future__ import annotations

import json
import os

from typing import Any, AsyncIterator

from memory_proxy.context.assembler import ContextAssembler
from memory_proxy.context.budgeter import TokenBudgeter
from memory_proxy.providers.base import ProviderAdapter


def _log_file(kind: str, detail: dict) -> None:
    """Append-only event log to logs/memory.log (audit, besides DB events)."""
    try:
        path = os.path.join(os.path.dirname(__file__), "..", "..", "logs", "memory.log")
        path = os.path.abspath(path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{_now_iso()} [{kind}] {json.dumps(detail, ensure_ascii=False)}\n")
    except Exception:
        pass


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Orchestrator:
    def __init__(
        self,
        provider: ProviderAdapter,
        *,
        identity=None,
        memory_repo=None,
        knowledge_repo=None,
        conversation_repo=None,
        writer=None,
        budgeter: TokenBudgeter | None = None,
        default_user_id: str = "00000000-0000-0000-0000-000000000001",
        top_k: int = 5,
    ):
        self._provider = provider
        self._identity = identity
        self._memory = memory_repo
        self._knowledge = knowledge_repo
        self._conversations = conversation_repo
        self._writer = writer
        self._budgeter = budgeter
        self._assembler = ContextAssembler()
        self._default_user_id = default_user_id
        self._top_k = top_k

    def _resolve_user_id(self, payload: dict[str, Any]) -> str:
        # D-013: single-user hardcode by default. If the client sends a
        # `user` field (Hermes may pass an opaque id like "telegram:123"),
        # map it deterministically to a UUID so it's safe for the DB and
        # stable per user. Never trust the raw value as a UUID.
        import uuid as _uuid
        import hashlib as _hash

        raw = payload.get("user")
        if not raw:
            return str(self._default_user_id)
        digest = _hash.sha256(str(raw).encode()).digest()
        return str(_uuid.UUID(bytes=digest[:16]))

    async def handle(
        self, payload: dict[str, Any]
    ) -> "AsyncIterator[bytes] | dict[str, Any]":
        stream = bool(payload.get("stream", False))
        user_id = self._resolve_user_id(payload)
        query = self._provider.extract_latest_user_message(payload)

        # 0. make sure the user row exists (Hermes sends opaque ids)
        if self._memory:
            await self._memory.ensure_user(user_id)

        # 2. identity
        soul = self._identity.soul if self._identity else ""
        user = self._identity.user if self._identity else ""

        # 3 + 4. retrieve memory & knowledge SEPARATELY
        memory_hits = (
            await self._memory.search(user_id, query, limit=self._top_k)
            if self._memory and query else []
        )
        knowledge_hits = (
            await self._knowledge.search(query, limit=self._top_k)
            if self._knowledge and query else []
        )
        # 3b. retrieve recent conversations (Opsi C: recall past chat)
        conv_hits = (
            await self._conversations.search_recent(user_id, query, limit=self._top_k)
            if self._conversations and query else []
        )

        # 5. assemble
        ctx = self._assembler.assemble(
            soul=soul, user=user,
            memory=[h["content"] for h in memory_hits],
            knowledge=[h["content"] for h in knowledge_hits],
            history=[f"{c['role']}: {c['content']}" for c in conv_hits],
        )

        # 6. budget
        if self._budgeter:
            ctx = self._budgeter.fit(ctx)
        context_block = ctx.render()

        # 7. inject + forward
        final_payload = self._provider.inject_context(payload, context_block)
        result = await self._provider.forward(final_payload, stream=stream)

        # 9. async memory write (fire-and-forget, non-blocking)
        if self._writer and query:
            if stream and hasattr(result, "__aiter__"):
                # Buffer SSE so we can extract facts AFTER the stream ends.
                # Without this, streaming turns never pass assistant_msg to the
                # extractor and conversation logs miss the assistant reply.
                return self._stream_then_write(result, user_id, query)  # type: ignore[arg-type]
            assistant_msg = ""
            if isinstance(result, dict):
                assistant_msg = (
                    result.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                    or ""
                )
            self._writer.enqueue(user_id, query, assistant_msg)
            if self._conversations:
                await self._conversations.add_turn(user_id, "user", query)
                if assistant_msg:
                    await self._conversations.add_turn(user_id, "assistant", assistant_msg)

        return result

    async def _stream_then_write(
        self, stream_result: AsyncIterator[bytes], user_id: str, query: str
    ) -> AsyncIterator[bytes]:
        """Passthrough SSE bytes while collecting assistant text for the writer."""
        pieces: list[str] = []
        async for chunk in stream_result:
            # Decode & parse OpenAI-style SSE deltas (best-effort).
            try:
                text = chunk.decode("utf-8", errors="ignore")
            except Exception:
                text = ""
            for line in text.splitlines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    obj = json.loads(data)
                    delta = (
                        obj.get("choices", [{}])[0]
                        .get("delta", {})
                        .get("content")
                    )
                    if delta:
                        pieces.append(delta)
                except Exception:
                    pass
            yield chunk

        assistant_msg = "".join(pieces)
        if self._writer and query:
            self._writer.enqueue(user_id, query, assistant_msg)
        if self._conversations and query:
            await self._conversations.add_turn(user_id, "user", query)
            if assistant_msg:
                await self._conversations.add_turn(user_id, "assistant", assistant_msg)

    async def consolidate(self, user_id: str, keep: int = 20) -> dict:
        """Time-based loop (D-023): summarise recent facts into a Long memory.

        Called by the Hermes cron job (flat prompt, never brain_loop()).

        Anti-spam:
        - If new summary is nearly identical to the latest consolidated
          (cosine distance < 0.08), SKIP insert.
        - When a new distinct summary is added, expire older consolidated
          rows (keep only the newest 1).
        """
        if not self._memory:
            return {"status": "no-memory"}
        facts = await self._memory.recent_facts(user_id, limit=keep)
        if not facts:
            return {"status": "nothing-to-consolidate"}
        lines = "\n".join(f"- {f['content']}" for f in facts)
        summary = await self._summarise(
            user_id,
            "Consolidate these user facts into a concise durable profile "
            "(name, preferences, context). Keep only what is stable/reusable. "
            "1 short paragraph, no preamble.",
            lines,
        )
        if not summary:
            return {"status": "llm-failed"}

        # Skip if nearly-identical to newest active consolidated.
        near = await self._memory.search(user_id, summary, limit=3)
        for h in near:
            if (h.get("source") == "consolidated" or "consolidated" in str(h.get("source", ""))) and h["distance"] < 0.08:
                await self._memory.log_event(
                    user_id, "consolidate",
                    {"status": "skipped-duplicate", "distance": h["distance"]},
                )
                _log_file("consolidate", {"user": user_id, "status": "skipped-duplicate"})
                return {
                    "status": "skipped-duplicate",
                    "distance": h["distance"],
                    "facts_seen": len(facts),
                }
        # Also skip if any hit is extremely close regardless of source label
        # (covers older rows tagged differently).
        if near and near[0]["distance"] < 0.05 and len(near[0]["content"]) > 80:
            # Only skip when the nearest neighbour is itself a long profile-like fact
            if near[0]["content"][:40].lower() in summary[:80].lower() or near[0]["distance"] < 0.03:
                await self._memory.log_event(
                    user_id, "consolidate",
                    {"status": "skipped-near", "distance": near[0]["distance"]},
                )
                _log_file("consolidate", {"user": user_id, "status": "skipped-near"})
                return {
                    "status": "skipped-duplicate",
                    "distance": near[0]["distance"],
                    "facts_seen": len(facts),
                }

        await self._memory.add_consolidated(user_id, summary, "consolidated")
        expired = await self._memory.expire_old_consolidated(user_id, keep=1)
        await self._memory.log_event(
            user_id, "consolidate",
            {"input_count": len(facts), "summary": summary, "expired_old": expired},
        )
        _log_file("consolidate", {"user": user_id, "summary": summary, "expired_old": expired})
        return {
            "status": "ok",
            "summary": summary,
            "facts_seen": len(facts),
            "expired_old": expired,
        }

    async def audit(self, user_id: str, since_hours: int = 24) -> dict:
        """Daily audit loop (Opsi C): read recent conversations, ask the LLM
        which turns are USEFUL / likely-to-be-reused, promote those to memory
        (source='audit'), and archive the rest (stop retrieval, keep for audit).
        """
        if not self._conversations or not self._memory:
            return {"status": "no-conversations"}
        turns = await self._conversations.recent_turns(user_id, since_hours=since_hours)
        if not turns:
            return {"status": "nothing-to-audit"}
        text = "\n".join(f"- {t}" for t in turns)
        # LLM picks the useful, reusable ones (facts / preferences / context)
        useful = await self._summarise(
            user_id,
            "From this conversation transcript, extract ONLY lines that are "
            "USEFUL and LIKELY TO BE REUSED later: stable facts, user preferences, "
            "decisions, context. Skip chit-chat, questions, transient status. "
            "Return one bullet per item, original wording. If none, return 'NONE'.",
            text,
        )
        promoted = 0
        if useful and useful.strip().upper() != "NONE":
            for line in useful.splitlines():
                line = line.lstrip("- ").strip()
                if not line:
                    continue
                if self._memory:
                    new_id = await self._memory.add_fact(user_id, line, source="audit")
                    if new_id:
                        promoted += 1
        # archive old conversations so they leave the hot retrieval path
        archived = await self._conversations.archive(user_id, older_than_hours=since_hours)
        await self._memory.log_event(
            user_id, "audit",
            {"reviewed": len(turns), "promoted": promoted, "archived": archived},
        )
        _log_file("audit", {"user": user_id, "promoted": promoted, "archived": archived})
        return {"status": "ok", "reviewed": len(turns), "promoted": promoted, "archived": archived}

    async def reflect(self, user_id: str) -> dict:
        """Time-based loop (D-023): score importance of recent facts."""
        if not self._memory:
            return {"status": "no-memory"}
        facts = await self._memory.recent_facts(user_id, limit=15)
        scored = 0
        for f in facts:
            score = self._importance_score(f["content"], f.get("source"))
            await self._memory.score_importance(str(f["id"]), score)
            scored += 1
        await self._memory.log_event(user_id, "reflect", {"scored": scored})
        _log_file("reflect", {"user": user_id, "scored": scored})
        return {"status": "ok", "scored": scored}

    async def _summarise(self, user_id: str, instr: str, text: str) -> str | None:
        if not self._writer or not getattr(self._writer, "_extractor", None):
            return None
        try:
            return await self._writer._extractor.summarise(instr, text)
        except Exception:
            return None

    @staticmethod
    def _importance_score(content: str, source: str | None) -> float:
        score = 0.5
        c = (content or "").lower()
        if any(k in c for k in ["nama", "name", "kuliah", "kerja", "prefer", "suka", "benci", "jangan"]):
            score += 0.3
        if source == "consolidated":
            score += 0.1
        return min(1.0, score)
