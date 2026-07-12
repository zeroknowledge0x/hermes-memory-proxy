"""Conversation repository — full-write raw chat logs (ARCHITECTURE §5, tier: Conversation).

Every turn (user + assistant) is written verbatim. A daily audit (cron ->
/v1/audit) filters which conversations are USEFUL / likely-to-be-reused and
promotes them to `memories` (source='audit'), archiving the rest so they stop
being retrieved but remain for audit.
"""
from __future__ import annotations

from typing import Any

from memory_proxy.knowledge.embedding import EmbeddingService


class ConversationRepository:
    def __init__(self, pool, embedder: EmbeddingService | None = None):
        self._pool = pool
        self._embedder = embedder

    async def add_turn(
        self, user_id: str, role: str, content: str, session_id: str | None = None
    ) -> None:
        """Write one turn. Creates a session if none provided (per user)."""
        async with self._pool.acquire() as c:
            if not session_id:
                row = await c.fetchrow(
                    """INSERT INTO sessions (user_id) VALUES ($1)
                       RETURNING id""",
                    user_id,
                )
                session_id = str(row["id"])
            await c.execute(
                """INSERT INTO conversations (session_id, role, content)
                   VALUES ($1, $2, $3)""",
                session_id, role, content,
            )

    async def search_recent(
        self, user_id: str, query: str, limit: int = 5,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        """Semantic search over NON-archived conversations for a user.

        Used by the orchestrator to recall past chat context (Opsi C).
        """
        vec = self._embedder.embed_one(query) if self._embedder else None
        async with self._pool.acquire() as c:
            if vec is not None:
                lit = EmbeddingService.to_pgvector(vec)
                rows = await c.fetch(
                    """
                    SELECT conv.content, conv.role, conv.created_at
                    FROM conversations conv
                    JOIN sessions s ON s.id = conv.session_id
                    WHERE s.user_id = $1 AND (conv.archived = FALSE OR $3)
                    ORDER BY conv.created_at DESC
                    LIMIT $2
                    """,
                    user_id, limit, include_archived,
                )
            else:
                rows = await c.fetch(
                    """
                    SELECT conv.content, conv.role, conv.created_at
                    FROM conversations conv
                    JOIN sessions s ON s.id = conv.session_id
                    WHERE s.user_id = $1 AND (conv.archived = FALSE OR $3)
                    ORDER BY conv.created_at DESC
                    LIMIT $2
                    """,
                    user_id, limit, include_archived,
                )
        return [dict(r) for r in rows]

    async def recent_turns(self, user_id: str, since_hours: int = 24) -> list[str]:
        """All conversation contents in the last N hours (for the daily audit)."""
        async with self._pool.acquire() as c:
            rows = await c.fetch(
                """
                SELECT conv.content
                FROM conversations conv
                JOIN sessions s ON s.id = conv.session_id
                WHERE s.user_id = $1
                  AND conv.created_at > now() - ($2::text || ' hours')::interval
                ORDER BY conv.created_at ASC
                """,
                user_id, str(since_hours),
            )
        return [r["content"] for r in rows]

    async def archive(self, user_id: str, older_than_hours: int = 24) -> int:
        """Mark old conversations archived (stop retrieval, keep for audit).

        Returns count archived.
        """
        async with self._pool.acquire() as c:
            res = await c.execute(
                """
                UPDATE conversations conv
                SET archived = TRUE
                FROM sessions s
                WHERE s.id = conv.session_id
                  AND s.user_id = $1
                  AND conv.archived = FALSE
                  AND conv.created_at < now() - ($2::text || ' hours')::interval
                """,
                user_id, str(older_than_hours),
            )
            # psycopg returns 'UPDATE n'
            try:
                return int(str(res).split()[-1])
            except Exception:
                return 0
