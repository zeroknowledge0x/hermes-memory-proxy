"""Knowledge ingest — chunk + embed static documents into knowledge_chunks.

Supports: .txt / .md (text split) and .pdf (via pypdf if installed).
Chunks are overlap-free with a small tail overlap for coherence.

Usage:
    python -m memory_proxy.knowledge.ingest path/to/doc.md --title "RFC X"
    python -m memory_proxy.knowledge.ingest ./docs --title "Project docs"
"""
from __future__ import annotations

import argparse
import asyncpg
import os
import sys

# make src importable when run as a module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))

from memory_proxy.knowledge.embedding import EmbeddingService  # noqa: E402
from memory_proxy.knowledge.repository import KnowledgeRepository  # noqa: E402
from memory_proxy.storage.db import init_pool, close_pool  # noqa: E402


CHUNK_CHARS = 1200
OVERLAP_CHARS = 150


def chunk_text(text: str, chunk=CHUNK_CHARS, overlap=OVERLAP_CHARS) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk:
        return [text]
    out = []
    start = 0
    while start < len(text):
        end = min(start + chunk, len(text))
        out.append(text[start:end])
        if end == len(text):
            break
        start = max(end - overlap, start + 1)
    return out


def read_file(path: str) -> str:
    if path.lower().endswith(".pdf"):
        try:
            from pypdf import PdfReader
        except ImportError:
            raise SystemExit("pypdf not installed; pip install pypdf")
        r = PdfReader(path)
        return "\n".join(p.extract_text() or "" for p in r.pages)
    return open(path, encoding="utf-8").read()


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", help="file or directory")
    ap.add_argument("--title", required=True)
    ap.add_argument("--source-type", default="docs")
    ap.add_argument("--db", default=os.environ.get("DATABASE_URL"))
    args = ap.parse_args()
    if not args.db:
        raise SystemExit("DATABASE_URL not set")

    paths = []
    if os.path.isdir(args.path):
        for f in sorted(os.listdir(args.path)):
            if f.lower().endswith((".txt", ".md", ".pdf")):
                paths.append(os.path.join(args.path, f))
    else:
        paths.append(args.path)

    embedder = EmbeddingService()
    pool = await init_pool(args.db)
    repo = KnowledgeRepository(pool, embedder)
    count = 0
    for p in paths:
        chunks = chunk_text(read_file(p))
        doc_title = args.title if len(paths) == 1 else f"{args.title} :: {os.path.basename(p)}"
        await repo.add_document(
            doc_title, args.source_type, chunks, source_uri=p
        )
        count += len(chunks)
        print(f"  ingested {p}: {len(chunks)} chunks")
    await close_pool()
    print(f"done. {count} chunks total.")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
