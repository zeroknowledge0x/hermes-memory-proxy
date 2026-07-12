"""Knowledge ingest chunking tests (no DB)."""
from __future__ import annotations

from memory_proxy.knowledge.ingest import chunk_text


def test_chunk_short_returns_one():
    assert chunk_text("halo dunia pendek") == ["halo dunia pendek"]


def test_chunk_long_splits():
    text = "x" * 3000
    chunks = chunk_text(text)
    assert len(chunks) > 1
    # no empty chunks
    assert all(c.strip() for c in chunks)
    # overlap means adjacent chunks share tail/head
    assert chunks[0][-150:] in text


def test_chunk_empty():
    assert chunk_text("") == []
    assert chunk_text("   \n  ") == []
