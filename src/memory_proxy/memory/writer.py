"""Async memory writer (ARCHITECTURE §9, D-007/D-010).

Design:
- Single-writer queue: one async worker consumes and writes sequentially,
  avoiding read/write races between turns (D-010).
- Hybrid extraction: heuristic gate -> pluggable LLM extractor -> dedupe
  (cosine) -> ADD-only store. Extractor is injectable so tests / different
  providers plug in without touching the core (model-agnostic).
- Fire-and-forget per turn; extraction is OPTIONAL (can be disabled).
"""
from __future__ import annotations

import asyncio
import re
from typing import Awaitable, Callable, Protocol

from memory_proxy.memory.repository import MemoryRepository


class FactExtractor(Protocol):
    async def extract(self, text: str) -> list[str]:
        """Return a list of short standalone facts from the text."""
        ...


# Heuristic gate: only bother the LLM when a turn *looks* like it carries a
# durable fact. Bilingual triggers (ID + EN). Cheap pre-filter (D-007).
_TRIGGER = re.compile(
    r"\b(nama|gua|gue|saya|aku|suka|benci|tinggal|kerja|umur|punya|"
    r"pakai|prefer|selalu|jangan|"
    r"my name|i am|i'm|i like|i prefer|i live|i work|i hate|i have|always|never)\b",
    re.IGNORECASE,
)


def looks_like_fact(text: str) -> bool:
    return bool(_TRIGGER.search(text or ""))


class MemoryWriter:
    def __init__(
        self,
        repo: MemoryRepository,
        extractor: FactExtractor | None = None,
        enabled: bool = True,
        dedupe_threshold: float = 0.10,  # cosine DISTANCE; < => duplicate
    ):
        self._repo = repo
        self._extractor = extractor
        self._enabled = enabled and extractor is not None
        self._dedupe_threshold = dedupe_threshold
        self._queue: asyncio.Queue[tuple[str, str, str]] = asyncio.Queue()
        self._worker: asyncio.Task | None = None

    def start(self) -> None:
        if self._worker is None:
            self._worker = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._worker:
            await self._queue.join()
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
            self._worker = None

    def enqueue(self, user_id: str, text: str, assistant_msg: str = "") -> None:
        """Fire-and-forget: drop a turn into the queue. Non-blocking."""
        if not self._enabled or not looks_like_fact(text):
            return
        self._queue.put_nowait((user_id, text, assistant_msg))

    async def _run(self) -> None:
        while True:
            user_id, text, assistant_msg = await self._queue.get()
            try:
                await self._process(user_id, text, assistant_msg)
            except Exception:
                pass  # never let one bad turn kill the worker
            finally:
                self._queue.task_done()

    async def _process(self, user_id: str, text: str, assistant_msg: str = "") -> int:
        assert self._extractor is not None
        facts = await self._extractor.extract(text, assistant_msg)
        written = 0
        for fact in facts:
            fact = (fact or "").strip()
            if not fact:
                continue
            if await self._is_duplicate(user_id, fact):
                continue
            new_id = await self._repo.add_fact(user_id, fact, source="extractor")
            if new_id:  # None => exact-text duplicate already in DB
                written += 1
        return written

    async def _is_duplicate(self, user_id: str, fact: str) -> bool:
        """True if an active near-duplicate exists (cosine distance gate).

        Threshold is cosine DISTANCE (0 = identical). 0.10 ≈ very similar;
        also catch exact string via repository.add_fact.
        """
        hits = await self._repo.search(user_id, fact, limit=1)
        if not hits:
            return False
        return hits[0]["distance"] < self._dedupe_threshold

    # Test/E2E helper: process a turn synchronously (await write done).
    async def process_now(self, user_id: str, text: str, assistant_msg: str = "") -> int:
        if not self._enabled or not looks_like_fact(text):
            return 0
        return await self._process(user_id, text, assistant_msg)
