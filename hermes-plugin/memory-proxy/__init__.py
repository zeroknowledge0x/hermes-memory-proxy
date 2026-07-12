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


def _fetch_memory(user_id: str) -> dict:
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.get(
                f"{MEMORY_PROXY_URL}/v1/memory",
                params={"user": user_id, "limit": 10},
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
    auto-loaded behavior (retrieve + plan loop)."""
    user_id = ""
    if isinstance(context, dict):
        user_id = (
            context.get("user")
            or context.get("user_id")
            or context.get("telegram_user_id")
            or ""
        )
    data = _fetch_memory(user_id)
    mem_block = _format_block(data)
    parts = []
    if mem_block:
        parts.append(mem_block)
    parts.append(PLANNING_DIRECTIVE)
    block = "\n\n".join(parts)
    if not block.strip():
        return {}
    return {"system_prompt_suffix": block}
