# Log insight epoch 0

Satu baris per insight ([ADR 0013](../../decisions/0013-epoch-eksperimen-dan-pelestarian.md) butir 4). Angka dibaca dari arsip epoch 0 lewat kunci yang disebut di kolom Sumber, bukan diketik tanpa sumber. Semua angka mode learned berlabel **eksperimental** (BR-35).

- **Penanda:** **[F]** fakta terverifikasi · **[K]** keputusan · **[T]** terbuka, dibawa ke epoch berikutnya.
- **Singkatan sumber:**
  - `E0` = `runs/e0/report.json`;
  - `E1` = `runs/e1/report.json`;
  - `E4` = `runs/e4/e4_report.json`;
  - `P` = `runs/e4/paths_report.json`;
  - `H` = `docs/epochs/epoch-0/holdout.json`.

## Hasil hipotesis (rencana analisis G2)

| ID | Pernyataan | Penanda | Sumber | Tanggal |
| --- | --- | --- | --- | --- |
| I-01 | H1a lolos: median MAE meta-model 0,0035, lebih rendah dari baseline (a), (b), dan (c) dengan p Holm < 0,05 untuk ketiganya. Selisih terhadap (c), model konteks tanpa indikator kekotoran, paling kecil (median −0,0010) | [F] | `E1` `h1a`, `methods` | 13/11/2026 |
| I-02 | H1b lolos: meta-model tidak kalah dari dose–response (d) (batas atas CI selisih MAE −0,0050 < 0,005) dan ±1.550× lebih murah per estimasi | [F] | `E1` `h1b` | 13/11/2026 |
| I-03 | H2 gagal: label noise uniform berdampak tertinggi, tetapi dampak terendah adalah outlier, bukan MCAR. Missing, outlier, dan duplikat eksak ≈ 0 pada `affected_row_frac` 0,10. Dampak MCAR yang kecil pada LightGBM adalah temuan yang sah, bukan kegagalan desain | [F] | `E1` `h2` | 13/11/2026 |
| I-04 | H2b lolos (eksploratif): median τ urutan potensi 0,27 vs urutan volume −0,12 | [F] | `E1` `h2b` | 13/11/2026 |
| I-05 | H3 gagal: 7 dari 31 dataset dalam rentang coverage 85–95%, padahal coverage marginal 0,90. Kalibrasi berbobot dataset menjamin rata-rata, bukan coverage tiap dataset. Coverage per dataset turun seiring galat dan sebaran ΔAUC dataset | [F] | `E1` `h3`; ADR 0012 | 14/11/2026 |
| I-06 | H4 lolos lemah: Spearman skor OOD vs galat 0,19 (CI batas bawah 0,001). Relasinya tidak monoton; desil OOD teratas tidak punya galat terbesar | [F] | `E1` `h4`, `ood_bins` | 13/11/2026 |
| I-07 | H5 lolos: median selisih noise floor estimasi vs terukur 0,0003; kappa status 1,0 tidak informatif karena hampir semua `T` = 0,01 | [F] | `E1` `h5` | 13/11/2026 |

## Ukuran pendukung dan kegagalan

| ID | Pernyataan | Penanda | Sumber | Tanggal |
| --- | --- | --- | --- | --- |
| I-08 | 86% prediksi LODO berstatus `tidak_yakin`, karena interval lebih lebar dari `T`. Presisi `material` 0,93, recall 0,47 | [F] | `E1` `status_quality` | 13/11/2026 |
| I-09 | 32% potensi pemulihan negatif (duplikat konflik dan missing paling sering). Normalisasi satu jenis temuan dapat menaruh profil di luar manifold korpus | [F] | `runs/e1/lodo_recovery.parquet`; ADR 0012 | 13/11/2026 |
| I-10 | 200 run gagal secara struktural: outlier butuh kolom numerik, sehingga tidak berlaku pada 4 dataset kategorikal | [F] | `E1` `failed_errors` | 13/11/2026 |
| I-11 | Meta-model ΔAUC relatif: MAE 0,0070, coverage 0,97; tidak dipakai di R0 karena tidak punya hipotesis sendiri (G3-4) | [F] | `E1` `relative_metamodel` | 13/11/2026 |
| I-12 | Proyeksi waktu komputasi E1 berulang kali terlalu optimistis selama Phase 4 | [F] | `runs/e1_progress.log` | 13/11/2026 |
| I-12b | 1.313 dari 1.325 run pilot E0 tercatat `git_dirty` karena pengembangan paralel; karena itu E1 dijalankan dari worktree terpisah dan seluruh baris E1 bersih | [F] | `E0` `git_dirty_runs`; `E1` `git_dirty_rows` | 13/11/2026 |

## E4 dan konsistensi jalur (Phase 5)

| ID | Pernyataan | Penanda | Sumber | Tanggal |
| --- | --- | --- | --- | --- |
| I-13 | Tidak ada pasangan CleanML dengan versi bersih ground truth: inkonsistensi dibersihkan dengan OpenRefine. Clothing tidak ada di arsip, dan Citation tidak punya berkas versi bersih. Semua bukti E4 sekunder | [F] | `E4` `ineligible`; ADR 0014 | 14/11/2026 |
| I-14 | E4 gagal kriteria: median galat 0,0186 (CI 0,0092–0,0265) > batas 2× MAE LODO 0,0070. Tidak ada pasangan dalam batas. ΔAUC nyata keempat pasangan inkonsistensi ≈ 0, sedangkan meta-model memprediksi 0,010–0,026 | [F] | `E4` `summary`, `pairs` | 14/11/2026 |
| I-15 | Keempat pasangan E4 berskor OOD tinggi (11–865 vs ambang 4,68), sehingga semuanya berstatus `tidak_yakin`: OOD mencegah status yang keliru pada data di luar korpus | [F] | `E4` `pairs[].ood_score`, `status_scan` | 14/11/2026 |
| I-16 | Konsistensi jalur akhir (BR-16) lolos: 31 dataset korpus dan 4 pasangan E4 memberi profil identik dan selisih prediksi 0 | [F] | `P` `passed`; `E4` `br16` | 14/11/2026 |
| I-17 | CSV vs Parquet: 4 dari 31 dataset korpus memberi estimasi berbeda (≤ 0,0005) dari CSV; peringatan `csv_integer_low_cardinality` muncul (BR #12) | [F] | `P` `n_csv_differs` | 14/11/2026 |
| I-18 | Kolom deskriptif `changed_train_cells` di laporan E4 pertama (commit eaeb979) salah hitung karena nilai kosong dibandingkan sebagai teks; diperbaiki di 941ec6b dan E4 dijalankan ulang. ΔAUC, prediksi, dan kriteria tidak terdampak | [F] | `runs/e4/e4_report_eaeb979.json` vs `E4` | 14/11/2026 |
| I-18b | `report.json` E0 dan E1 yang dibangkitkan ulang dari arsip pada commit tercatat (`5144b84`, `10ce452`) identik byte demi byte dengan aslinya | [F] | `runs/e0_regen.log`, `runs/e1_regen.log`; `closure.md` | 14/11/2026 |

## Dibawa ke epoch 1

| ID | Pertanyaan | Penanda | Sumber | Tanggal |
| --- | --- | --- | --- | --- |
| I-19 | Apakah conformal ternormalisasi (X1) memperbaiki coverage per dataset pada holdout? | [T] | `analysis-plan.md` bagian 10 | 14/11/2026 |
| I-20 | Skor OOD alternatif yang monoton terhadap galat | [T] | I-06 | 14/11/2026 |
| I-21 | Jenis kekotoran nyata yang tidak ada di grid korupsi (inkonsistensi representasi kategorikal) tidak punya fitur profil. Meta-model menebak dari sinyal lain dan melebih-lebihkan ΔAUC | [T] | I-14 | 14/11/2026 |
| I-22 | Level korupsi lebih kuat, outlier kategorikal, dataset dengan noise floor > 0,01, dan learner kedua | [T] | ADR 0013 butir 7 | 14/11/2026 |
| I-23 | Holdout epoch 1 tersegel: 15 dataset | [K] | `H` | 14/11/2026 |
