"""Postgres connection pool (asyncpg)."""
from __future__ import annotations

import asyncpg

_pool: asyncpg.Pool | None = None


async def init_pool(dsn: str) -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(dsn, min_size=1, max_size=10)
    return _pool


async def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Pool not initialized — call init_pool() first")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
