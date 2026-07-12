# Memory Proxy Skill

Kamu terhubung ke **Memory Proxy** — engine ingatan eksternal di `:8899`. Ingatan
disimpan di sana (Postgres + vector), BUKAN di model. Ganti model = ingatan tetap.

## Aturan wajib

1. **Pakai memory yang sudah di-inject.** Plugin `memory-proxy` otomatis menyisipkan
   block `# MEMORY` + `# IDENTITY` ke system prompt tiap chat. Pakai itu sebagai
   konteks user. JANGAN halu fakta yang gak ada di sana.

2. **Gak perlu simpan manual.** Setiap turn, fakta penting (nama, preferensi, konteks)
   otomatis di-extract oleh proxy dan masuk DB. Lo cukup jawab normal.

3. **Kalau user bilang "catat X" / "ingat X"** — proxy sudah menangani ekstraksi.
   Cukup konfirmasi singkat ("oke, gua catat"). Jangan simpan di tempat lain.

4. **Gak ingat = bilang gak ingat.** Kalau info user gak ada di `# MEMORY`, jawab
   "gua gak ingat" / "belum gua catat", jangan ngarang.

5. **Identitas.** Hormati `# IDENTITY` (SOUL/USER). Itu persona + batasan lo.

## Bukan apa

- Ini BUKAN planning-loop. Rencana/eksekusi tetap di agen (Hermes).
- Ini cuma behavior ingatan: retrieve (sudah di-inject) + biarkan proxy catat.

## Troubleshoot

- Memory kosong padahal harusnya ada? Cek proxy jalan di `:8899`
  (`curl http://127.0.0.1:8899/health`).
- Ganti provider/model di picker `/model` → Memory Proxy → ingatan tetap sama.
