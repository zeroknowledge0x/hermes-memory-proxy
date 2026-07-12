"""Tests for user_id resolution (BUG found during deploy: opaque
`user` field like 'telegram:5398668166' crashed UUID query)."""
from __future__ import annotations

import uuid

from memory_proxy.pipeline.orchestrator import Orchestrator


class _Dummy:
    pass


def _orch(default="00000000-0000-0000-0000-000000000001"):
    return Orchestrator(_Dummy(), default_user_id=default)


def test_resolve_default_when_no_user():
    o = _orch()
    uid = o._resolve_user_id({"messages": []})
    assert uid == "00000000-0000-0000-0000-000000000001"
    uuid.UUID(uid)  # valid uuid


def test_resolve_opaque_user_mapped_to_uuid():
    o = _orch()
    uid = o._resolve_user_id({"user": "telegram:5398668166"})
    # must be a valid UUID, not the raw opaque string
    u = uuid.UUID(uid)
    assert uid != "telegram:5398668166"
    # deterministic
    assert o._resolve_user_id({"user": "telegram:5398668166"}) == uid


def test_resolve_real_uuid_passthrough_shape():
    o = _orch()
    real = "11111111-2222-3333-4444-555555555555"
    out = o._resolve_user_id({"user": real})
    assert uuid.UUID(out)  # valid uuid shape
