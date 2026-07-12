"""Knowledge base repository + retrieval (ARCHITECTURE §5).

Static documents (RFC/docs/PDF) chunked + embedded into knowledge_chunks.
Retrieval is SEPARATE from memory — never mixed in one query.
"""
from __future__ import annotations

from typing import Any

from memory_proxy.knowledge.embedding import EmbeddingService


class KnowledgeRepository:
    def __init__(self, pool, embedder: EmbeddingService):
        self._pool = pool
        self._embedder = embedder

    async def add_document(
        self, title: str, source_type: str, chunks: list[str],
        source_uri: str | None = None,
    ) -> str:
        vecs = self._embedder.embed(chunks)
        async with self._pool.acquire() as c:
            async with c.transaction():
                doc = await c.fetchrow(
                    """
                    INSERT INTO knowledge_documents (title, source_type, source_uri)
                    VALUES ($1, $2, $3) RETURNING id
                    """,
                    title, source_type, source_uri,
                )
                doc_id = doc["id"]
                for i, (chunk, vec) in enumerate(zip(chunks, vecs)):
                    await c.execute(
                        """
                        INSERT INTO knowledge_chunks
                            (document_id, chunk_index, content, embedding, embedding_model)
                        VALUES ($1, $2, $3, $4::vector, $5)
                        """,
                        doc_id, i, chunk,
                        EmbeddingService.to_pgvector(vec), self._embedder.model_name,
                    )
        return str(doc_id)

    async def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        vec = self._embedder.embed_one(query)
        literal = EmbeddingService.to_pgvector(vec)
        async with self._pool.acquire() as c:
            rows = await c.fetch(
                """
                SELECT id, content, embedding <=> $1::vector AS distance
                FROM knowledge_chunks
                ORDER BY embedding <=> $1::vector
                LIMIT $2
                """,
                literal, limit,
            )
        return [
            {"id": str(r["id"]), "content": r["content"],
             "distance": float(r["distance"])}
            for r in rows
        ]
