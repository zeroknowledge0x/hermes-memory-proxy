# Audit 2026-07-13 — Mini-training quality pass

Summary of problems found + fixes. Decision detail: `DECISIONS.md` **D-025**.
Progress log: `PROGRESS.md` section "Mini-training quality pass".

## Problems found

1. **Consolidate spam** — the 60m cron wrote near-identical profile rows repeatedly (28 active consolidated rows).
2. **Exact-text duplicates** — identical strings piled up (including multi-user test pollution).
3. **Plugin not query-aware** — retrieval always probed with a fixed phrase `"important user facts"`.
4. **Stream path** — extraction/conversation log did not receive the `assistant_msg`.
5. **Importance ranking idle** — the `importance` column was filled by reflect but unused in `ORDER BY`.
6. **User-id split** — facts were split across the default UUID vs `telegram:<your-user-id>`.

## Code fixes

| Area | Change |
|------|--------|
| `orchestrator.py` | consolidate skip-near-dup + expire old; stream buffer SSE |
| `repository.py` | exact-text gate; importance-weighted search; expire helpers |
| `writer.py` | respect `add_fact` None (dup) |
| `api/main.py` | `?q=` on `/v1/memory`; `POST /v1/admin/dedupe` |
| `hermes-plugin/...` | pass latest user text as `q` |
| `scripts/dedupe_memories.py` | one-shot cleanup CLI |

## Ops (not in git)

- DB cleanup: active 208→181, consolidated 28→1
- Cron consolidate: 60m → 6h
- Restart: `memory-proxy.service` only (gateway left running)

## Open (not yet)

- [ ] Merge facts default-UUID → telegram user (needs permission)
- [ ] Enforce `TEST_DATABASE_URL` separate from prod
- [ ] Gateway reload so plugin cache is fully fresh (optional)

## Follow-up: D-026 single-user merge (same day)

- **Problem #6 fixed:** user-id split merged into canonical UUID (`<canonical-user-uuid>`, stable hash from `telegram:<your-user-id>`).
- `SINGLE_USER_MODE=true` default — no split-brain while there is one user.
- Script: `scripts/merge_to_single_user.py`.
- Active memories after merge+dedupe: **155** across 1 user; others **0**.
