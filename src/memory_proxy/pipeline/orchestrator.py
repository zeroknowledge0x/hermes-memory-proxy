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
        #    Must await the result first so we have the assistant reply.
        if self._writer and query:
            assistant_msg = ""
            if not stream and isinstance(result, dict):
                assistant_msg = (
                    result.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )
            self._writer.enqueue(user_id, query, assistant_msg)
            # full-write conversation log (Opsi C)
            if self._conversations:
                await self._conversations.add_turn(user_id, "user", query)
                if assistant_msg:
                    await self._conversations.add_turn(user_id, "assistant", assistant_msg)

        return result

    async def consolidate(self, user_id: str, keep: int = 20) -> dict:
        """Time-based loop (D-023): summarise recent facts into a Long memory.

        Called by the Hermes cron job (flat prompt, never brain_loop()).
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
        if summary:
            await self._memory.add_consolidated(user_id, summary, "consolidated")
            await self._memory.log_event(
                user_id, "consolidate",
                {"input_count": len(facts), "summary": summary},
            )
            _log_file("consolidate", {"user": user_id, "summary": summary})
            return {"status": "ok", "summary": summary, "facts_seen": len(facts)}
        return {"status": "llm-failed"}

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
                if self._memory and self._writer:
                    await self._memory.add_fact(user_id, line, source="audit")
                    promoted += 1
        # archive old conversations so they leave the hot retrieval path
        archived = await self._conversations.archive(user_id, older_than_hours=since_hours)
        await self._memory.log_event(
            user_id, "audit",
            {"reviewed": len(turns), "promoted": promoted, "archived": archived},
        )
        _log_file("audit", {"user": user_id, "promoted": promoted, "archived": archived})
        return {"status": "ok", "reviewed": len(turns), "promoted": promoted, "archived": archived}
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
