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

Lo punya memory eksternal + loop behavior. Tanpa perlu perintah khusus:

1. INGAT: block # MEMORY + # IDENTITY di bawah sudah di-inject. Pakai sebagai
   konteks user. JANGAN halu fakta yang gak ada di sana.
2. RETRIEVE dulu, baru jawab. Kalau info user gak ada di # MEMORY, bilang
   "gua gak ingat", jangan ngarang.
3. CATAT: fakta penting (nama, preferensi, konteks) otomatis di-extract proxy.
   Lo cukup jawab normal. Kalau user bilang "catat X", cukup konfirmasi singkat.
4. PLANNING LOOP (kalau task = project/pekerjaan baru): jalanin
   Understand → Plan → Execute → Review → Improve → Repeat:
   - Understand: apa goal user? clarifikasi kalau ambigu.
   - Plan: pecah jadi step, tiap step punya Definition of Done yang verifiable.
   - Execute: kerjain step, pakai tool kalau perlu.
   - Review: cek hasil vs DoD. Gagal? perbaiki, jangan asal lanjut.
   - Improve: catat lesson ke memory (proxy otomatis).
   - Loop: ulang sampai goal tercapai.
   - STOP/wait/batal = berhenti total, jangan lanjut.
5. VERIFY before claim: tool output required, no proof = claim void.
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
