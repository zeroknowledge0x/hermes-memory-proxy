"""Memory Proxy plugin for Hermes — auto-load behavior (no manual trigger).

Hook `pre_llm_call` -> `inject_memory`: fetches ranked memories + identity from
the memory-proxy engine (:8899) AND injects the memory skill + a generic
planning-loop directive into the system prompt. Result: the agent remembers
across sessions AND behaves with retrieve→plan→execute→review loop automatically,
without the user having to type a keyword.

Install: copy this folder into ~/.hermes/plugins/model-providers/ (or symlink),
add `memory-proxy` to `plugins.enabled` in config.yaml, restart the gateway.

Reference: hermes-loop plugin format (plugin.yaml + hooks pre_llm_call).
"""
from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger("memory_proxy_plugin")

MEMORY_PROXY_URL = os.environ.get("MEMORY_PROXY_URL", "http://127.0.0.1:8899")
TIMEOUT = float(os.environ.get("MEMORY_PROXY_TIMEOUT", "5"))

PLANNING_DIRECTIVE = """\
# BEHAVIOR (auto-loaded by Memory Proxy)

You have external memory + a loop behavior. No special command needed:

1. REMEMBER: the # MEMORY + # IDENTITY blocks below are already injected. Use
   them as user context. Do NOT hallucinate facts absent from there.
2. RETRIEVE first, then answer. If the user's info isn't in # MEMORY, say
   "I don't remember that", don't fabricate.
3. NOTE: important facts (names, preferences, context) are auto-extracted by
   the proxy. Just answer normally. If the user says "note X", just confirm briefly.
4. PLANNING LOOP (if the task is a new project/piece of work): run
   Understand → Plan → Execute → Review → Improve → Repeat:
   - Understand: what is the user's goal? clarify if ambiguous.
   - Plan: break into steps, each with a verifiable Definition of Done.
   - Execute: do the step, use tools if needed.
   - Review: check result vs DoD. Failed? fix it, don't blindly proceed.
   - Improve: note the lesson to memory (proxy does this automatically).
   - Loop: repeat until the goal is reached.
   - STOP/wait/cancel = halt entirely, don't continue.
5. VERIFY before claiming: tool output required, no proof = claim void.
"""


def _latest_user_text(context: dict | None) -> str:
    """Best-effort extract of the latest user message for query-aware retrieval."""
    if not isinstance(context, dict):
        return ""
    # Common Hermes context shapes
    for key in ("user_message", "message", "latest_user_message", "prompt", "query"):
        val = context.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()[:500]
    messages = context.get("messages") or context.get("history") or []
    if isinstance(messages, list):
        for msg in reversed(messages):
            if not isinstance(msg, dict):
                continue
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, list):
                    parts = [
                        p.get("text", "")
                        for p in content
                        if isinstance(p, dict) and p.get("type") == "text"
                    ]
                    content = " ".join(parts)
                if isinstance(content, str) and content.strip():
                    return content.strip()[:500]
    return ""


def _fetch_memory(user_id: str, query: str = "") -> dict:
    try:
        params: dict = {"user": user_id, "limit": 10}
        if query:
            params["q"] = query
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.get(
                f"{MEMORY_PROXY_URL}/v1/memory",
                params=params,
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        logger.warning("memory-proxy fetch failed: %s", exc)
        return {"memory": [], "identity": {}}


def _format_block(data: dict) -> str:
    lines = []
    identity = data.get("identity") or {}
    if identity.get("soul"):
        lines.append(f"# IDENTITY (SOUL)\n{identity['soul'].strip()}")
    if identity.get("user"):
        lines.append(f"# USER PROFILE\n{identity['user'].strip()}")
    mem = data.get("memory") or []
    if mem:
        lines.append("# MEMORY (retrieved facts about the user)")
        for m in mem:
            lines.append(f"- {m}")
    if not lines:
        return ""
    return "\n\n".join(lines)


def inject_memory(context: dict | None = None) -> dict:
    """pre_llm_call hook. Returns a system-prompt suffix carrying memory +
    auto-loaded behavior (retrieve + plan loop).

    Uses the latest user message as a semantic query (`q`) so retrieval is
    query-aware instead of always probing with a fixed phrase.
    """
    user_id = ""
    if isinstance(context, dict):
        user_id = (
            context.get("user")
            or context.get("user_id")
            or context.get("telegram_user_id")
            or ""
        )
        # Prefer platform-prefixed ids when only a bare chat id is available.
        if user_id and ":" not in str(user_id) and str(user_id).isdigit():
            user_id = f"telegram:{user_id}"
    query = _latest_user_text(context)
    data = _fetch_memory(str(user_id or ""), query)
    mem_block = _format_block(data)
    parts = []
    if mem_block:
        parts.append(mem_block)
    parts.append(PLANNING_DIRECTIVE)
    block = "\n\n".join(parts)
    if not block.strip():
        return {}
    return {"system_prompt_suffix": block}
