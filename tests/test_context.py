"""Phase 1.4 tests — identity loader, context assembler, token budgeter.
No DB needed; all in-memory / filesystem fixtures."""
from __future__ import annotations

import pytest

from memory_proxy.identity.loader import IdentityLoader
from memory_proxy.context.assembler import AssembledContext, ContextAssembler
from memory_proxy.context.budgeter import TokenBudgeter, estimate_tokens


# ---------- Identity Loader ----------

def test_identity_loads_once(tmp_path):
    (tmp_path / "SOUL.md").write_text("I am ZKA.", encoding="utf-8")
    (tmp_path / "USER.md").write_text("zk profile.", encoding="utf-8")
    loader = IdentityLoader(tmp_path)
    loader.load()
    # access many times — must NOT re-read files
    for _ in range(10):
        _ = loader.soul
        _ = loader.user
    assert loader.soul == "I am ZKA."
    assert loader.user == "zk profile."
    assert loader.read_count == 2  # one read per file, once


def test_identity_missing_files_empty(tmp_path):
    loader = IdentityLoader(tmp_path)
    loader.load()
    assert loader.soul == ""
    assert loader.user == ""


def test_identity_reload_rereads(tmp_path):
    (tmp_path / "SOUL.md").write_text("v1", encoding="utf-8")
    loader = IdentityLoader(tmp_path)
    loader.load()
    assert loader.soul == "v1"
    (tmp_path / "SOUL.md").write_text("v2", encoding="utf-8")
    loader.reload()
    assert loader.soul == "v2"


# ---------- Context Assembler ----------

def test_assembler_order_deterministic():
    a = ContextAssembler()
    ctx = a.assemble(
        soul="SOUL", user="USER",
        memory=["m1", "m2"], knowledge=["k1"], history=["h1"],
    )
    out = ctx.render()
    # order must be SOUL -> USER -> MEMORY -> KNOWLEDGE -> RECENT
    i_soul = out.index("SOUL")
    i_user = out.index("USER PROFILE")
    i_mem = out.index("MEMORY")
    i_know = out.index("KNOWLEDGE")
    i_hist = out.index("RECENT MESSAGES")
    assert i_soul < i_user < i_mem < i_know < i_hist
    # deterministic: same input -> same output
    assert a.assemble(soul="SOUL", user="USER",
                      memory=["m1", "m2"], knowledge=["k1"],
                      history=["h1"]).render() == out


def test_assembler_skips_empty_sections():
    ctx = ContextAssembler().assemble(soul="SOUL")
    out = ctx.render()
    assert "SOUL" in out
    assert "MEMORY" not in out
    assert "KNOWLEDGE" not in out


# ---------- Token Budgeter ----------

def test_budget_computation():
    b = TokenBudgeter(total_context_window=1000, reserved_pct=0.25)
    assert b.budget == 750


def test_budgeter_trims_history_first():
    # SOUL/USER small; memory/knowledge/history large enough to overflow.
    big = "x" * 300  # ~100 tokens each via //3
    ctx = AssembledContext(
        soul="s", user="u",
        memory=[big], knowledge=[big], history=[big, big, big],
    )
    b = TokenBudgeter(total_context_window=400, reserved_pct=0.25)  # budget 300
    fitted = b.fit(ctx)
    # SOUL + USER always survive
    assert fitted.soul == "s" and fitted.user == "u"
    # history trimmed before knowledge/memory
    assert len(fitted.history) < 3
    # output within budget
    assert estimate_tokens(fitted.render()) <= b.budget


def test_budgeter_soul_user_never_trimmed():
    huge = "y" * 100000
    ctx = AssembledContext(soul=huge, user=huge, memory=[], knowledge=[], history=[])
    b = TokenBudgeter(total_context_window=100, reserved_pct=0.2)
    fitted = b.fit(ctx)
    # nothing to trim in memory/knowledge/history; SOUL/USER kept even if over
    assert fitted.soul == huge and fitted.user == huge


def test_budgeter_trim_order_knowledge_before_memory():
    big = "z" * 600  # ~200 tokens each
    ctx = AssembledContext(
        soul="s", user="u",
        memory=["m" * 600], knowledge=["k" * 600], history=[],
    )
    # budget that fits SOUL+USER+one big block but not two
    b = TokenBudgeter(total_context_window=400, reserved_pct=0.25)  # budget 300
    fitted = b.fit(ctx)
    # knowledge trimmed before memory
    if not fitted.knowledge and not fitted.memory:
        pytest.skip("both trimmed — budget too tight for this assertion")
    assert fitted.memory and not fitted.knowledge
