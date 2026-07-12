"""Token Budgeter (ARCHITECTURE §6, D-008).

Truncation priority when context exceeds budget (LEFT kept longest):
    SOUL -> USER -> Memory -> Knowledge -> Chat History

History is trimmed FIRST, then knowledge, then memory. USER and SOUL are
practically never trimmed (kept short by design).

Token estimation: len(text)//3 + margin (D-008) — coarse on purpose. No
per-provider tokenizer in v1 (model-agnostic requirement makes one
tokenizer inaccurate for all).
"""
from __future__ import annotations

from memory_proxy.context.assembler import AssembledContext


def estimate_tokens(text: str) -> int:
    """Conservative estimate. //3 slightly over-counts vs typical ~4 chars/
    token, giving a safety margin so we never blow the real budget."""
    return len(text) // 3


class TokenBudgeter:
    def __init__(self, total_context_window: int, reserved_pct: float = 0.25):
        if not 0 <= reserved_pct < 1:
            raise ValueError("reserved_pct must be in [0, 1)")
        self.total_context_window = total_context_window
        self.reserved_pct = reserved_pct

    @property
    def budget(self) -> int:
        """Tokens available for context (reserve the rest for generation)."""
        return int(self.total_context_window * (1 - self.reserved_pct))

    def fit(self, ctx: AssembledContext) -> AssembledContext:
        """Return a NEW context that fits within budget. Trims in order:
        history -> knowledge -> memory. SOUL/USER never trimmed here."""
        soul, user = ctx.soul, ctx.user
        memory = list(ctx.memory)
        knowledge = list(ctx.knowledge)
        history = list(ctx.history)

        def total() -> int:
            return estimate_tokens(
                AssembledContext(soul, user, memory, knowledge, history).render()
            )

        # Trim history first (drop oldest = front), then knowledge, then memory.
        for bucket in (history, knowledge, memory):
            while total() > self.budget and bucket:
                bucket.pop(0)

        return AssembledContext(
            soul=soul, user=user, memory=memory,
            knowledge=knowledge, history=history,
        )
