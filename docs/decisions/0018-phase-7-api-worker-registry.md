# ADR 0018: Phase 7 — API, worker, dan model registry

- **Status:** Diterima **[K]**. Rincian pelaksanaan diusulkan agent dalam batas stack terkunci (`architecture.md` 10) dan ADR 0016, lalu ditinjau pemilik repo lewat PR.
- **Tanggal:** 14/11/2026
- **Rilis terdampak:** R1, Phase 7
- **Rujukan:** `execution-plan.md` Phase 7; [backlog R1](../backlog/r1.md) US1.1, US1.4, US2.2; [ADR 0015](0015-epoch-1-sejajar-sprint-c.md), [ADR 0016](0016-paket-keputusan-pra-r1.md); BR-10, BR-23, BR-60, BR-63; AC-3–AC-7, AC-11; NFR-2, NFR-8, NFR-9

## Keputusan **[K]**

### 1. Paket dan dependensi

- **Paket:** server tinggal di `server/ceteris_server/` (ADR 0016 K1) dan ikut wheel `ceteris`. Dependensinya opsional: `pip install ceteris[server]`.
- **Dependensi runtime baru (extra `server`), semuanya permisif dan cocok dengan Apache-2.0:**

| Paket | Lisensi | Peran |
| --- | --- | --- |
| fastapi | MIT | API `/v1` |
| uvicorn | BSD-3-Clause | server ASGI |
| rq | BSD-2-Clause | Redis Queue |
| redis | MIT | klien Redis |
| sqlalchemy | MIT | metadata store |
| pg8000 | BSD-3-Clause | driver Postgres |
| minio | Apache-2.0 | object store S3-compatible |
| python-multipart | Apache-2.0 | unggahan berkas |

- **Dependensi uji baru (grup `dev`):** httpx (BSD-3-Clause), fakeredis (BSD-3-Clause), schemathesis (MIT).
- **Driver Postgres:** pg8000 dipilih alih-alih psycopg, yang berlisensi LGPL-3.0, agar seluruh dependensi tetap permisif.

### 2. Konfigurasi dan mode lokal

- Semua konfigurasi lewat variabel lingkungan `CETERIS_*` (`ceteris_server.settings`).
- **Nilai bawaan untuk pengembangan dan uji:** SQLite, object store berupa folder lokal, dan antrian sinkron di dalam proses.
- **Docker Compose** menimpanya dengan Postgres, Redis Queue, dan MinIO, sesuai stack terkunci.
- Uji tanpa Docker memakai SQLite, folder lokal, dan fakeredis. Uji dengan layanan sungguhan diberi marker `integration`.

### 3. Model registry dan gate rilis (BR-63)

- **Tata letak:** registry adalah prefiks `registry/` di object store. Isinya `manifest.json` (daftar rilis berurutan, SHA-256 tiap berkas, metadata ringkas, dan laporan akurasi) dan berkas artefak per versi.
- **Validasi saat rilis:** artefak dimuat dengan `ceteris.artifact.load_artifact`, sehingga metadata wajib dan kecocokan versi profil diperiksa (BR-23, AC-9).
- **Gate BR-63:** setiap rilis membawa `AccuracyReport` (`regression_set`, MAE, proporsi dataset dengan coverage dalam rentang, jumlah dataset, dan sumber).
  - Pada set regresi yang sama, rilis ditolak bila MAE naik atau proporsi coverage turun.
  - Set regresi yang berbeda tidak sebanding. Rilis hanya boleh dengan alasan tertulis (`override`), yang ikut tercatat di manifest. Ini terjadi misalnya pada artefak epoch 1 yang dievaluasi di dataset holdout.
- **Laporan akurasi artefak `1.0.0`** ada di `configs/registry/metamodel-1.0.0.accuracy.json`. Angkanya dibaca dari `runs/e1/report.json` (`methods.metamodel.mae`, `h3.share`), bukan diketik ulang.
- **AC-4:** API dan worker hanya memakai kelas `Registry`, yang hanya-baca. Rilis lewat `RegistryPublisher` (`python -m ceteris_server.registry publish`), yang dipakai peneliti. Berkas yang diambil dari registry diverifikasi dengan SHA-256 manifest.

### 4. Metadata store

- **Tabel R1:** `dataset`, `scan`, `finding`, `impact_estimate` (dengan `finding_id = null` untuk estimasi total), dan `model_version` (`architecture.md` 6.3).
- **Tanpa data mentah (AC-6):** `scan.report` hanya menyimpan `ScanReport` dalam JSON; snapshot ada di object store dan dirujuk lewat `snapshot_uri`.
- **Skema dibuat dengan `create_all`.** Migrasi berversi (misalnya Alembic) ditambahkan sebelum ada perubahan skema setelah data pengguna tersimpan. Paling cepat itu terjadi saat Phase 8 menambah tabel login.
- **Profil scan belum disimpan.** BR-62 (Phase 8) butuh profil lama untuk diestimasi ulang dengan model baru, sehingga penyimpanan profil ditambahkan di Phase 8 bersama F-L03 **[T]**.

### 5. API dan worker

- **Endpoint R1 Phase 7:**
  - `GET /v1/health`;
  - `POST /v1/datasets`;
  - `POST /v1/scans` (multipart, `202`);
  - `GET /v1/scans/{id}`;
  - `GET /v1/scans/{id}/report`.
  `?format=html` menjawab `501` sampai Phase 11. Tidak ada alias draf awal (ADR 0016 K6).
- **Galat** selalu berbentuk `{"error": {"code", "message", "details"}}`, termasuk galat validasi dan 405, dengan header `Allow` dipertahankan.
- **Batas unggahan:** 500 MB per berkas, dicek bertahap tanpa memuat seluruh berkas ke memori. Format berkas mengikuti BR-10 lewat ekstensi.
- **Worker** memanggil `ceteris.scan.scan_file`, fungsi yang sama dengan CLI, sehingga `ScanReport` REST identik dengan CLI (AC-5). Galat kontrak input tersimpan sebagai `scan.error` dengan kode `input_contract`.
- **Peringatan `outside_corpus_range`** (ADR 0016 K5) ditambahkan di jalur scan (`ceteris.scan`), sehingga CLI, Python API, dan REST sama-sama memuatnya.
- **Jejak (NFR-9):** setiap permintaan punya `trace_id` dari header `x-request-id` atau dibuat baru. `trace_id` diteruskan ke job dan dicatat di log JSON bersama `scan_id`.
- **Autentikasi** belum ada di Phase 7 dan dibangun di Phase 8 (US8.1). Karena itu Docker Compose hanya membuka API di `127.0.0.1`.

## Validasi **[F]** (14/11/2026)

- **Uji:** 227 lulus. Uji baru mencakup:
  - registry dan BR-63;
  - AC-5: REST identik dengan CLI;
  - AC-6;
  - amplop galat;
  - batas unggahan;
  - NFR-2, indikatif di dalam proses: p95 `GET /v1/scans/{id}` < 300 ms;
  - jejak NFR-9;
  - jalur Redis Queue dengan fakeredis;
  - kontrak OpenAPI terhadap snapshot `ScanReport` 1.0;
  - schemathesis pada kelima endpoint;
  - uji impor AC-3 yang diperluas ke server.
- **Pemeriksaan statis:** ruff dan mypy strict bersih untuk `ceteris` dan `ceteris_server`.
- **Uji asap lokal:** artefak `metamodel-1.0.0` dirilis ke registry lokal. Uvicorn lalu memindai satu dataset korpus lewat `POST /v1/scans` sampai berstatus `done` dalam ±5 detik, dengan `trace_id` tercatat di log.
- **Belum dijalankan:** `docker compose up` dan uji `integration` dengan Postgres, Redis, dan MinIO sungguhan, karena daemon Docker tidak berjalan di mesin pengembangan per 14/11/2026. `docker compose config` valid.

## Konsekuensi

- Phase 8 menambah login (US8.1), histori (US2.1), penyimpanan profil untuk BR-62, migrasi berversi, dan uji beban NFR-1.
- Kriteria Phase 7 yang bergantung pada layanan sungguhan baru tuntas setelah uji `integration` dan `docker compose up` dijalankan.

## Alternatif yang ditolak

- **psycopg sebagai driver Postgres.** Berlisensi LGPL-3.0; pg8000 setara untuk beban R1 dan permisif.
- **Registry sebagai tabel di Postgres.** Arsitektur menetapkan registry di object store dengan manifest, sehingga artefak dan manifest bisa dipindah bersama tanpa basis data.
- **Worker yang menghitung ulang profil dengan kode sendiri.** Melanggar AC-1 dan AC-5; worker harus membungkus fungsi scan yang sama.
