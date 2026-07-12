"""OpenAI-compatible provider adapter.

Canonical wire format (DECISIONS.md D-002). Forwards to the upstream
OpenAI-compatible endpoint. Streaming = raw SSE byte passthrough so the
downstream OpenAI SDK (Hermes) parses it unchanged (D-002).
"""
from __future__ import annotations

import copy
from typing import Any, AsyncIterator

import httpx

from memory_proxy.providers.base import ProviderAdapter
from memory_proxy.providers.credentials import CredentialProvider


class OpenAICompatibleAdapter(ProviderAdapter):
    def __init__(self, base_url: str, credentials: CredentialProvider,
                 timeout: float = 300.0):
        self._base_url = base_url.rstrip("/")
        self._creds = credentials
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        h.update(self._creds.auth_header())
        return h

    async def forward(
        self, payload: dict[str, Any], stream: bool
    ) -> "AsyncIterator[bytes] | dict[str, Any]":
        url = f"{self._base_url}/chat/completions"
        if stream:
            return self._stream(url, payload)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(url, json=payload, headers=self._headers())
            # Stale OAuth token -> refresh once and retry (D-020)
            if resp.status_code in (401, 403, 404) and self._creds.mode == "oauth":
                await self._creds.refresh_now()
                resp = await client.post(url, json=payload, headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def _stream(
        self, url: str, payload: dict[str, Any]
    ) -> AsyncIterator[bytes]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async with client.stream(
                "POST", url, json=payload, headers=self._headers()
            ) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes():
                    yield chunk

    def inject_context(
        self, payload: dict[str, Any], context_block: str
    ) -> dict[str, Any]:
        """Prepend a system message carrying the assembled context.
        Returns a new payload (no in-place mutation)."""
        if not context_block:
            return copy.deepcopy(payload)
        new_payload = copy.deepcopy(payload)
        messages = new_payload.get("messages", [])
        system_msg = {"role": "system", "content": context_block}
        new_payload["messages"] = [system_msg] + messages
        return new_payload

    async def list_models(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self._base_url}/models", headers=self._creds.auth_header()
            )
            resp.raise_for_status()
            return resp.json().get("data", [])

    async def get_model(self, model: str) -> dict[str, Any] | None:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self._base_url}/models/{model}", headers=self._creds.auth_header()
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()

    def extract_latest_user_message(self, payload: dict[str, Any]) -> str:
        for msg in reversed(payload.get("messages", [])):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, list):
                    # OpenAI content-parts format
                    return " ".join(
                        p.get("text", "")
                        for p in content
                        if isinstance(p, dict) and p.get("type") == "text"
                    )
                return content or ""
        return ""
