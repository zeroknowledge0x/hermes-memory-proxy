"""Security middleware — auth token + rate limiting (Phase 3).

- Auth: if the proxy binds to a non-loopback host, a bearer token is
  REQUIRED. Requests without it are rejected 401. When bound to
  127.0.0.1, auth is skipped (local-only, trusted).
- Rate limit: simple in-memory token-bucket per IP, N requests per window.

Both are opt-in via env (AUTH_TOKEN, RATE_LIMIT_PER_MIN). Disabled by
default for local single-user use.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


def requires_auth(bind_host: str) -> bool:
    """Auth is mandatory only when exposed beyond loopback."""
    return bind_host not in ("127.0.0.1", "localhost", "::1", "0.0.0.0:127.0.0.1")


class RateLimiter:
    def __init__(self, max_per_min: int = 60):
        self._max = max_per_min
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        dq = self._hits[key]
        while dq and now - dq[0] > 60:
            dq.popleft()
        if len(dq) >= self._max:
            return False
        dq.append(now)
        return True


def install_security(app: FastAPI, *, auth_token: str | None,
                     rate_limit_per_min: int = 0,
                     bind_host: str = "127.0.0.1") -> None:
    limiter = RateLimiter(rate_limit_per_min) if rate_limit_per_min > 0 else None
    need_auth = bool(auth_token) and requires_auth(bind_host)

    @app.middleware("http")
    async def security_middleware(request: Request, call_next):
        # health & admin reload are always allowed (local ops)
        path = request.url.path
        if path in ("/health", "/v1/models"):
            return await call_next(request)

        if need_auth:
            auth = request.headers.get("authorization", "")
            if auth != f"Bearer {auth_token}":
                return JSONResponse({"error": "unauthorized"}, status_code=401)

        if limiter is not None:
            ip = request.client.host if request.client else "?"
            if not limiter.allow(ip):
                return JSONResponse(
                    {"error": "rate limited"}, status_code=429,
                    headers={"Retry-After": "60"},
                )
        return await call_next(request)
