# ADR 0020: Phase 8 — histori, login, dan self-host

- **Status:** Diterima **[K]** oleh pemilik repo 14/11/2026 (butir K1–K3). Rincian pelaksanaan diusulkan agent dan ditinjau lewat PR.
- **Tanggal:** 14/11/2026
- **Rilis terdampak:** R1, Phase 8, gerbang G5
- **Rujukan:** `execution-plan.md` Phase 8; [backlog R1](../backlog/r1.md) US2.1, US8.1, US8.3; [ADR 0016](0016-paket-keputusan-pra-r1.md) K2, K4; [ADR 0018](0018-phase-7-api-worker-registry.md); [ADR 0019](0019-object-store-seaweedfs.md); BR-61, BR-62, BR-71, BR-72; AC-6, AC-10; NFR-1, NFR-5, NFR-6, NFR-7, NFR-9, NFR-10

## Keputusan pemilik repo **[K]**

1. **K1: tanpa Helm chart di R1.** Self-host R1 hanya Docker Compose di satu mesin. Helm chart dan Kubernetes ditunda sampai ada pengguna yang membutuhkannya. `architecture.md` 10 diselaraskan.
2. **K2: TLS lewat Caddy, enkripsi at-rest oleh operator (NFR-5).**
   - Compose menambah reverse proxy Caddy `caddy:2.11.9-alpine` (Apache-2.0), satu-satunya layanan yang dibuka ke jaringan. Port API 8000 tidak dibuka.
   - Caddy memakai TLS 1.2 sebagai versi minimum: CA internal untuk `localhost`, ACME untuk domain publik.
   - Enkripsi at-rest volume Postgres, object store, dan Caddy adalah tanggung jawab operator (disk terenkripsi), dijelaskan di `docs/self-host.md`.
3. **K3: token sesi login berlaku 12 jam.** Token API untuk SDK dan CI berlaku sampai dicabut, dan teksnya hanya ditampilkan sekali saat dibuat.

## Keputusan pelaksanaan **[K]**

### Login (US8.1)

- **Penyimpanan:** akun lokal di tabel `app_user`, kata sandi sebagai hash Argon2id (`argon2-cffi`, MIT) dengan panjang minimum 12 karakter.
- **Pembuatan akun:** tidak ada pendaftaran publik. Admin membuat akun lewat `python -m ceteris_server.auth create-user`.
- **Token:** berbentuk `ctr_<acak 32 byte>`. Tabel `api_token` hanya menyimpan hash SHA-256 dan awalan 12 karakter untuk ditampilkan.
- **Endpoint baru:** `POST /v1/auth/login`, `POST /v1/auth/logout`, `GET /v1/me`, `POST|GET /v1/tokens`, `DELETE /v1/tokens/{id}`.
- **Proteksi:** semua endpoint `/v1` kecuali `health` dan `auth/login` menolak permintaan tanpa token bearer yang sah dengan `401` `unauthorized`.
- **Pesan galat login** sama untuk email tak dikenal dan kata sandi salah, dan verifikasinya memakan waktu yang sama (hash tiruan), agar email terdaftar tidak bisa ditebak.
- **Kesetaraan pengguna:** di R1 semua pengguna satu instans setara (ADR 0016 K4); RBAC dan OIDC di R2. Pembatasan laju percobaan login belum dibangun **[T]**. Mitigasinya, API hanya dicapai lewat Caddy dan instans self-host berada di jaringan tim; pembatasan ditambahkan bersama RBAC di R2.

### Histori dan perbandingan (US2.1, BR-61, BR-62)

- **Endpoint:** `GET /v1/datasets/{id}/scans` mengembalikan daftar scan (terbaru di atas) dan perbandingan scan selesai terbaru dengan scan selesai sebelumnya.
- **Model sama:** selisih ΔAUC dan perubahan status dibaca dari laporan tersimpan (`basis = same_model`).
- **Model berbeda (BR-62):** profil scan sebelumnya yang tersimpan diestimasi ulang dengan artefak scan terbaru lewat `ceteris.scan.estimate_from_profile`, yaitu fungsi estimasi yang sama dengan scan (AC-1). Perbedaan versi disebutkan (`basis = reestimated`).
- **Tanpa penimpaan (BR-61):** perbandingan dihitung saat diminta dan tidak disimpan; laporan lama tidak diubah.
- **Profil tersimpan:** tabel `scan_profile` menyimpan fitur profil agregat, versi skema profil, dan flag kebocoran. Tidak ada baris data (AC-6). Ini menutup hal **[T]** ADR 0018 butir 4.

### Migrasi berversi

- **Alembic (MIT):** proses API dan worker menjalankan `Database.migrate()` saat mulai. Revisi `0001` adalah skema Phase 7, revisi `0002` menambah `scan_profile`, `app_user`, dan `api_token`.
- **Basis data Phase 7** (dibuat `create_all`, tanpa `alembic_version`) ditandai di revisi `0001` lalu dinaikkan.

### CI (NFR-6)

- **Workflow:** `.github/workflows/ci.yml` berjalan di setiap PR dan push ke `main`, dengan tiga job:
  - **test:** ruff, format, mypy, dan pytest;
  - **security:**
    - Semgrep `p/python` sebagai SAST;
    - pip-audit untuk kerentanan dependensi;
    - pip-licenses untuk lisensi, menolak GPL dan AGPL sesuai ADR 0016 K3;
  - **image:** build image lalu pemindaian Trivy untuk kerentanan CRITICAL/HIGH yang sudah ada perbaikannya.
- **Alat:** dijalankan lewat `uvx` atau action, bukan dependensi paket.

### Kontrak OpenAPI `/v1` (G5, NFR-10, AC-10)

- Snapshot OpenAPI ada di `tests/contracts/openapi_v1.json`. Uji menolak perbedaan antara skema yang disajikan dan snapshot.
- Snapshot ini kandidat yang dibekukan saat G5 disetujui. Sesudahnya, perubahan yang merusak hanya di versi mayor.

### Uji beban NFR-1

`tests/test_load_nfr1.py` (marker `load`) memindai 100.000 baris × 100 kolom sintetis tiga kali dengan artefak `metamodel-1.0.0` dan mensyaratkan median ≤ 5 menit.

### Optimasi scan untuk NFR-1 (hasil tidak berubah)

Profiling satu scan 100.000 × 100 (334 detik dengan profiler): noise floor estimasi 169 detik (25 fit LightGBM), Spearman indikator missing 70,5 detik, probe out-of-fold ±33 detik, probe kebocoran 30,6 detik. Semua fit LightGBM berjalan berurutan dengan 1 thread, karena `configs/learner.yaml` memakai `num_threads: 1` (dibekukan di G1).

- **Spearman indikator missing** (`_missing_feature_assoc`) kini menghitung peringkat tiap kolom numerik sekali saja. Peringkat indikator 0/1 dihitung dengan rumus tertutup peringkat rata-rata, lalu `np.corrcoef` dipanggil atas dua kolom seperti `scipy.stats.spearmanr`. Hasilnya identik bit demi bit dengan `Series.corr(method="spearman")` milik profil v1 (`tests/test_parallel_identical.py`).
- **Probe kebocoran** menjalankan pohon scikit-learn per fitur di thread (`CETERIS_SCAN_THREADS`, bawaan jumlah inti; hanya jalur scan). Setiap thread memakai salinan kolomnya sendiri, dan urutan pemilihan fitur terbaik tetap. Jalur riset tetap berurutan.
- **Fit LightGBM tetap berurutan.** Dua pendekatan dicoba lalu ditolak **[F]**:
  - Thread untuk fit LightGBM menyebabkan *access violation* di kode C LightGBM saat beberapa thread melatih bersamaan. Terjadi pada uji konsistensi jalur di dataset 1497 dan 40701, dengan stack trace dari `faulthandler`.
  - Pool proses memang aman dari crash, tetapi di Windows memakai *spawn*: skrip yang memanggil Python API tanpa pelindung `if __name__ == "__main__"` menjalankan ulang dirinya tanpa henti. Biaya membuat pool juga melambatkan data kecil.

  Risiko itu tidak sebanding dengan percepatannya.
- **Hasil:** scan tetap deterministik dan profilnya tidak berubah. Uji konsistensi jalur terhadap fitur profil di run store E1 dijalankan ulang untuk membuktikannya (bagian Validasi).

## Validasi **[F]** (14/11/2026)

- **Uji otomatis:** 237 lulus. Uji baru mencakup login, token, kedaluwarsa sesi, kebijakan kata sandi, kata sandi dan token tidak masuk log, BR-61, BR-62 (model sama dan estimasi ulang), migrasi dari skema Phase 7, dan snapshot OpenAPI. Schemathesis mencakup 12 endpoint dan menemukan header `Allow` 405 yang tidak lengkap; bug itu sudah diperbaiki. Ruff dan mypy strict bersih.
- **Docker Compose:** semua layanan sehat, termasuk Caddy.
  - Basis data Postgres dari Phase 7 dinaikkan otomatis ke revisi `0002`.
  - Lewat HTTPS (CA internal Caddy):
    - `/v1/health` menjawab;
    - permintaan tanpa token ditolak `401`;
    - TLS 1.1 ditolak dan TLS 1.2 diterima;
    - login, pembuatan token API, dua scan selesai, dan histori `same_model` berjalan;
    - logout mencabut sesi.
  - Kata sandi dan token tidak muncul di log API maupun worker.
  - Uji `integration` lulus.
- **Keamanan dependensi dan kode, dijalankan lokal:**
  - Semgrep `p/python`: 0 temuan dari 151 aturan di 28 berkas.
  - pip-audit: tidak ada kerentanan yang diketahui.
  - Tidak ada dependensi berlisensi GPL atau AGPL.
  - Trivy dan job CI di GitHub belum dijalankan, karena CI baru aktif saat PR dibuka.
- **NFR-1, pengukuran pertama: tidak lolos, tipis.** Tiga scan 100.000 × 100 memakan 331,4, 304,6, dan 293,9 detik; mediannya 304,6 detik, di atas batas 300 detik. Diukur di mesin pengembangan 4 inti yang sedang menjalankan layanan Docker lain.
- **NFR-1, setelah optimasi (pilihan pemilik repo): lolos.**
  - Tiga scan memakan 264,1, 260,0, dan 260,7 detik; mediannya 260,7 detik, dengan sisa ruang sekitar 13%. Kondisi mesinnya sama.
  - Batas uji tidak diubah. Kedua pengukuran tercatat; pengukuran kedua tidak menggantikan yang pertama.
- **Profil tidak berubah setelah optimasi:** uji konsistensi jalur (`python -m ceteris.validation paths`, 15/11/2026) lulus pada 31 dari 31 dataset korpus.
  - Profil scan identik dengan fitur di run store E1, dan selisih prediksinya 0.
  - Selisih estimasi CSV identik dengan run `eaeb979`.
  - Run ini memakai kode optimasi yang belum di-commit (`git_dirty` true di laporan). Kode yang di-commit sama dengan kode itu.

## Konsekuensi

- G5 menunggu persetujuan pemilik repo: OpenAPI `/v1` dibekukan, uji kontrak lulus, self-host berjalan dari repository bersih.
- Panduan operator ada di `docs/self-host.md`.

## Alternatif yang ditolak

- **Token tanpa penyimpanan (JWT) untuk sesi.** Token tidak bisa dicabut seketika tanpa daftar blokir, padahal US8.1 meminta token yang dicabut langsung ditolak.
- **Menyimpan profil di laporan `ScanReport`.** Mengubah kontrak `ScanReport` (BR-60). Tabel terpisah tidak menyentuh kontrak.
- **Enkripsi volume di dalam compose.** Bergantung pada sistem operasi host. Enkripsi disk operator lebih andal dan umum.
