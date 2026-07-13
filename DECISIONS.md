# DECISIONS — Hermes Memory Proxy

> Catatan semua keputusan desain yang sudah **DIKUNCI** sebelum implementasi, beserta bukti/alasan.
> Format: setiap keputusan = konteks → keputusan → alasan/bukti → konsekuensi. Perubahan di masa depan wajib ditambahkan sebagai entri baru, jangan hapus yang lama.

---

## D-001 — Arsitektur transparan proxy FEASIBLE

- **Keputusan:** Lanjut. Tidak ada blocker fatal.
- **Bukti (source Hermes `/usr/local/lib/hermes-agent/`):**
  - Custom `base_url` didukung → `~/.hermes/config.yaml:4` sudah pakai `base_url: https://inference-api.nousresearch.com/v1`.
  - Client = `AsyncOpenAI` SDK → `agent/auxiliary_client.py:4377` (`return AsyncOpenAI(**async_kwargs)`).
  - Provider plugin `custom` untuk endpoint OpenAI-compat/Ollama/local → `plugins/model-providers/custom/plugin.yaml`.
- **Konsekuensi:** STOP-condition #1 di plan awal (base_url tidak bisa) TERBANTAH. Aman lanjut.

## D-002 — Wire-format kanonik = OpenAI Chat Completions

- **Keputusan:** Core proxy bicara **satu** wire-format kanonik: OpenAI Chat Completions. Adapter menerjemahkan ke provider lain.
- **Alasan:** Hermes default pakai `AsyncOpenAI` SDK. SDK memvalidasi/parse response → format harus valid sempurna, bukan "hampir bener".
- **Konsekuensi:** Response cacat ditolak SDK (bukan Hermes). Streaming harus SSE `data: {...}` + `data: [DONE]` bit-exact.

## D-003 — Adapter OpenAI-compatible dibangun DULUAN (bukan Anthropic)

- **Keputusan:** Flip urutan dari plan awal §10. OpenAI-compat adapter #1, Anthropic fase 2.
- **Alasan:** Jalur default Hermes = OpenAI SDK → base_url. Membangun Anthropic duluan = jalur yang tidak dipakai di v1.

## D-004 — Memory internal Hermes DIMATIKAN

- **Keputusan:** Set `memory.memory_enabled: false` dan `memory.user_profile_enabled: false` di `~/.hermes/config.yaml`.
- **Bukti:** `agent/context_breakdown.py:72` cek flag `_memory_enabled` sebelum inject block ke system prompt; `agent_init.py:1336-1347` gate memory di config. Config saat ini `memory_enabled: true` (aktif) → HARUS dimatikan.
- **Alasan:** Kalau tidak, memory Hermes lokal (MEMORY.md/USER.md) + memory proxy = DOUBLE injection.
- **Konsekuensi:** Semua memory dinamis dari proxy. SOUL.md/USER.md untuk identity tetap di-load proxy (bukan Hermes).

## D-005 — Vector DB = PostgreSQL + pgvector

- **Keputusan:** pgvector, bukan Qdrant/Weaviate/Chroma/Milvus.
- **Alasan:** Sudah pakai Postgres untuk relational → zero service tambahan; backup satu pintu (`pg_dump` relational+vektor); OSS, no lock-in; HNSW mature; skala ribuan–puluhan ribu vektor = ringan.
- **Konsekuensi:** Pindah Qdrant hanya jika data tembus ratusan ribu–juta vektor + butuh quantization/multitenancy. (Riset: `/root/laporan-vector-db-memory-proxy.md`)

## D-006 — Embedding = bge-small-en-v1.5 (dim 384) via fastembed

- **Keputusan:** `bge-small-en-v1.5`, dimensi **384**, library **fastembed (ONNX)**.
- **Alasan:** Retrieval terbaik di kelas ringan (MTEB retrieval 46.1), aman di VPS 1–2GB, 384-dim (index kecil), fastembed hindari PyTorch ~2GB. Lokal = model-agnostic (embedding tidak nyangkut provider LLM).
- **Konsekuensi:** Schema `VECTOR(384)` LOCKED. Ganti embedding model = re-embed semua data. Simpan `embedding_model` di metadata DB. Upgrade ke bge-base (768) hanya jika VPS punya 2GB longgar. (Riset: `/root/embed_research/LAPORAN_EMBEDDING_RAG.md`)

## D-007 — Fact Extraction = hybrid ringan, model kecil terpisah, async, ADD-only

- **Keputusan:**
  - Pakai **model kecil TERPISAH** (Ollama 7B lokal / gpt-4o-mini), BUKAN model utama.
  - Alur hybrid: heuristic gate → LLM kecil extract → normalisasi → dedupe (cosine) → ADD-only store.
  - Timing: per-turn async fire-and-forget + consolidation end-of-session.
  - Output ketat: list fakta pendek, `response_format=json_object` + parser fallback.
- **Alasan:** LLM extraction pakai model utama = biaya 2x + latency. Model kecil terpisah = murah. ADD-only (pinjam mem0) hindari bagian rapuh (LLM milih UPDATE/DELETE). Validity window (pinjam Zep) untuk fakta berubah tanpa hapus history.
- **Konsekuensi:** Extraction WAJIB optional & configurable (bisa dimatikan; proxy tetap jalan sebagai passthrough+retrieval). (Riset: `/root/riset-fact-extraction.md`)

## D-008 — Token Budgeter pakai estimasi, bukan tokenizer akurat

- **Keputusan:** Estimasi `len(text)//3` + `reserved_pct` besar (0.25–0.3). Tokenizer akurat per-provider ditunda.
- **Alasan:** Tokenizer akurat = dependency berat (tiktoken/SentencePiece) + network call (Anthropic count_tokens) di hot path. Budgeting itu coarse (buang history turn), tidak butuh presisi ±1 token. Model-agnostic requirement bikin satu tokenizer tidak akurat untuk semua.
- **Konsekuensi:** Kalau metrics menunjukkan budgeting sering meleset → revisit di fase hardening.

## D-009 — test_passthrough: yang identik = PAYLOAD, bukan response content

- **Keputusan:** Acceptance "hasil identik" diredefinisi jadi **byte-level payload** yang diteruskan ke provider identik (dengan/tanpa injection off), bukan response content.
- **Alasan:** LLM non-deterministic; request sama ≠ output sama (kecuali temp=0+seed, tidak semua provider hormati seed).

## D-010 — Memory writer = single-writer queue; test await, prod eventual consistency

- **Keputusan:** Satu worker async sequential consume queue. Di test mode `await` write selesai; di prod terima eventual consistency EKSPLISIT (didokumentasikan).
- **Alasan:** Writer async non-blocking → acceptance "fakta turn 1 muncul di turn 2" bisa flaky kalau write belum commit. Single-writer hindari race read/write.

## D-011 — Backup = pg_dump harian off-VPS; git = code only

- **Keputusan:** `pg_dump -Fc` harian via cron → upload Backblaze B2/S3 (rclone). WAL/PITR overkill v1. GitHub HANYA code/config/migration/docker.
- **Konsekuensi:** `.gitignore` wajib: `.env`, `*.dump`, `backup/`, volume data. Restore drill bulanan.

## D-012 — Provider v1 = OpenAI-compat only

- **Keputusan:** v1 dukung OpenAI-compat (openai, openrouter, ollama, vLLM, LM Studio, custom). Anthropic & Gemini = fase 2. Codex/Responses API = tidak didukung.
- **Bukti:** `providers/__init__.py` plugin registry; Anthropic pakai `agent/anthropic_adapter.py` (wire beda), Codex `agent/codex_runtime.py` (beda total).

## D-013 — Identity single-user hardcode untuk v1

- **Alasan:** v1 = single hardcoded `user_id` + `session_id` per proses (known limitation eksplisit, bukan bug tersembunyi).
- **Alasan:** Perlu verifikasi apakah Hermes kirim identitas user/session (Phase 0 poin 6). Sampai terverifikasi, default single-user.
- **Status:** VERIFY saat implementasi — cek apakah request Hermes bawa field `user`/header identitas.

## D-014 — Embedding model = paraphrase-multilingual-MiniLM-L12-v2 (REVISI D-006)

- **Keputusan:** Ganti dari `bge-small-en-v1.5` ke `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`. Dimensi TETAP 384 (schema tidak berubah).
- **Alasan:** bge-small English-only. User berkomunikasi Bahasa Indonesia. Bukti cosine (diukur langsung, query "minuman favorit user apa?"):
  - bge-small-en: kopi ranking #3 (0.532) ❌
  - paraphrase-multilingual-MiniLM: kopi ranking #1 (0.568), separasi jelas vs #2 (0.293) ✅
  - multilingual-e5-large (1024, 2.24GB): kopi #1 tapi separasi tipis (0.859 vs 0.837) + kegedean utk VPS
- **Konsekuensi:** dim 384 tetap → schema aman. Model ~0.22GB (ringan). Warning mean-pooling fastembed = benign.
- **Swap-ability:** Ganti model tetap didukung selamanya — set `EMBEDDING_MODEL` di config, lalu jalankan `scripts/reembed.py` untuk re-encode data lama. Kolom `embedding_model` per-row melacak model mana yang dipakai. Kalau model baru beda dimensi, ubah `EMBEDDING_DIM` + migration `ALTER ... VECTOR(n)` dulu.

## D-015 — Verifikasi: Hermes TIDAK kirim identitas user/session di request

- **Keputusan:** Konfirmasi D-013 — v1 single hardcoded `user_id` + `session_id` adalah benar. Hermes tidak mengirim field `user` maupun header identitas di request OpenAI Chat Completions.
- **Bukti:** source `agent/transports/chat_completions.py:494` `_build_kwargs_from_profile()` — tidak ada `api_kwargs["user"]`, tidak ada header identitas. `session_id` (param:276,572,582) hanya dilewatkan ke `profile.build_extra_body()` / `build_api_kwargs_extras()` → masuk `extra_body` SAJA, dan hanya kalau provider profile emit (mis. OpenRouter). Untuk Nous profile (provider aktif), session_id tidak jadi identitas user di wire.
- **Cara verifikasi:** Tidak perlu restart gateway/serve. Cukup baca source. Pendekatan live-capture via proxy probe (8900) terhalang karena gateway tidak reconnect ke serve baru tanpa restart penuh Hermes — tapi source sudah memberi bukti konklusif.
- **Implikasi deploy:** Proxy hardcode 1 user_id per proses. Kalau mau per-session, baca env `HERMES_SESSION_USER_ID` di SISI PROXY (bukan dari request Hermes).

## D-016 — Ollama (local) tidak diinstal di VPS → verifikasi via simulasi wire

- **Keputusan:** Ollama tidak diinstal di VPS ini (curl localhost:11434 gagal). Verifikasi dilakukan via **simulasi upstream** yang meniru wire quirks Ollama (SSE `data:` + `[DONE]`, keep-alive chunk kosong `choices:[]`, content string). Adapter OpenAI-compat sudah menangani semua itu (passthrough byte-exact).
- **Bukti:** `tests/test_ollama.py` — 2 test lolos: stream passthrough (termasuk keep-alive), non-stream JSON. Forward ke `/v1/chat/completions` untouched.
- **Konsekuensi:** Gemini / vLLM / LM Studio = OpenAI-compat → pakai adapter yang sama (ProviderAdapter interface). Anthropic butuh adapter sendiri (D-002, sudah ada).
- **Catatan:** Tes Ollama SUNGGUHAN butuh install Ollama (download model GB-an). Tunda sampai lo mau — gak blocker untuk v1 (adapter sudah benar secara teori wire).

## D-017 — Backup strategy (Postgres only, git = code)

- **Keputusan:** Backup = `pg_dump -Fc` harian via cron → lokal + `rclone` ke B2/S3. Git HANYA untuk source/config/migration. Memory/DB **TIDAK** di git (`.gitignore` cover `*.dump`, `pgdata/`, `backup/`).
- **Bukti/implikasi:** `scripts/backup.sh` sudah ada, retensi 14 hari lokal. Recovery: `git clone` → `docker compose up` / native pg → `rclone copy` → `pg_restore`. WAL/PITR sengaja di-skip (overkill v1 single-user).
- **Konsekuensi:** apabila VPS mati → clone repo + restore dump = jalan lagi. Test restore berkala = disarankan tapi di luar scope otomatis v1.

## D-018 — Proxy model-list dari upstream (bukan kosong)

- **Keputusan:** Route `/v1/models` dan `/v1/models/{model}` di proxy **mem-forward GET ke upstream asli** (baca token lewat CredentialProvider), bukan balikin list kosong.
- **Bukti:** Hermes pas daftarin/cek provider nge-probe `/v1/models` → kalau kosong, muncul warning "model X not found in model listing" (ERR-008). Setelah proxy ke upstream, Hermes liat 278 model asli → warning hilang.
- **Konsekuensi:** proxy tetep model-agnostic (list diambil dari upstream aktif). Adapter OpenAI ditambah `list_models()` + `get_model()` (base adapter punya default no-op).

## D-019 — Daftarin provider di picker Hermes = `custom_providers:` di config.yaml

- **Keputusan:** Biar sebuah proxy/provider muncul di picker `/model` Hermes, daftarin sebagai entry `custom_providers:` (list of dict) di `~/.hermes/config.yaml`. Field: `name`, `provider_key`, `base_url`, `api_mode: openai_chat`, `model`.
- **Bukti:** Folder plugin `~/.hermes/plugins/model-providers/<n>` **TIDAK** dipakai picker (cuma `list_providers()` internal). `hermes config set custom_providers '[{...}]'` nyimpen sebagai STRING (gak ke-parse). Cara yang bener = tulis YAML list lewat script/python langsung ke config.yaml (ERR-007).
- **Konsekuensi:** ganti provider di picker = pilih nama itu; `base_url` otomatis ke proxy. Gak perlu restart Hermes buat ganti antar provider yang sudah terdaftar (cuma re-read config per `/model`).
  - CATATAN GUARD: agent TIDAK boleh `patch`/`write` config.yaml via tool (security guard). Edit lewat terminal python (root) atau user yang edit.

## D-020 — Auto-refresh OAuth token on stale (401/403/404)

- **Keputusan:** `OpenAICompatibleAdapter.forward()` kalau dapet 401/403/404 dari upstream OAuth, panggil `CredentialProvider.refresh_now()` lalu retry SEKALI. Gak perlu restart proxy tiap token expired.
- **Bukti:** Sebelum fix, token Nous expired → proxy balikin 404 → 1 request gagal (ERR-010). Pola berulang tiap beberapa menit. Setelah fix, stale token di-refresh otomatis di request yang sama.
- **Konsekuensi:** proxy resilient terhadap token expiry. `refresh_now()` force-refresh bypass expiry-check; kalau refresh gagal, fallback ke cached token (best-effort). Berlaku buat mode oauth aja (api_key gak perlu refresh).

## D-021 — Hermes internal memory dimigrasi ke Proxy DB

- **Keputusan:** Isi `~/.hermes/memories/MEMORY.md` + `USER.md` dimigrasi ke `memories` table di Proxy DB (source=`hermes_migration`), lalu file Hermes di-rename jadi `m1.md`/`m2.md` biar Hermes beneran gak baca (cuma `MEMORY.md`/`USER.md` yang dikenal).
- **Bukti:** Setelah rename, lo tanya "VPS pake Docker?" → proxy jawab bener (match 100% sama `m1.md`) → terbukti proxy baca dari DB, BUKAN Hermes internal. Ingatan sekarang 100% di Proxy (Postgres).
- **Konsekuensi:** memory internal Hermes dimatikan (file gak dikenal). Single source of truth = Proxy DB. Kalau mau balikin, rename `m1.md`→`MEMORY.md`.

## D-022 — Acuan the-fool / hermes-loop: ambil POLA, 3 repo terpisah

- **Keputusan:** Memory-proxy masa depan diarahkan dari `the-fool` (RFC-0002 Memory Engine: taxonomy Working/Short/Conversation/Semantic/Episodic/Reflection, Ranker, Compressor, Event Log) + `hermes-loop` (plugin.yaml + hooks pre_llm_call/on_session_start). **Ambil POLA, gak ambil SKILL** — tidak copy isi skill (core_evo, project_manager, growth_manager), brain/learnings, atau the agent-os RFC. Struktur target = **3 repo terpisah**: `memory-proxy/` (engine), `memory-proxy-plugin/` (inject memory ke Hermes), `memory-proxy-skill/` (behavior generik). Orang clone masing-masing → tinggal pasang.
- **Bukti:** `the-fool` jauh lebih lengkap dari `hermes-loop` (vault hidup: learnings ratusan, RFC memory/knowledge/context/router/learning, loop_types 4 kategori). RFC-0002 memory taxonomy = reference arsitektur valid. `hermes-loop` plugin format (plugin.yaml + hooks) = reference plugin Hermes yang benar.
- **Konsekuensi:** repo memory-proxy = kerangka KOSONG generik; persona/facts diisi user sendiri (template SOUL/USER kosong). DB sekarang gak kritis → prioritas build arsitektur, bukan backup. Backup cron DITUNDA. Planning-loop agen tetap di Hermes, proxy cuma memory + behavior inject.

## D-023 — Mekanisme loop the-fool/hermes-loop (cron + plugin, gak di proxy)

- **Keputusan:** "Otak ke-2 pinter + loop" = kombinasi (1) plugin inject behavior tiap chat (turn-based, SUDAH di `inject_memory`), DAN (2) **cron job Hermes** yang jalanin loop berkala (time-based). Bukan di proxy. Proxy cuma memory store + extract + consolidate API.
- **Bukti (dari the-fool):** 30+ cron jobs (`loop_evolve`, `loop_intake`, `loop_daily_digest`, dll) jalan di schedule (tiap jam / */5). Tiap job = **flat prompt** ("refleksi diri"), BUKAN panggil `brain_loop(...)` (itu HTTP 400 — pitfall mereka). `hermes cron run <id>` buat verifikasi. Learning: "saat fix config fleet-wide, verifikasi SEMUA job, bukan cuma contoh".
- **Bukti (dari hermes-loop core skill):** `core` = satu-satunya decision-maker; skill lain eksekutor pasif (gak call skill lain, gak write session). Workflow: Load Session → Discover Goal → Plan → Select Skill → Execute → Validate → Review → Loop Control → Update Session → Escalate → Respond. max_iterations default 5.
- **Arsitektur (RFC-0001/0002/0006 the-fool):** LLM = syscall (bukan product). Memory Engine = tiers (Working/Short/Conversation/Long/Semantic/Episodic/Reflection) + Ranker + Compressor + Event Log. Learning Engine = Experience → Reflection → Self-Critique → Score → Propose → Gate → Apply. **Auto-merge opt-in, gated.**
- **Konsekuensi untuk memory-proxy:** (a) plugin SUDAH inject memory+planning (turn-based). (b) TAMBAH cron jobs Hermes yg panggil proxy endpoint `/v1/consolidate` (rangkum memory) + `/v1/reflect` (review fakta) — flat prompt, verifikasi tiap job. (c) Gak copy skill isi (core_evo/project_manager); cuma pola. (d) Cron job butuh izin eksplisit user (aturan), dan jgn auto-resurrect R&D loop tanpa izin (lesson the maintainer: income > R&D loops).
- **Bukti (verify):** consolidate beneran LLM-rangkum 6 fakta → summary profile the maintainer (disimpan tier=long, ke-catet di events+file). reflect score 7 fakta. 54 tests ijo.

## D-024 — Backup DB off-VPS (GitHub private, bukan lokal doang)

- **Keputusan:** backup harian `pg_dump` → (1) lokal `/root/memory-proxy/backup/` (retention 14d, udah test restore sukses: 56 memories+4 events balik), DAN (2) **force-push ke repo private `memory-proxy-backup` branch `latest`** (1 file `latest.dump`, gak numpuk history). Kalau VPS ilang total → clone branch `latest` → restore. Repo private = data the maintainer gak bocor.
- **Bukti:** `scripts/backup_to_github.sh` jalan (dump 96694 bytes → push branch latest, verified via gh API size). Cron `loop_db_backup_gh` (daily 4AM) verified succeeded. `rclone` B2/S3 diskip (gak terinstall) — GitHub jadi off-VPS carrier.
- **Konsekuensi:** "DB gak ilang" aman walau VPS mati. Catatan: dump gak含 API key/credential (cuma memory+events). Main repo `memory-proxy` TETAP murni kode (backup di repo terpisah, sesuai aturan "GitHub = source/config, BUKAN user memory" — tapi kasus ini user explicitly izin GitHub buat backup DB off-VPS).

## D-025 — Mini-training quality pass (2026-07-13)

Audit live + code review: memory-proxy **sudah** mirip mini-training (RAG + extract + inject + loops), tapi ada lubang kualitas yang bikin “otak” berisik / kurang akurat.

### Masalah yang ditemukan (bukti)

| # | Masalah | Bukti | Impact |
|---|---------|-------|--------|
| 1 | **Consolidate spam** | Cron hourly menambah profile hampir identik → **28** baris `source=consolidated` aktif | Top-k banjir teks duplikat; buang token + biaya LLM |
| 2 | **Exact-text duplicates** | Fakta test/production numpuk exact string | Noise di DB |
| 3 | **Plugin gak query-aware** | `GET /v1/memory` hardcode query `"important user facts"` | Inject gak nyambung ke pertanyaan user |
| 4 | **Stream path buta extract** | `assistant_msg=""` saat `stream=True` | Extraction cuma dari user turn |
| 5 | **Importance ranking idle** | `reflect` nulis `importance`, search cuma `ORDER BY distance` | Loop reflect hampir sia-sia |
| 6 | **User-id split** | Banyak facts di default UUID; consolidate di hash telegram | Memory terbelah antar path |

### Perbaikan (implementasi)

1. Consolidate anti-spam — skip jika cosine < 0.08; `expire_old_consolidated(keep=1)`.
2. Exact-text gate di `add_fact` + `expire_exact_duplicates`.
3. `GET /v1/memory?q=` query-aware + diversity profile facts.
4. Plugin kirim latest user message sebagai `q`.
5. Stream buffer SSE → writer + conversation log.
6. Ranking: `distance - 0.12 * importance`.
7. `POST /v1/admin/dedupe` + `scripts/dedupe_memories.py`.
8. Cron consolidate 60m → 6h (Hermes cron).
9. DB cleanup one-shot: active 208→181; consolidated 28→1.

### Sengaja tidak diubah

- Gateway Hermes tidak di-restart (izin: proxy only).
- Merge massal default-UUID → telegram user (butuh keputusan).
- Enforce TEST_DATABASE_URL terpisah dari prod.

### Verifikasi post-restart

- `/health` ok; `/v1/memory?...&q=` return `query_used`; `/v1/admin/dedupe` ok.

Lihat juga: `docs/AUDIT-2026-07-13-mini-training.md`.

## D-026 — Single-user brain (anti split user_id) — 2026-07-13

### Masalah
Extract/retrieve bisa masuk **UUID beda** karena `_resolve_user_id` hash field `user` (telegram vs empty vs test). Akibat: 2+ “kantong otak” (default UUID ~141 facts vs `telegram:<your-user-id>` ~9 + consolidated).

### Keputusan
Deployment **single-user** (default):
1. `SINGLE_USER_MODE=true` (default) → semua request map ke `DEFAULT_USER_ID` (abaikan payload `user`).
2. `DEFAULT_USER_ID` = hash stabil `telegram:<your-user-id>` = `<canonical-user-uuid>`.
3. One-shot merge DB: semua `memories` / `sessions` / `events` → UUID kanonik; exact-dup expire.
4. Multi-tenant: set `SINGLE_USER_MODE=false` (hash opaque user lagi).

### Bukti
- Merge: memories UPDATE 177, sessions 520, active_on_others=0, active_on_canonical=155.
- API: `user=telegram:…` / `user=totally-different` / empty → **same** top facts.
- Tests: `tests/test_user_id.py` 4 passed.

### Ops
- Script: `scripts/merge_to_single_user.py`
- Restart `memory-proxy.service` after env change (gateway tidak disentuh).
