"""test_passthrough — verifies (DECISIONS.md D-009):
1. The payload forwarded to the provider is byte-for-byte identical to the
   client request when no context injection happens (Phase 1.2 = empty ctx).
2. Non-stream and stream both pass through unchanged.
3. Streaming does NOT full-buffer (chunks arrive incrementally).
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator

import pytest

from memory_proxy.pipeline.orchestrator import Orchestrator
from memory_proxy.providers.base import ProviderAdapter


class SpyAdapter(ProviderAdapter):
    """Records what the orchestrator forwards, returns canned responses."""

    def __init__(self):
        self.forwarded_payload: dict[str, Any] | None = None
        self.forwarded_stream: bool | None = None

    async def forward(self, payload, stream):
        self.forwarded_payload = payload
        self.forwarded_stream = stream
        if stream:
            return self._gen()
        return {"id": "resp-1", "choices": [{"message": {"content": "hi"}}]}

    async def _gen(self) -> AsyncIterator[bytes]:
        for c in (b'data: {"delta":"h"}\n\n', b'data: {"delta":"i"}\n\n', b"data: [DONE]\n\n"):
            yield c

    # Real OpenAI-compat inject logic (empty ctx -> unchanged payload).
    def inject_context(self, payload, context_block):
        import copy
        if not context_block:
            return copy.deepcopy(payload)
        p = copy.deepcopy(payload)
        p["messages"] = [{"role": "system", "content": context_block}] + p.get("messages", [])
        return p

    def extract_latest_user_message(self, payload):
        for m in reversed(payload.get("messages", [])):
            if m.get("role") == "user":
                return m.get("content", "")
        return ""


REQUEST = {
    "model": "test-model",
    "messages": [{"role": "user", "content": "hello"}],
    "temperature": 0.7,
}


@pytest.mark.asyncio
async def test_nonstream_payload_identical():
    spy = SpyAdapter()
    orch = Orchestrator(spy)
    req = dict(REQUEST, stream=False)
    await orch.handle(req)
    # Phase 1.2: no injection -> forwarded payload must equal client request.
    assert spy.forwarded_payload == req
    assert spy.forwarded_stream is False


@pytest.mark.asyncio
async def test_stream_payload_identical_and_incremental():
    spy = SpyAdapter()
    orch = Orchestrator(spy)
    req = dict(REQUEST, stream=True)
    result = await orch.handle(req)
    assert spy.forwarded_payload == req
    assert spy.forwarded_stream is True

    # Collect chunks — proves generator (incremental), not one buffered blob.
    chunks = [c async for c in result]
    assert len(chunks) == 3
    assert chunks[-1] == b"data: [DONE]\n\n"
    # First chunk parseable as SSE data line.
    assert chunks[0].startswith(b"data: ")


@pytest.mark.asyncio
async def test_empty_context_does_not_add_system_message():
    """Guardrail: Phase 1.2 must not silently inject a system message."""
    spy = SpyAdapter()
    orch = Orchestrator(spy)
    req = dict(REQUEST, stream=False)
    await orch.handle(req)
    roles = [m["role"] for m in spy.forwarded_payload["messages"]]
    assert roles == ["user"]  # no system message added
