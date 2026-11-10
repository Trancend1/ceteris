# ADR 0004: Perkakas kualitas kode dan dependensi kerangka R0

- **Status:** Diterima **[K]** (arahan pemilik repo, 10/11/2026)
- **Tanggal:** 10/11/2026
- **Rilis terdampak:** R0
- **Rujukan:** `architecture.md` bagian 8 (NFR-6, NFR-11) dan bagian 10; AGENTS.md bagian 5 dan 6

## Konteks

Dokumen stack menyebut pytest dan hypothesis untuk uji, serta cakupan ≥ 80% (NFR-11), tetapi tidak menyebut linter, pemeriksa tipe, atau alat cakupan. Kerangka R0 butuh keputusan agar `pyproject.toml` tidak memuat tebakan.

## Keputusan

1. Linter dan formatter: **ruff** (aturan `E`, `F`, `I`, `B`, `UP`, panjang baris 100).
2. Pemeriksa tipe: **mypy** mode `strict` pada paket `ceteris`.
3. Uji: **pytest**, **hypothesis**, dan **pytest-cov** (untuk laporan cakupan NFR-11).
4. Dependensi runtime R0 mengikuti `architecture.md` bagian 10 (Polars, pandas, PyArrow, LightGBM, scikit-learn, SciPy, statsmodels, DuckDB, Typer, Pydantic v2). cleanlab **tidak** dimasukkan karena lisensi AGPL-3.0 masih **[T]**.
5. Notebook (JupyterLab, ipykernel, papermill, nbstripout) berada di grup dependensi `notebook` terpisah, bukan bagian runtime.
6. Build backend: hatchling, tata letak datar (`ceteris/` di root) sesuai AGENTS.md bagian 5.

## Konsekuensi

- Perintah standar: `uv sync`, `uv run pytest`, `uv run ruff check .`, `uv run mypy`.
- Lisensi semua dependensi di atas permisif (BSD, MIT, atau Apache-2.0). Dependensi baru tetap diperiksa lisensinya dan disebut di PR.
- Entri `ruff` dan `mypy` di `.claude/settings.json` kini punya dasar keputusan.
- `uv.lock` di-commit untuk reprodusibilitas (NFR R0).

## Alternatif yang ditolak

- Black + flake8 + isort: tiga alat untuk pekerjaan yang dicakup ruff.
- Tanpa pemeriksa tipe: kontrak `ScanReport` dan profil mendapat manfaat dari tipe ketat.
