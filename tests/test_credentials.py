"""Credential provider tests — api_key vs OAuth file modes."""
from __future__ import annotations

import json

from memory_proxy.providers.credentials import CredentialProvider


def test_api_key_mode_static():
    c = CredentialProvider(api_key="sk-test")
    assert c.mode == "api_key"
    assert c.get_token() == "sk-test"
    assert c.auth_header() == {"Authorization": "Bearer sk-test"}


def test_oauth_mode_reads_file(tmp_path):
    f = tmp_path / "nous_auth.json"
    f.write_text(json.dumps({
        "access_token": "at-123", "refresh_token": "rt-456",
        "expires_at": "2099-01-01T00:00:00+0000",
        "portal_base_url": "https://portal.nousresearch.com",
    }))
    c = CredentialProvider(oauth_file=str(f))
    assert c.mode == "oauth"
    assert c.get_token() == "at-123"


def test_oauth_refresh_when_expired(tmp_path):
    import respx
    import httpx
    respx.mock  # ensure imported

    f = tmp_path / "nous_auth.json"
    f.write_text(json.dumps({
        "access_token": "old", "refresh_token": "rt",
        "expires_at": "2000-01-01T00:00:00+0000",  # already expired
        "portal_base_url": "https://portal.nousresearch.com",
        "client_id": "cid",
    }))
    with respx.mock:
        respx.post("https://portal.nousresearch.com/api/oauth/token").mock(
            return_value=httpx.Response(200, json={
                "access_token": "new-token",
                "refresh_token": "rt2",
                "expires_at": "2099-01-01T00:00:00+0000",
            })
        )
        c = CredentialProvider(oauth_file=str(f))
        tok = c.get_token()
    assert tok == "new-token"
    # file persisted with new token
    assert json.loads(f.read_text())["access_token"] == "new-token"
