"""Credential provider — supports static API key OR OAuth (Nous).

Modes:
 - api_key: UPSTREAM_API_KEY set -> static Bearer token
 - oauth:   NOUS_AUTH_FILE set   -> reads access_token from a Nous
             OAuth JSON file, auto-refreshes via refresh_token BEFORE expiry
             (re-reads the file every call so a manual re-auth by the user
              is picked up without restarting the proxy).

The OpenAI-compatible adapter uses this to build the Authorization header,
so the rest of the pipeline stays provider-agnostic.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

import httpx


def _parse_expiry(exp) -> float:
    """Parse Nous `expires_at` (ISO 8601 string) or epoch into a timestamp."""
    if exp is None:
        return 0.0
    if isinstance(exp, (int, float)):
        return float(exp)
    try:
        s = str(exp).replace("Z", "+00:00")
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return 0.0


class CredentialProvider:
    def __init__(self, api_key: str | None = None, oauth_file: str | None = None,
                 refresh_lead_sec: int = 300):
        self._api_key = api_key
        self._oauth_file = oauth_file
        self._lead = refresh_lead_sec
        self._cache: dict | None = None
        if not api_key and not oauth_file:
            raise ValueError("Either UPSTREAM_API_KEY or NOUS_AUTH_FILE must be set")

    @property
    def mode(self) -> str:
        return "api_key" if self._api_key else "oauth"

    def _read_oauth(self) -> dict:
        with open(self._oauth_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write_oauth(self, data: dict) -> None:
        # Persist refreshed tokens back to the file (same shape Nous uses).
        with open(self._oauth_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def _refresh(self, data: dict) -> dict:
        """Exchange refresh_token for a new access_token (Nous OAuth)."""
        portal = data.get("portal_base_url", "https://portal.nousresearch.com")
        resp = httpx.post(
            f"{portal.rstrip('/')}/api/oauth/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": data["refresh_token"],
                "client_id": data.get("client_id", ""),
            },
            timeout=30,
        )
        resp.raise_for_status()
        tok = resp.json()
        data["access_token"] = tok["access_token"]
        if tok.get("refresh_token"):
            data["refresh_token"] = tok["refresh_token"]
        data["obtained_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        data["expires_at"] = tok.get("expires_at", data.get("expires_at", ""))
        self._write_oauth(data)  # also updates the on-disk file
        return data

    def get_token(self) -> str:
        if self._api_key:
            return self._api_key
        # OAuth path — ALWAYS re-read the file so a manual user re-auth
        # (or another process refreshing) is picked up without restart.
        data = self._read_oauth()
        self._cache = data
        exp_ts = _parse_expiry(data.get("expires_at", ""))
        # refresh if expired (or within lead window)
        if time.time() + self._lead >= exp_ts:
            try:
                data = self._refresh(data)
                self._cache = data
            except Exception:
                # best-effort: fall back to the (possibly stale) token
                pass
        return data["access_token"]

    async def refresh_now(self) -> None:
        """Force a token refresh, re-reading the file first (D-020).

        Robust against a stale in-memory cache: we always read the on-disk
        file before refreshing, so a concurrent refresh / manual re-auth is seen.
        """
        if self._api_key:
            return
        try:
            data = self._read_oauth()  # re-read, never trust cache
            self._cache = data
            self._cache = self._refresh(data)
        except Exception:
            # best-effort: keep using cached token if refresh fails
            pass

    def auth_header(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.get_token()}"}
