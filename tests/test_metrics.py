"""Metrics tests (no DB)."""
from __future__ import annotations

import json

from memory_proxy.telemetry.metrics import RequestMetrics, Timer


def test_metrics_json_valid():
    m = RequestMetrics(
        session_id="s1", provider="nous", context_tokens_used=412,
        context_budget=2000, memory_chunks_retrieved=3,
        knowledge_chunks_retrieved=2, facts_written=1,
        latency_ms=890, streamed=True,
    )
    data = json.loads(m.to_json())
    assert data["provider"] == "nous"
    assert data["streamed"] is True
    assert data["timestamp"].endswith("Z")
    # all §11 keys present
    for k in ("timestamp", "session_id", "provider", "context_tokens_used",
              "context_budget", "memory_chunks_retrieved",
              "knowledge_chunks_retrieved", "facts_written", "latency_ms",
              "streamed"):
        assert k in data


def test_timer_measures():
    with Timer() as t:
        sum(range(1000))
    assert t.ms >= 0
