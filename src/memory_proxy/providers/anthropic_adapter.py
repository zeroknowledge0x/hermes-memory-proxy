"""Anthropic provider adapter (Messages API format).

Unlike OpenAI-compat, Anthropic:
- puts `system` at the TOP LEVEL, not in messages
- uses `max_tokens` REQUIRED at top level
- content is a list of blocks, not a string

The orchestrator only talks to the ProviderAdapter interface, so this
adapter translates the canonical OpenAI-shaped payload to Anthropic wire
format. Streaming = raw SSE passthrough.
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from memory_proxy.providers.base import ProviderAdapter


class AnthropicAdapter(ProviderAdapter):
    def __init__(self, base_url: str, api_key: str, model: str | None = None,
                 timeout: float = 60.0):
        # Anthropic SDK talks to /v1/messages
        self._base = base_url.rstrip("/").replace("/v1", "") or "https://api.anthropic.com"
        self._base = self._base.rstrip("/") + "/v1"
        self._key = api_key
        self._model = model or "claude-3-5-sonnet-latest"
        self._timeout = timeout

    async def forward(self, payload: dict[str, Any], stream: bool) -> Any:
        url = f"{self._base}/messages"
        headers = {
            "x-api-key": self._key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        if stream:
            headers["accept"] = "text/event-stream"
        body = json.loads(json.dumps(payload))  # deep copy via serialize
        body.setdefault("stream", stream)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(url, json=body, headers=headers)
            if stream:
                return self._aiter_bytes(resp)
            resp.raise_for_status()
            return self._normalize(resp.json())

    async def _aiter_bytes(self, resp):
        async for chunk in resp.aiter_bytes():
            yield chunk

    def inject_context(self, payload: dict[str, Any], context_block: str) -> dict[str, Any]:
        """Anthropic keeps `system` at top level and out of messages."""
        import copy
        p = copy.deepcopy(payload)
        if context_block:
            existing = p.get("system", "")
            p["system"] = (existing + "\n\n" + context_block).strip() if existing else context_block
        # Anthropic requires max_tokens
        p.setdefault("max_tokens", 4096)
        return p

    def extract_latest_user_message(self, payload: dict[str, Any]) -> str:
        for m in reversed(payload.get("messages", [])):
            if m.get("role") == "user":
                c = m.get("content", "")
                return c if isinstance(c, str) else json.dumps(c, default=str)
        return ""

    @staticmethod
    def _normalize(resp: dict) -> dict:
        """Convert Anthropic Messages response -> OpenAI ChatCompletion shape
        (so the rest of the pipeline/SDK stays OpenAI-shaped)."""
        text = "".join(
            b.get("text", "") for b in resp.get("content", [])
            if b.get("type") == "text"
        )
        return {
            "id": resp.get("id", "anthropic"),
            "object": "chat.completion",
            "model": resp.get("model", ""),
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": resp.get("stop_reason", "stop"),
            }],
            "usage": resp.get("usage", {}),
        }
