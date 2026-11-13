# Manifest epoch 0

Manifest arsip epoch 0 ([ADR 0013](../../decisions/0013-epoch-eksperimen-dan-pelestarian.md) butir 4, [ADR 0014](../../decisions/0014-phase-5-e4-dan-holdout.md) butir 4). Arsip tidak berubah setelah epoch ditutup: hanya boleh dibaca.

## Lokasi arsip

| Salinan | Lokasi | Status per 14/11/2026 |
| --- | --- | --- |
| Lokal | `D:\DevSpace\Archive\ceteris\epoch-0\` | Dibuat dan diverifikasi |
| Awan | Google Drive milik pemilik repo, folder "Ceteris Epoch Experiment". Tautan sengaja tidak dicatat di repo publik ini karena arsip memuat data CleanML yang lisensinya tidak tercantum (ADR 0014 butir 1) | Folder dibuat; **berkas belum terunggah** per 14/11/2026, sehingga belum diverifikasi |

## Integritas

- `SHA256SUMS.txt` di akar arsip memuat SHA-256 setiap berkas, satu baris per berkas, dengan path relatif terhadap akar arsip.
- SHA-256 `SHA256SUMS.txt`: `b6dc666011d4ea4bfc91dd07d91d039fd3df87906c4a3ec38f33cdc61955436b`.
- Isi arsip: 36.600 berkas, 665.429.088 byte.
- Cara verifikasi dari akar arsip:

```bash
sha256sum -c SHA256SUMS.txt
```

| Bagian | Berkas | Byte |
| --- | --- | --- |
| `runs/e0` (run store pilot E0, termasuk `report.json`) | 5.733 | 51.206.387 |
| `runs/e1` (run store E1, termasuk `report.json`, `lodo_recovery.parquet`, `lodo_timing.parquet`) | 30.759 | 297.187.177 |
| `runs/e4` (laporan E4 dan BR-16, data turunan pasangan dan dataset uji jalur) | 76 | 82.494.244 |
| Log runner (`e0_progress.log`, `e0_baseline_d.log`, `e1_progress.log`, `e1_lodo.log`, `holdout.log`, `e0_regen.log`, `e1_regen.log`) | 7 | 2.965.925 |
| `artifacts/` (`metamodel-0.1.0-pilot`, `metamodel-1.0.0-rc1`, `metamodel-1.0.0`) | 15 | 2.766.232 |
| `sources/` (arsip `CleanML-datasets-2020.zip`, `DatasetDescriptions.pdf`, makalah CleanML) | 3 | 228.758.201 |
| `repo-snapshot/` (`configs/`, `analysis-plan.md`, `holdout.json` pada commit `0b269b1`) | 7 | 50.922 |

## Provenance eksperimen

| Eksperimen | Commit kode (`run_log`) | `git_dirty` | Laporan dibangkitkan oleh | Versi protokol |
| --- | --- | --- | --- | --- |
| E0 pilot | `c297d19` | 1.313 dari 1.325 run dirty | `python -m ceteris.evaluate e0` pada `5144b84` | `configs/e0.yaml` 1.1.0 |
| E1 korpus penuh | `df626f2` | 0 baris | `python -m ceteris.evaluate e1` pada `10ce452` | `configs/e1.yaml` 1.0.0 |
| E4 dan BR-16 | `0b269b1` (E4 ulang), `eaeb979` (BR-16 dan E4 pertama) | tidak | `python -m ceteris.validation e4` / `paths` | `analysis-plan.md` bagian 11 |
| Holdout epoch 1 | `941ec6b` | tidak | `python -m ceteris.validation holdout` | ADR 0014 butir 3 |

- **Spesifikasi:**
  - learner acuan `configs/learner.yaml` 1.0.0;
  - grid korupsi `configs/corruption.yaml` 1.0.0;
  - skema profil v1.
- **`corpus_snapshot`:** `openml-cc18:31:ca50952a4348` (31 dataset OpenML-CC18 lolos saringan Phase 1).
- **Rencana analisis epoch 0:** `docs/analysis-plan.md`, dibekukan 12/11/2026 (G2), dengan revisi bertanggal 14/11/2026 (bagian 10 dan 11) yang ditulis sebelum analisisnya dijalankan.
- **Artefak final:** `metamodel-1.0.0`.

## Dataset holdout epoch 1

- **Daftar:** `docs/epochs/epoch-0/holdout.json`, di-commit di `0b269b1`. Berisi 15 dataset, beserta ID OpenML, versi, checksum sumber, dan hash D₀, latih, serta uji.
- **SHA-256 berkas:**
  - salinan kerja Windows (CRLF): `61d920f1151f774ea88c7e3ab0ea2f9400722b140a4fe7fdeb875e0462738513`;
  - isi blob git (LF), sama dengan `repo-snapshot/docs/holdout.json`: `3a5d2d052d2d3c3d2fba3a242cd14de42f687ba3e0169e05a6491b4de574bef0`.
- **Cara pemilihan:** atribut saringan saja; tidak ada run korupsi, profil, atau eksplorasi lain. Data holdout yang diunduh ada di `data/holdout-epoch-1/`, yang diabaikan git dan tidak termasuk arsip epoch 0.

## Yang tidak diarsipkan

- **Korpus D₀ (`data/corpus/`):** dapat diunduh ulang dari OpenML. Hash D₀ dan test set tiap dataset ada di tabel `corpus_dataset` dan `meta.json`.
- **Cache OpenML dan ekstraksi CleanML:** dapat dibangun ulang dari `sources/`.
