"""E2E test — closes Phase 1.

Proves the whole pipeline: a fact stated in turn 1 is extracted, stored,
and RETRIEVED into the assembled context of turn 2 (without process
restart). Uses a fake provider (records injected context) + fake extractor
(no real LLM), but REAL Postgres+pgvector + REAL multilingual embeddings.
"""
from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio

from memory_proxy.context.budgeter import TokenBudgeter
from memory_proxy.identity.loader import IdentityLoader
from memory_proxy.knowledge.embedding import EmbeddingService
from memory_proxy.memory.repository import MemoryRepository
from memory_proxy.memory.writer import MemoryWriter
from memory_proxy.pipeline.orchestrator import Orchestrator
from memory_proxy.providers.base import ProviderAdapter
from memory_proxy.storage.db import init_pool, close_pool

DSN = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="TEST_DATABASE_URL not set")


class RecordingProvider(ProviderAdapter):
    """Records the context injected into the final payload."""

    def __init__(self):
        self.last_injected_context = ""
        self.last_payload = None

    async def forward(self, payload, stream):
        self.last_payload = payload
        return {"id": "r", "choices": [{"message": {"content": "ok"}}]}

    def inject_context(self, payload, context_block):
        import copy
        self.last_injected_context = context_block
        p = copy.deepcopy(payload)
        if context_block:
            p["messages"] = [{"role": "system", "content": context_block}] + p.get("messages", [])
        return p

    def extract_latest_user_message(self, payload):
        for m in reversed(payload.get("messages", [])):
            if m.get("role") == "user":
                return m.get("content", "")
        return ""


class FakeExtractor:
    def __init__(self, facts):
        self._facts = facts

    async def extract(self, text, assistant_msg: str = ""):
        return list(self._facts)


@pytest_asyncio.fixture
async def pool():
    p = await init_pool(DSN)
    yield p
    await close_pool()


@pytest_asyncio.fixture(scope="module")
def embedder():
    return EmbeddingService()


@pytest.mark.asyncio
async def test_e2e_fact_remembered_across_turns(pool, embedder, tmp_path):
    uid = str(uuid.uuid4())
    async with pool.acquire() as c:
        await c.execute("INSERT INTO users(id) VALUES($1)", uuid.UUID(uid))

    # identity fixtures
    (tmp_path / "SOUL.md").write_text("I am ZKA.", encoding="utf-8")
    (tmp_path / "USER.md").write_text("User: zk.", encoding="utf-8")
    identity = IdentityLoader(tmp_path)
    identity.load()

    repo = MemoryRepository(pool, embedder)
    extractor = FakeExtractor(["user suka kopi hitam tanpa gula"])
    writer = MemoryWriter(repo, extractor, enabled=True)
    provider = RecordingProvider()

    orch = Orchestrator(
        provider,
        identity=identity,
        memory_repo=repo,
        writer=writer,
        budgeter=TokenBudgeter(8192, 0.25),
        default_user_id=uid,
    )

    # --- Turn 1: user states a fact ---
    writer.start()
    await orch.handle({
        "model": "m",
        "messages": [{"role": "user", "content": "gua suka kopi hitam banget"}],
    })
    await writer.stop()  # drain queue -> fact persisted (D-010)

    # --- Turn 2: user asks something related ---
    await orch.handle({
        "model": "m",
        "messages": [{"role": "user", "content": "minuman apa yang cocok buat gua?"}],
    })

    ctx = provider.last_injected_context
    # SOUL/USER present + the remembered fact retrieved into context
    assert "ZKA" in ctx
    assert "kopi" in ctx.lower()
    assert "MEMORY" in ctx
