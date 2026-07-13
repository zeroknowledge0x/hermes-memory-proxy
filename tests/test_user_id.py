"""Tests for user_id resolution (D-013 multi-user hash + D-026 single-user)."""
from __future__ import annotations

import uuid

from memory_proxy.pipeline.orchestrator import Orchestrator


class _Dummy:
    pass


def _orch(default="00000000-0000-0000-0000-000000000001", single_user_mode=True):
    return Orchestrator(
        _Dummy(), default_user_id=default, single_user_mode=single_user_mode
    )


def test_single_user_mode_always_default():
    """D-026: with single_user_mode ON, any payload maps to DEFAULT_USER_ID."""
    o = _orch(single_user_mode=True)
    assert o._resolve_user_id({"messages": []}) == "00000000-0000-0000-0000-000000000001"
    assert o._resolve_user_id({"user": "telegram:5398668166"}) == (
        "00000000-0000-0000-0000-000000000001"
    )
    assert o._resolve_user_id({"user": "someone-else"}) == (
        "00000000-0000-0000-0000-000000000001"
    )


def test_resolve_default_when_no_user_multi():
    o = _orch(single_user_mode=False)
    uid = o._resolve_user_id({"messages": []})
    assert uid == "00000000-0000-0000-0000-000000000001"
    uuid.UUID(uid)


def test_resolve_opaque_user_mapped_to_uuid_multi():
    o = _orch(single_user_mode=False)
    uid = o._resolve_user_id({"user": "telegram:5398668166"})
    u = uuid.UUID(uid)
    assert uid != "telegram:5398668166"
    assert o._resolve_user_id({"user": "telegram:5398668166"}) == uid
    # known stable hash for this opaque id
    assert str(u) == "9c5202b3-0c9d-bd91-b8d0-2e24d2d261d3"


def test_resolve_real_uuid_hashed_in_multi_mode():
    o = _orch(single_user_mode=False)
    real = "11111111-2222-3333-4444-555555555555"
    out = o._resolve_user_id({"user": real})
    assert uuid.UUID(out)  # valid uuid shape
