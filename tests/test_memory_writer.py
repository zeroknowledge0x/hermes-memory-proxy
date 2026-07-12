"""Phase 1.5 tests — async memory writer.

DB-backed (skips without TEST_DATABASE_URL). Uses a FAKE extractor so no
real LLM is needed — proves the queue/gate/dedupe machinery.
"""
from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio

from memory_proxy.knowledge.embedding import EmbeddingService
from memory_proxy.memory.repository import MemoryRepository
from memory_proxy.memory.writer import MemoryWriter, looks_like_fact
from memory_proxy.storage.db import init_pool, close_pool

DSN = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="TEST_DATABASE_URL not set")


class FakeExtractor:
    """Returns canned facts; records call count."""

    def __init__(self, facts):
        self._facts = facts
        self.calls = 0

    async def extract(self, text: str, assistant_msg: str = ""):
        self.calls += 1
        return list(self._facts)


@pytest_asyncio.fixture
async def pool():
    p = await init_pool(DSN)
    yield p
    await close_pool()


@pytest_asyncio.fixture(scope="module")
def embedder():
    return EmbeddingService()


async def _new_user(pool):
    uid = str(uuid.uuid4())
    async with pool.acquire() as c:
        await c.execute("INSERT INTO users(id) VALUES($1)", uuid.UUID(uid))
    return uid


# ---------- heuristic gate (no DB) ----------

def test_gate_triggers_on_fact_like():
    assert looks_like_fact("nama gua Budi")
    assert looks_like_fact("gua suka kopi hitam")
    assert looks_like_fact("my name is Budi")


def test_gate_skips_non_fact():
    assert not looks_like_fact("oke sip lanjut")
    assert not looks_like_fact("terima kasih ya")


# ---------- writer ----------

@pytest.mark.asyncio
async def test_writer_stores_extracted_fact(pool, embedder):
    uid = await _new_user(pool)
    repo = MemoryRepository(pool, embedder)
    extractor = FakeExtractor(["user suka kopi hitam tanpa gula"])
    writer = MemoryWriter(repo, extractor, enabled=True)

    n = await writer.process_now(uid, "gua suka kopi hitam banget")
    assert n == 1
    res = await repo.search(uid, "minuman favorit", limit=1)
    assert "kopi" in res[0]["content"].lower()


@pytest.mark.asyncio
async def test_writer_dedupes(pool, embedder):
    uid = await _new_user(pool)
    repo = MemoryRepository(pool, embedder)
    extractor = FakeExtractor(["user tinggal di Jakarta Selatan"])
    writer = MemoryWriter(repo, extractor, enabled=True)

    n1 = await writer.process_now(uid, "gua tinggal di Jaksel")
    n2 = await writer.process_now(uid, "gua tinggal di Jaksel")  # same fact again
    assert n1 == 1
    assert n2 == 0  # deduped, not written twice
    async with pool.acquire() as c:
        cnt = await c.fetchval("SELECT count(*) FROM memories WHERE user_id=$1",
                               uuid.UUID(uid))
    assert cnt == 1


@pytest.mark.asyncio
async def test_writer_gate_skips_llm(pool, embedder):
    uid = await _new_user(pool)
    repo = MemoryRepository(pool, embedder)
    extractor = FakeExtractor(["should not happen"])
    writer = MemoryWriter(repo, extractor, enabled=True)

    n = await writer.process_now(uid, "oke sip")  # no trigger
    assert n == 0
    assert extractor.calls == 0  # LLM never called (cost saved)


@pytest.mark.asyncio
async def test_writer_disabled_noop(pool, embedder):
    uid = await _new_user(pool)
    repo = MemoryRepository(pool, embedder)
    writer = MemoryWriter(repo, extractor=None, enabled=True)  # no extractor
    n = await writer.process_now(uid, "nama gua Budi")
    assert n == 0


@pytest.mark.asyncio
async def test_writer_queue_single_writer(pool, embedder):
    """enqueue() + await queue drain -> fact is persisted (D-010)."""
    uid = await _new_user(pool)
    repo = MemoryRepository(pool, embedder)
    extractor = FakeExtractor(["user kerja sebagai software engineer"])
    writer = MemoryWriter(repo, extractor, enabled=True)
    writer.start()
    writer.enqueue(uid, "gua kerja sebagai software engineer", "")
    await writer.stop()  # drains queue then stops

    res = await repo.search(uid, "pekerjaan user", limit=1)
    assert res and "engineer" in res[0]["content"].lower()
