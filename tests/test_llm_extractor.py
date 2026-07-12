"""Tests for LLMFactExtractor — JSON fallback parser (no network) +
mocked extract flow via respx."""
from __future__ import annotations

import pytest

from memory_proxy.memory.llm_extractor import LLMFactExtractor, extract_json
from memory_proxy.providers.credentials import CredentialProvider


# ---------- robust JSON parser (no network) ----------

def test_extract_json_clean():
    assert extract_json('{"facts": ["a", "b"]}') == {"facts": ["a", "b"]}


def test_extract_json_markdown_fenced():
    raw = '```json\n{"facts": ["gua suka kopi"]}\n```'
    assert extract_json(raw) == {"facts": ["gua suka kopi"]}


def test_extract_json_with_preamble():
    raw = 'Sure! Here you go: {"facts": ["nama user Budi"]} hope that helps'
    assert extract_json(raw) == {"facts": ["nama user Budi"]}


def test_extract_json_garbage_returns_empty():
    assert extract_json("totally not json") == {"facts": []}


# ---------- extract() with mocked HTTP ----------

@pytest.mark.asyncio
async def test_extract_calls_llm_and_parses():
    respx = pytest.importorskip("respx")
    import httpx

    ex = LLMFactExtractor(
        base_url="http://fake/v1",
        credentials=CredentialProvider(api_key="k"),
        model="mini",
    )
    with respx.mock:
        respx.post("http://fake/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={"choices": [{"message": {
                    "content": '{"facts": ["user suka kopi hitam"]}'}}]},
            )
        )
        facts = await ex.extract("gua suka kopi hitam", "oke, dicatat")
    assert facts == ["user suka kopi hitam"]


@pytest.mark.asyncio
async def test_extract_network_error_returns_empty():
    respx = pytest.importorskip("respx")
    import httpx

    ex = LLMFactExtractor(
        base_url="http://fake/v1",
        credentials=CredentialProvider(api_key="k"),
    )
    with respx.mock:
        respx.post("http://fake/v1/chat/completions").mock(
            side_effect=httpx.ConnectError("boom")
        )
        facts = await ex.extract("whatever")
    assert facts == []  # best-effort, never raises
