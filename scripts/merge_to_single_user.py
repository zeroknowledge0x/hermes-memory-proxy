#!/usr/bin/env python3
"""Merge all memory/session/event rows into ONE canonical user (single-user).

D-026. Safe to re-run (idempotent reassignment + exact-dup expire).

Usage:
    python scripts/merge_to_single_user.py
    python scripts/merge_to_single_user.py --canonical 9c5202b3-0c9d-bd91-b8d0-2e24d2d261d3
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))


def _load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


async def main(canonical: str) -> None:
    from memory_proxy.knowledge.embedding import EmbeddingService
    from memory_proxy.memory.repository import MemoryRepository
    from memory_proxy.storage.db import close_pool, init_pool

    dsn = os.environ["DATABASE_URL"]
    pool = await init_pool(dsn)

    async with pool.acquire() as c:
        await c.execute(
            "INSERT INTO users (id) VALUES ($1) ON CONFLICT (id) DO NOTHING",
            canonical,
        )
        # Reassign everything foreign-keyed to users
        mem = await c.execute(
            "UPDATE memories SET user_id = $1 WHERE user_id IS DISTINCT FROM $1",
            canonical,
        )
        sess = await c.execute(
            "UPDATE sessions SET user_id = $1 WHERE user_id IS DISTINCT FROM $1",
            canonical,
        )
        ev = await c.execute(
            "UPDATE events SET user_id = $1 WHERE user_id IS NOT NULL "
            "AND user_id IS DISTINCT FROM $1",
            canonical,
        )

    emb = EmbeddingService(
        os.environ.get(
            "EMBEDDING_MODEL",
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        ),
        int(os.environ.get("EMBEDDING_DIM", "384")),
    )
    repo = MemoryRepository(pool, emb)
    n_exact = await repo.expire_exact_duplicates(canonical)
    n_cons = await repo.expire_old_consolidated(canonical, keep=1)

    async with pool.acquire() as c:
        active = await c.fetchval(
            "SELECT COUNT(*) FROM memories WHERE user_id=$1 AND valid_until IS NULL",
            canonical,
        )
        others = await c.fetchval(
            "SELECT COUNT(*) FROM memories WHERE user_id IS DISTINCT FROM $1 "
            "AND valid_until IS NULL",
            canonical,
        )

    print(
        {
            "canonical": canonical,
            "memories_moved": str(mem),
            "sessions_moved": str(sess),
            "events_moved": str(ev),
            "expired_exact_dupes": n_exact,
            "expired_old_consolidated": n_cons,
            "active_on_canonical": active,
            "active_on_others": others,
        }
    )
    await close_pool()


if __name__ == "__main__":
    _load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--canonical",
        default=os.environ.get(
            "DEFAULT_USER_ID", "9c5202b3-0c9d-bd91-b8d0-2e24d2d261d3"
        ),
        help="UUID of the single brain (default: telegram:5398668166 hash or env)",
    )
    args = ap.parse_args()
    asyncio.run(main(args.canonical))
