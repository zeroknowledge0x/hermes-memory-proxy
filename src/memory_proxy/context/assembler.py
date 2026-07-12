"""Context Assembler — fixed order (ARCHITECTURE §5, D-002).

Order (NEVER reordered without a DECISIONS.md entry):
    1. SOUL
    2. USER
    3. Memory      (semantic search, filtered per user_id)
    4. Knowledge   (semantic search knowledge_chunks)
    5. Recent Messages
    6. Current User Prompt  (stays in the request messages, not duplicated here)

memory and knowledge arrive as SEPARATE lists — never mixed (guardrail).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AssembledContext:
    soul: str = ""
    user: str = ""
    memory: list[str] = field(default_factory=list)
    knowledge: list[str] = field(default_factory=list)
    history: list[str] = field(default_factory=list)

    def render(self) -> str:
        parts: list[str] = []
        if self.soul:
            parts.append(f"# IDENTITY (SOUL)\n{self.soul}")
        if self.user:
            parts.append(f"# USER PROFILE\n{self.user}")
        if self.memory:
            parts.append(
                "# MEMORY (user facts)\n"
                + "\n".join(f"- {m}" for m in self.memory)
            )
        if self.knowledge:
            parts.append(
                "# KNOWLEDGE (reference)\n"
                + "\n".join(f"- {k}" for k in self.knowledge)
            )
        if self.history:
            parts.append(
                "# RECENT MESSAGES\n" + "\n".join(self.history)
            )
        return "\n\n".join(parts)


class ContextAssembler:
    def assemble(
        self,
        soul: str = "",
        user: str = "",
        memory: list[str] | None = None,
        knowledge: list[str] | None = None,
        history: list[str] | None = None,
    ) -> AssembledContext:
        return AssembledContext(
            soul=soul,
            user=user,
            memory=list(memory or []),
            knowledge=list(knowledge or []),
            history=list(history or []),
        )
