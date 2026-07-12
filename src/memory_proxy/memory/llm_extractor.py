"""LLM-based fact extractor (D-007).

Uses a small/cheap model via an OpenAI-compatible endpoint to extract
short standalone facts from a turn. Robust JSON parsing with fallback
(mem0-style) because small/local models (Ollama) often emit malformed
JSON. Model-agnostic: talks OpenAI Chat Completions only, and uses the
same CredentialProvider as the forward path (so OAuth/API-key both work).
"""
from __future__ import annotations

import json
import re

import httpx

from memory_proxy.providers.credentials import CredentialProvider

_SYSTEM = (
    "You extract durable personal facts about the user from a conversation turn. "
    "Return ONLY a JSON object: {\"facts\": [\"fact 1\", \"fact 2\"]}. "
    "Each fact must be a short standalone statement (preferences, identity, "
    "stable facts). If there are no durable facts, return {\"facts\": []}. "
    "Preserve the user's original language."
)


def extract_json(text: str) -> dict:
    """Best-effort JSON extraction from a possibly-messy LLM response."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return {"facts": []}


class LLMFactExtractor:
    def __init__(
        self,
        base_url: str,
        credentials: CredentialProvider,
        model: str = "tencent/hy3:free",
        timeout: float = 30.0,
    ):
        self._base_url = base_url.rstrip("/")
        self._creds = credentials
        self._model = model
        self._timeout = timeout

    async def extract(self, user_msg: str, assistant_msg: str = "") -> list[str]:
        turn = f"User: {user_msg}\n"
        if assistant_msg:
            turn += f"Assistant: {assistant_msg}\n"
        turn += (
            "Extract any durable facts about the user from the above. "
            "Ignore one-off requests or chit-chat."
        )
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": turn},
            ],
            "temperature": 0,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers=self._creds.auth_header(),
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
        except Exception:
            return []  # extraction is best-effort; never break the turn

        data = extract_json(content)
        facts = data.get("facts", [])
        return [f.strip() for f in facts if isinstance(f, str) and f.strip()]

    async def summarise(self, instr: str, text: str) -> str | None:
        """Cheap-model summarisation for the consolidation loop (D-023)."""
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": instr},
                {"role": "user", "content": text},
            ],
            "temperature": 0,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers=self._creds.auth_header(),
                )
                # Stale OAuth token -> refresh once and retry (D-020)
                if resp.status_code in (401, 403, 404) and self._creds.mode == "oauth":
                    await self._creds.refresh_now()
                    resp = await client.post(
                        f"{self._base_url}/chat/completions",
                        json=payload,
                        headers=self._creds.auth_header(),
                    )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
            return content.strip() or None
        except Exception:
            return None
