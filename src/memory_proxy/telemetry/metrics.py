"""Metrics — one JSON record per request (ARCHITECTURE §11)."""
from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


@dataclass
class RequestMetrics:
    session_id: str = ""
    provider: str = ""
    context_tokens_used: int = 0
    context_budget: int = 0
    memory_chunks_retrieved: int = 0
    knowledge_chunks_retrieved: int = 0
    facts_written: int = 0
    latency_ms: int = 0
    streamed: bool = False
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    def emit(self, stream=sys.stdout) -> None:
        stream.write(self.to_json() + "\n")


class Timer:
    """Context manager -> elapsed milliseconds."""

    def __enter__(self):
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.ms = int((time.perf_counter() - self._t0) * 1000)
        return False
