"""Identity loader — SOUL.md + USER.md (ARCHITECTURE §4, D-004).

Loaded ONCE at startup, cached in-memory. Reload only via explicit
/admin/reload-identity. Never re-read per request. Missing files ->
empty string (no error), so the proxy runs without identity files.
"""
from __future__ import annotations

from pathlib import Path


class IdentityLoader:
    def __init__(self, identity_dir: str | Path):
        self._dir = Path(identity_dir)
        self._soul: str | None = None
        self._user: str | None = None
        self._read_count = 0  # for tests: proves load-once

    def load(self) -> None:
        """Read files from disk into cache. Idempotent per call."""
        self._soul = self._read("SOUL.md")
        self._user = self._read("USER.md")

    def _read(self, name: str) -> str:
        path = self._dir / name
        if not path.exists():
            return ""
        self._read_count += 1
        return path.read_text(encoding="utf-8").strip()

    @property
    def soul(self) -> str:
        if self._soul is None:
            self.load()
        return self._soul or ""

    @property
    def user(self) -> str:
        if self._user is None:
            self.load()
        return self._user or ""

    @property
    def read_count(self) -> int:
        return self._read_count

    def reload(self) -> None:
        """Explicit reload (admin endpoint)."""
        self.load()
