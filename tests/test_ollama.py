"""Phase 2 — Ollama verification (OpenAI-compat mode).

Ollama is not installed on this VPS, so we verify the OpenAI-compatible
adapter against Ollama's *known* wire quirks via a simulated upstream:
- streams `data: {...}` chunks then `data: [DONE]`
- sometimes emits chunks with empty/omitted `choices` (keep-alive)
- content may arrive as a string (not list) — same as OpenAI, so our
  passthrough already handles it.

This proves the proxy does not assume anything OpenAI-specific beyond the
SSE envelope, so Ollama (and vLLM/LM Studio) work via the same adapter.
"""
from __future__ import annotations

import pytest

from memory_proxy.providers.credentials import CredentialProvider
from memory_proxy.providers.openai_compatible_adapter import OpenAICompatibleAdapter


def _adapter():
    return OpenAICompatibleAdapter(
        base_url="http://ollama:11434/v1", credentials=CredentialProvider(api_key="x")
    )


@pytest.mark.asyncio
async def test_ollama_style_stream_passthrough():
    respx = pytest.importorskip("respx")
    import httpx

    adapter = _adapter()
    raw = (
        b'data: {"id":"1","choices":[{"delta":{"content":"hai"}}]}\n\n'
        b'data: {"id":"1","choices":[]}\n\n'          # keep-alive, no choices
        b'data: [DONE]\n\n'
    )

    class _SSE(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield raw

    captured_url = {}

    with respx.mock:
        def cb(request):
            captured_url["url"] = str(request.url)
            return httpx.Response(200, stream=_SSE(),
                                  headers={"content-type": "text/event-stream"})
        respx.post("http://ollama:11434/v1/chat/completions").mock(side_effect=cb)
        out = []
        async for c in await adapter.forward(
            {"model": "llama3", "messages": [{"role": "user", "content": "hi"}]},
            stream=True,
        ):
            out.append(c)
    joined = b"".join(out)
    assert b"hai" in joined
    assert b"[DONE]" in joined
    assert captured_url["url"].endswith("/v1/chat/completions")


@pytest.mark.asyncio
async def test_ollama_non_stream_json_ok():
    respx = pytest.importorskip("respx")
    import httpx

    adapter = _adapter()
    with respx.mock:
        respx.post("http://ollama:11434/v1/chat/completions").mock(
            return_value=httpx.Response(200, json={
                "id": "1", "object": "chat.completion",
                "choices": [{"message": {"role": "assistant", "content": "halo"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            })
        )
        result = await adapter.forward(
            {"model": "llama3", "messages": [{"role": "user", "content": "hi"}]},
            stream=False,
        )
    assert result["choices"][0]["message"]["content"] == "halo"
