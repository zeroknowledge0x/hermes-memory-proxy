# Audit 2026-07-13 — Mini-training quality pass

Ringkasan masalah + fix. Detail keputusan: `DECISIONS.md` **D-025**.
Progress log: `PROGRESS.md` section “Mini-training quality pass”.

## Masalah ditemukan

1. **Consolidate spam** — cron 60m nulis profil hampir sama berkali-kali (28 baris consolidated aktif).
2. **Exact-text duplicates** — string identik numpuk (termasuk polusi test multi-user).
3. **Plugin tidak query-aware** — retrieval selalu probe fixed `"important user facts"`.
4. **Stream path** — extraction/conversation log tidak dapat `assistant_msg`.
5. **Importance ranking idle** — kolom `importance` diisi reflect, tidak dipakai di `ORDER BY`.
6. **User-id split** — facts terbelah default UUID vs `telegram:5398668166`.

## Fix di kode

| Area | Perubahan |
|------|-----------|
| `orchestrator.py` | consolidate skip-near-dup + expire old; stream buffer SSE |
| `repository.py` | exact-text gate; importance-weighted search; expire helpers |
| `writer.py` | respect `add_fact` None (dup) |
| `api/main.py` | `?q=` on `/v1/memory`; `POST /v1/admin/dedupe` |
| `hermes-plugin/...` | pass latest user text as `q` |
| `scripts/dedupe_memories.py` | one-shot cleanup CLI |

## Ops (bukan di git)

- DB cleanup: active 208→181, consolidated 28→1
- Cron consolidate: 60m → 6h
- Restart: `memory-proxy.service` only (gateway left running)

## Open (belum)

- [ ] Merge facts default-UUID → telegram user (butuh izin)
- [ ] Enforce `TEST_DATABASE_URL` terpisah dari prod
- [ ] Gateway reload agar plugin cache full-new (opsional)

## Follow-up: D-026 single-user merge (same day)

- **Masalah #6 fixed:** user-id split digabung ke UUID kanonik `9c5202b3-…` (`telegram:5398668166`).
- `SINGLE_USER_MODE=true` default — gak belah otak lagi selama 1 user.
- Script: `scripts/merge_to_single_user.py`.
- Active memories setelah merge+dedupe: **155** di 1 user; others **0**.
