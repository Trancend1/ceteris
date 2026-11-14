# ADR 0016: Paket keputusan pra-R1 (Phase 6)

- **Status:** Diterima **[K]** oleh pemilik repo 14/11/2026.
- **Tanggal:** 14/11/2026
- **Rilis terdampak:** R1 (Sprint C dan D)
- **Rujukan:** `execution-plan.md` Phase 6; `architecture.md` bagian 11 #1, #3, #5, #6; `product.md` 7.2 #1, #3; `business-rules.md` hal terbuka #7; BR-10, BR-12, BR-71; AC-5, AC-6; NFR-4, NFR-7; [ADR 0015](0015-epoch-1-sejajar-sprint-c.md)

Phase 6 menutup semua hal terbuka berbatas "Sebelum R1". Pola paket keputusan mengikuti [ADR 0009](0009-paket-keputusan-g1.md): satu ADR untuk beberapa keputusan yang diambil bersamaan.

## Keputusan **[K]**

### K1. Satu repository (arsitektur #1)

- Kode server R1 tinggal di repository ini:
  - `ceteris/`: paket inti, tidak berubah;
  - `server/`: API FastAPI dan worker;
  - `web/`: Web UI Next.js, dibuat mulai Phase 10 setelah G6.
- Worker mengimpor paket `ceteris` yang sama, sehingga `ScanReport` identik di CLI, Python API, dan REST (AC-5) diuji dalam satu CI.
- Jalur scan tetap tidak mengimpor kode eksperimen (AC-3). `server/` hanya boleh mengimpor jalur scan dan pemuat artefak, dan uji impor diperluas ke `server/`.
- Pemisahan repository ditinjau ulang bila ada kebutuhan rilis terpisah. Itu memerlukan ADR baru.

### K2. Tanpa versi hosted di R1 (arsitektur #3, product 7.2 #3)

- R1 berbentuk lokal (`pip` atau image Docker) dan self-host (Docker Compose; Helm chart bila diputuskan di Phase 8).
- Kebutuhan khusus hosted tidak dibangun di R1: retensi ≤ 24 jam (NFR-7, BR-72 bagian hosted) dan ketersediaan 99,5% (NFR-4).
- Uji 5 ML engineer (kriteria keluar R1) berjalan pada instans self-host di lingkungan masing-masing.
- Hosted ditinjau ulang setelah R1.

### K3. Model distribusi: open-core (product 7.2 #1)

- Paket inti `ceteris` (scan, profil, pemuat artefak, CLI, Python API) berlisensi terbuka. Fitur platform tertentu boleh berlisensi komersial di rilis berikutnya.
- **[F]** Sampai 14/11/2026, repository publik ini belum punya berkas `LICENSE`, sehingga secara hukum seluruh isinya *all rights reserved*.
- **[K]** Repository berlisensi **Apache-2.0** sejak 14/11/2026, atas pilihan pemilik repo:
  - berkas `LICENSE` berisi teks resmi dari apache.org (SHA-256 `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30`);
  - `pyproject.toml` memuat `license = "Apache-2.0"`.
  Apache-2.0 sejalan dengan dependensi utama (cleanlab ≥ 2.8.0 Apache-2.0, LightGBM MIT).
- **[T]** Batas fitur terbuka vs komersial diputuskan sebelum fitur komersial pertama dibangun (paling cepat R2). Sampai saat itu seluruh kode di repository ini berlisensi Apache-2.0.

### K4. Login R1: akun lokal dan token API (ketidaksesuaian F-L05 vs arsitektur)

- **Web UI:** akun lokal (email dan kata sandi ter-hash dengan algoritme modern, misalnya Argon2id).
- **SDK/CLI dan otomasi:** bearer token API per pengguna.
- **OIDC tetap di R2,** bersama RBAC (F-L09). Di R1 semua pengguna satu instans setara.
- F-L05 tetap berarti "login dan paket self-host". Dokumen diselaraskan: `product.md` F-L05 menyebut mekanismenya, dan `architecture.md` bagian 2 tetap menaruh OIDC di R2.

### K5. Ukuran input dan data di luar rentang korpus (arsitektur #5, BR hal terbuka #7)

- **Batas tetap BR-10:** ≤ 1.000.000 baris dan ≤ 500 kolom. Probe tetap memakai sampel ≤ 100.000 baris (BR-12); statistik terobservasi lain dihitung pada seluruh baris.
- **Data di luar rentang korpus diterima,** dengan peringatan `outside_corpus_range` di `input_warnings`. Rentang korpus adalah 2.000–50.000 baris setelah kontrak input. Status tetap ditentukan aturan biasa, termasuk OOD (BR-33). Peringatan menambah isi `input_warnings`, bukan field baru, sehingga `schema_version` tidak naik.
- **Unggahan lewat web (F-L02)** dibatasi 500 MB per berkas. Unggahan yang lebih besar ditolak dengan alasan, dan pengguna diarahkan ke SDK/CLI.
- Implementasi peringatan masuk backlog Phase 7 (US1.1).

### K6. Alias endpoint draf awal tidak dipertahankan (arsitektur #6)

- Belum ada pengguna endpoint draf awal (`POST /scan`, `GET /report/{id}`).
- `/v1` hanya memuat endpoint resmi di `architecture.md` 6.4.

### K7. Backlog R1 direkonstruksi dari dokumen repository

- **[F]** Draf Long-MVP, sumber user story `US x.y`, tidak ada di repository ini.
- Backlog R1 ([docs/backlog/r1.md](../backlog/r1.md)) ditulis ulang dari `product.md`, `architecture.md`, dan `business-rules.md`, memakai ID user story yang sudah dirujuk di feature index.
- Backlog ditandai sebagai rekonstruksi. Bila draf asli ditemukan, perbedaannya dicatat sebagai revisi bertanggal.

## Konsekuensi

- **Hal terbuka yang ditutup:** `architecture.md` #1, #3, #5, #6; `product.md` 7.2 #1 dan #3; `business-rules.md` #7. Hal terbuka baru: batas fitur terbuka vs komersial (K3), sebelum fitur komersial pertama.
- Struktur repository di `architecture.md` bagian 10 bertambah `server/` dan `web/`, yang dibuat saat phase terkait dimulai.
- Uji impor (AC-3) diperluas ke kode server di Phase 7.

## Alternatif yang ditolak

- **Dua repository.** Setiap perubahan inti butuh rilis paket sebelum server bisa memakainya. Untuk satu pemilik repository, biaya ini tidak sebanding dengan manfaatnya di R1.
- **Hosted demo di R1.** Menambah retensi, uptime, dan keamanan multi-pengguna sebelum nilai produk terbukti, dan bertentangan dengan prinsip data diproses di lingkungan pengguna.
- **Menolak atau menyampel data ke rentang korpus.** Menolak menaikkan tingkat penolakan input di atas KPI (< 15%). Menyampel ke 50.000 baris membuat profil tidak mewakili data penuh. OOD sudah menangani data yang jauh dari korpus.
- **OIDC sejak R1.** Memajukan integrasi identity provider sebelum ada kebutuhan multi-tim (RBAC di R2).
