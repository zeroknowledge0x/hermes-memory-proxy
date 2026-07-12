"""Phase 3 — security middleware tests (auth + rate limit)."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from memory_proxy.api.security import install_security, requires_auth, RateLimiter


def _app(auth_token=None, rate_limit_per_min=0, bind_host="127.0.0.1"):
    app = FastAPI()

    @app.get("/v1/models")
    async def models():
        return {"ok": True}

    @app.get("/v1/chat/completions")
    async def chat():
        return JSONResponse({"ok": True})

    install_security(
        app, auth_token=auth_token, rate_limit_per_min=rate_limit_per_min,
        bind_host=bind_host,
    )
    return app


async def _get(client_app, path, headers=None):
    from httpx import ASGITransport, AsyncClient
    transport = ASGITransport(app=client_app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        return await c.get(path, headers=headers or {})


def test_requires_auth_logic():
    assert requires_auth("0.0.0.0") is True
    assert requires_auth("192.168.1.5") is True
    assert requires_auth("127.0.0.1") is False
    assert requires_auth("localhost") is False


async def test_loopback_skips_auth():
    app = _app(auth_token="secret", bind_host="127.0.0.1")
    r = await _get(app, "/v1/chat/completions")
    assert r.status_code == 200


async def test_nonloopback_requires_token():
    app = _app(auth_token="secret", bind_host="0.0.0.0")
    r = await _get(app, "/v1/chat/completions")
    assert r.status_code == 401
    # wrong token
    r2 = await _get(app, "/v1/chat/completions", {"authorization": "Bearer wrong"})
    assert r2.status_code == 401
    # correct token
    r3 = await _get(app, "/v1/chat/completions", {"authorization": "Bearer secret"})
    assert r3.status_code == 200


async def test_rate_limit_kicks_in():
    app = _app(rate_limit_per_min=2, bind_host="127.0.0.1")
    r1 = await _get(app, "/v1/chat/completions")
    r2 = await _get(app, "/v1/chat/completions")
    r3 = await _get(app, "/v1/chat/completions")
    assert r1.status_code == 200 and r2.status_code == 200
    assert r3.status_code == 429


def test_ratelimiter_allows_up_to_max():
    lim = RateLimiter(max_per_min=3)
    assert all(lim.allow("ip") for _ in range(3)) is True
    assert lim.allow("ip") is False
    assert lim.allow("other") is True
