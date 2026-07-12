"""Live retrieval tests against a real Postgres+pgvector.

Skips automatically if TEST_DATABASE_URL is not set, so CI without a DB
still runs the rest of the suite.
"""
from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio

from memory_proxy.knowledge.embedding import EmbeddingService
from memory_proxy.knowledge.repository import KnowledgeRepository
from memory_proxy.memory.repository import MemoryRepository
from memory_proxy.storage.db import init_pool, close_pool

DSN = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="TEST_DATABASE_URL not set")


@pytest_asyncio.fixture
async def pool():
    p = await init_pool(DSN)
    yield p
    await close_pool()


@pytest_asyncio.fixture(scope="module")
def embedder():
    return EmbeddingService()


@pytest.mark.asyncio
async def test_memory_search_orders_by_similarity(pool, embedder):
    uid = str(uuid.uuid4())
    async with pool.acquire() as c:
        await c.execute("INSERT INTO users(id, display_name) VALUES($1,'t')", uuid.UUID(uid))
    repo = MemoryRepository(pool, embedder)
    # Multilingual model (D-014) — memory stored & queried in Bahasa Indonesia.
    await repo.add_fact(uid, "user suka kopi hitam tanpa gula")
    await repo.add_fact(uid, "user tinggal di Jakarta Selatan")
    await repo.add_fact(uid, "user kerja sebagai software engineer")

    res = await repo.search(uid, "minuman favorit user apa?", limit=3)
    assert len(res) == 3
    # most similar should be the coffee fact
    assert "kopi" in res[0]["content"].lower()
    # distances sorted ascending
    dists = [r["distance"] for r in res]
    assert dists == sorted(dists)


@pytest.mark.asyncio
async def test_memory_filtered_by_user(pool, embedder):
    uid_a, uid_b = str(uuid.uuid4()), str(uuid.uuid4())
    async with pool.acquire() as c:
        await c.execute("INSERT INTO users(id) VALUES($1),($2)",
                        uuid.UUID(uid_a), uuid.UUID(uid_b))
    repo = MemoryRepository(pool, embedder)
    await repo.add_fact(uid_a, "fakta rahasia milik user A")
    res_b = await repo.search(uid_b, "fakta apa aja", limit=5)
    assert res_b == []  # user B sees nothing of user A


@pytest.mark.asyncio
async def test_memory_and_knowledge_never_mixed(pool, embedder):
    """Core guardrail (ARCHITECTURE §5): a memory query returns ZERO
    knowledge chunks and vice-versa."""
    uid = str(uuid.uuid4())
    async with pool.acquire() as c:
        await c.execute("INSERT INTO users(id) VALUES($1)", uuid.UUID(uid))
    mem = MemoryRepository(pool, embedder)
    kb = KnowledgeRepository(pool, embedder)

    await mem.add_fact(uid, "HNSW index dipakai di pgvector proyek ini")
    await kb.add_document(
        "pgvector docs", "docs",
        ["HNSW adalah algoritma approximate nearest neighbor untuk vector search"],
    )

    mem_res = await mem.search(uid, "HNSW index", limit=5)
    kb_res = await kb.search("HNSW index", limit=5)

    mem_ids = {r["id"] for r in mem_res}
    kb_ids = {r["id"] for r in kb_res}
    # disjoint id spaces — no cross-contamination
    assert mem_ids.isdisjoint(kb_ids)
    assert all("dipakai di pgvector proyek" in r["content"] for r in mem_res)
    assert all("approximate nearest neighbor" in r["content"] for r in kb_res)
