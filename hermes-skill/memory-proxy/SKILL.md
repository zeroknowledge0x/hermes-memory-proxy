# Memory Proxy Skill

You are connected to the **Memory Proxy** — an external memory engine running
at `:8899`. Memories live there (Postgres + vector), NOT in the model. Swap the
model and your memory stays.

## Hard rules

1. **Use the memory already injected.** The `memory-proxy` plugin automatically
   injects a `# MEMORY` + `# IDENTITY` block into the system prompt every chat.
   Treat it as user context. Do NOT hallucinate facts that aren't present there.

2. **No manual saving needed.** Every turn, important facts (names, preferences,
   context) are auto-extracted by the proxy and stored in the DB. Just answer normally.

3. **If the user says "note X" / "remember X"** — the proxy already handles
   extraction. Just confirm briefly ("got it, noted"). Don't store it elsewhere.

4. **Don't remember = say you don't remember.** If the user's info isn't in
   `# MEMORY`, reply "I don't remember that / haven't noted it yet" — don't fabricate.

5. **Identity.** Respect `# IDENTITY` (SOUL/USER). That is your persona + boundaries.

## What this is NOT

- This is NOT a planning-loop. Planning/execution stays in the agent (Hermes).
- This is only memory behavior: retrieve (already injected) + let the proxy note things.

## Troubleshoot

- Memory empty but should have data? Check the proxy is up at `:8899`
  (`curl http://127.0.0.1:8899/health`).
- Swap provider/model in the `/model` picker → Memory Proxy → memory stays the same.
