"""Memory repository + retrieval (DECISIONS.md D-005/D-006/D-007).

- Facts stored ADD-only with validity window (valid_until IS NULL = active).
- Retrieval = pgvector cosine similarity, filtered by user_id.
- Memory and knowledge are NEVER queried together (ARCHITECTURE §5).
"""
from __future__ import annotations

from typing import Any

from memory_proxy.knowledge.embedding import EmbeddingService


class MemoryRepository:
    def __init__(self, pool, embedder: EmbeddingService):
        self._pool = pool
        self._embedder = embedder

    async def add_fact(
        self, user_id: str, content: str, source: str | None = None
    ) -> str:
        vec = self._embedder.embed_one(content)
        literal = EmbeddingService.to_pgvector(vec)
        async with self._pool.acquire() as c:
            row = await c.fetchrow(
                """
                INSERT INTO memories (user_id, content, source, embedding, embedding_model)
                VALUES ($1, $2, $3, $4::vector, $5)
                RETURNING id
                """,
                user_id, content, source, literal, self._embedder.model_name,
            )
        return str(row["id"])

    async def search(
        self, user_id: str, query: str, limit: int = 5
    ) -> list[dict[str, Any]]:
        """Semantic search over ACTIVE memories for a user, by cosine distance."""
        vec = self._embedder.embed_one(query)
        literal = EmbeddingService.to_pgvector(vec)
        async with self._pool.acquire() as c:
            rows = await c.fetch(
                """
                SELECT id, content, source,
                       embedding <=> $2::vector AS distance
                FROM memories
                WHERE user_id = $1 AND valid_until IS NULL
                ORDER BY embedding <=> $2::vector
                LIMIT $3
                """,
                user_id, literal, limit,
            )
        return [
            {"id": str(r["id"]), "content": r["content"],
             "source": r["source"], "distance": float(r["distance"])}
            for r in rows
        ]

    async def ensure_user(self, user_id: str) -> None:
        """Idempotent: create the user row if it does not exist yet.

        Needed because Hermes sends an opaque id (e.g. 'telegram:5398668166')
        that we hash to a UUID — the row may not be pre-registered.
        """
        async with self._pool.acquire() as c:
            await c.execute(
                "INSERT INTO users (id) VALUES ($1) ON CONFLICT (id) DO NOTHING",
                user_id,
            )

    async def recent_facts(self, user_id: str, limit: int = 20) -> list[dict]:
        """Most recent ACTIVE facts (for consolidation / reflection)."""
        async with self._pool.acquire() as c:
            rows = await c.fetch(
                """
                SELECT id, content, source, importance, tier, consolidated, created_at
                FROM memories
                WHERE user_id = $1 AND valid_until IS NULL
                ORDER BY created_at DESC
                LIMIT $2
                """,
                user_id, limit,
            )
            return [dict(r) for r in rows]

    async def add_consolidated(self, user_id: str, content: str, source: str) -> str:
        """Store a consolidated summary as a Long/Semantic memory (ADD-only)."""
        vec = self._embedder.embed_one(content)
        literal = EmbeddingService.to_pgvector(vec)
        async with self._pool.acquire() as c:
            row = await c.fetchrow(
                """
                INSERT INTO memories
                    (user_id, content, source, embedding, embedding_model, tier, consolidated)
                VALUES ($1, $2, $3, $4::vector, $5, 'long', TRUE)
                RETURNING id
                """,
                user_id, content, source, literal, self._embedder.model_name,
            )
        return str(row["id"])

    async def score_importance(self, memory_id: str, score: float) -> None:
        async with self._pool.acquire() as c:
            await c.execute(
                "UPDATE memories SET importance = $2 WHERE id = $1",
                memory_id, float(score),
            )

    async def log_event(self, user_id: str | None, kind: str, detail: dict) -> None:
        import json
        async with self._pool.acquire() as c:
            await c.execute(
                "INSERT INTO events (user_id, kind, detail) VALUES ($1, $2, $3::jsonb)",
                user_id, kind, json.dumps(detail),
            )
