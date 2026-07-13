#!/usr/bin/env python3
"""Expire exact-text duplicates + keep newest consolidated profile per user.

Usage (from repo root, with DATABASE_URL in env or .env):
    python scripts/dedupe_memories.py
    python scripts/dedupe_memories.py --user telegram:5398668166
"""
from __future__ import annotations
import argparse, asyncio, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

def _load_env():
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

async def main(user: str | None):
    from memory_proxy.knowledge.embedding import EmbeddingService
    from memory_proxy.memory.repository import MemoryRepository
    from memory_proxy.storage.db import init_pool, close_pool
    from memory_proxy.pipeline.orchestrator import Orchestrator

    dsn = os.environ["DATABASE_URL"]
    pool = await init_pool(dsn)
    emb = EmbeddingService(
        os.environ.get("EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"),
        int(os.environ.get("EMBEDDING_DIM", "384")),
    )
    repo = MemoryRepository(pool, emb)
    if user:
        orch = Orchestrator(provider=None)  # type: ignore
        uid = orch._resolve_user_id({"user": user})
        n1 = await repo.expire_exact_duplicates(uid)
        n2 = await repo.expire_old_consolidated(uid, keep=1)
        print({"user": user, "uid": uid, "expired_exact": n1, "expired_old_cons": n2})
    else:
        n1 = await repo.expire_exact_duplicates(None)
        # all users that have consolidated
        async with pool.acquire() as c:
            rows = await c.fetch(
                "SELECT DISTINCT user_id FROM memories WHERE valid_until IS NULL AND (source='consolidated' OR consolidated)"
            )
        n2 = 0
        for r in rows:
            n2 += await repo.expire_old_consolidated(str(r["user_id"]), keep=1)
        print({"expired_exact": n1, "expired_old_cons": n2})
    await close_pool()

if __name__ == "__main__":
    _load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default="")
    args = ap.parse_args()
    asyncio.run(main(args.user or None))
