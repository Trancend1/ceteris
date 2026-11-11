# ADR 0001: Paket Python tunggal `ceteris` sebagai basis R0

- **Status:** Diterima **[K]**
- **Tanggal:** 10/11/2026
- **Rilis terdampak:** R0, lalu worker R1
- **Rujukan:** `architecture.md` bagian 1, 3, 4, 10; NFR-11; BR-84

## Konteks

R0 membuktikan mode *learned* (F-S01–F-S14) tanpa server. Seluruh logika perhitungan harus bisa dipakai ulang oleh worker pada R1 tanpa ditulis ulang. Hasil eksperimen harus reprodusibel.

## Keputusan

1. Seluruh kode R0 berada dalam satu paket Python 3.11 bernama `ceteris` (modul `corpus`, `corrupt`, `train`, `dqprofile`, `store`, `metamodel`, `uncertainty`, `evaluate`, `recovery`, `scan`).
2. Lingkungan dikelola `uv` dengan `uv.lock`; Docker dipakai untuk image rilis.
3. R0 tidak punya server. CLI memakai Typer, skema keluaran memakai Pydantic v2, penyimpanan memakai Parquet + DuckDB.
4. Data tabular memakai Polars dan PyArrow; pandas hanya untuk interop scikit-learn. Learner acuan adalah LightGBM yang dijalankan deterministik.
5. Keacakan memakai seed eksplisit yang diturunkan dari (`dataset_id`, `config_id`, indeks seed).

## Konsekuensi

- Worker R1 membungkus paket yang sama; tidak ada port ulang logika.
- Struktur repository awal cukup satu paket; pemisahan paket inti dan server tetap **[T]** (`architecture.md` bagian 11, butir 1).
- Dependensi baru diperiksa lisensinya. cleanlab tetap **[T]** (butir 2). Pembaruan 12/11/2026: cleanlab berlisensi Apache-2.0 sejak 2.8.0; yang masih terbuka adalah pilihan pustaka, bukan lisensinya.

## Alternatif yang ditolak

- Beberapa paket sejak R0: menambah beban rilis sebelum ada konsumen kedua.
- Server sejak R0: bukan syarat untuk membuktikan H1 dan menunda bukti akurasi.
