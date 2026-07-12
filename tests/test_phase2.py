"""Phase 2 tests — Anthropic adapter + provider-swap (no code change
outside providers/).

Uses a fake Anthropic upstream (respx) so no real API key needed.
"""
from __future__ import annotations

import pytest

import httpx

from memory_proxy.providers.anthropic_adapter import AnthropicAdapter
from memory_proxy.providers.openai_compatible_adapter import OpenAICompatibleAdapter


# ---------- Anthropic wire-format translation ----------

@pytest.mark.asyncio
async def test_anthropic_inject_context_moves_system_top_level():
    respx = pytest.importorskip("respx")
    import httpx
    import json

    adapter = AnthropicAdapter(base_url="http://fake", api_key="k", model="claude-x")
    captured = {}

    async def handler(request):
        captured["body"] = json.loads(request.content)
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json={
            "id": "msg_1", "model": "claude-x",
            "content": [{"type": "text", "text": "hai"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 5, "output_tokens": 3},
        })

    with respx.mock:
        respx.post("http://fake/v1/messages").mock(side_effect=handler)
        result = await adapter.forward(
            adapter.inject_context(
                {"model": "claude-x", "messages": [{"role": "user", "content": "halo"}]},
                "CONTEXT BLOCK HERE",
            ),
            stream=False,
        )

    assert "system" in captured["body"]
    assert captured["body"]["system"] == "CONTEXT BLOCK HERE"
    # system must NOT be in messages
    assert all(m.get("role") != "system" for m in captured["body"]["messages"])
    # max_tokens required by Anthropic
    assert captured["body"]["max_tokens"] == 4096
    # normalized back to OpenAI shape
    assert result["choices"][0]["message"]["content"] == "hai"
    assert captured["headers"]["x-api-key"] == "k"


@pytest.mark.asyncio
async def test_anthropic_stream_passthrough():
    respx = pytest.importorskip("respx")
    import httpx as _hx

    adapter = AnthropicAdapter(base_url="http://fake", api_key="k")
    chunks = [
        b'event: message_start\r\ndata: {"x":1}\r\n\r\n',
        b'data: {"x":2}\r\n\r\n',
    ]

    class _SSE(_hx.AsyncByteStream):
        async def __aiter__(self):
            for c in chunks:
                yield c

    with respx.mock:
        respx.post("http://fake/v1/messages").mock(
            return_value=httpx.Response(200, stream=_SSE(),
                                        headers={"content-type": "text/event-stream"})
        )
        out = []
        async for c in await adapter.forward({"messages": []}, stream=True):
            out.append(c)
    assert b"".join(out) == b"".join(chunks)


# ---------- provider swap: orchestrator is provider-agnostic ----------

def test_orchestrator_accepts_anthropic_without_changes():
    """The orchestrator imports only the ProviderAdapter interface; swapping
    the concrete class requires NO change outside providers/."""
    orch = __import__(
        "memory_proxy.pipeline.orchestrator", fromlist=["Orchestrator"]
    ).Orchestrator
    a = AnthropicAdapter("http://x", "k")
    o = OpenAICompatibleAdapter("http://y", "k")
    # both construct an Orchestrator identically
    assert orch(a) is not None
    assert orch(o) is not None
