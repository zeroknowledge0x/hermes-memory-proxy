"""Provider adapter interface — the ONLY thing the core pipeline talks to.

The orchestrator never imports a concrete provider. Swapping models =
swapping which adapter is instantiated. See DECISIONS.md D-002/D-003.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator


class ProviderAdapter(ABC):
    @abstractmethod
    async def forward(
        self, payload: dict[str, Any], stream: bool
    ) -> "AsyncIterator[bytes] | dict[str, Any]":
        """Send final payload to the real provider.

        stream=True  -> async generator of raw SSE bytes (passthrough).
        stream=False -> parsed JSON dict.
        """
        ...

    @abstractmethod
    def inject_context(
        self, payload: dict[str, Any], context_block: str
    ) -> dict[str, Any]:
        """Insert context per this provider's format. Return a NEW payload,
        never mutate in place."""
        ...

    @abstractmethod
    def extract_latest_user_message(self, payload: dict[str, Any]) -> str:
        """Return the latest user message text from the payload."""
        ...

    async def list_models(self) -> list[dict[str, Any]]:
        """List models from the upstream. Default: empty (override per adapter)."""
        return []

    async def get_model(self, model: str) -> dict[str, Any] | None:
        """Fetch a single model's detail from upstream, or None."""
        return None
