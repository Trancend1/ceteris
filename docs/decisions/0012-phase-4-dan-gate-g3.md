# ADR 0012: Phase 4 — korpus penuh E1, LODO bersarang, artefak v1, dan gate G3

- **Status:** Diusulkan **[T]**. Keputusan implementasi di bawah adalah usulan agent; hasil E1 dan keputusan G3 diisi setelah E1 selesai dan dibawa ke pemilik repo.
- **Tanggal:** 13/11/2026
- **Rilis terdampak:** R0, Phase 4
- **Rujukan:** `execution-plan.md` Phase 4; BR-02, BR-22, BR-23, BR-24, BR-33, BR-40–BR-43, BR-64, BR-81, BR-85; ADR 0006, 0011; [analysis-plan.md](../analysis-plan.md)

G3 membuka klaim angka dan interval (`product.md` 5.1). Gerbang ini butuh artefak v1, laporan akurasi, register klaim, dan hasil H1–H5 yang dilaporkan apa adanya.

## Keputusan implementasi **[K]** (diusulkan agent, ditinjau di G3)

### E1 korpus penuh

- **Protokol:** `configs/e1.yaml` versi 1.0.0, mengikuti rencana analisis yang dibekukan:
  - 31 dataset lolos saringan Phase 1, diurutkan menurut proxy biaya menurun agar beban paralel merata;
  - grid korupsi 1.0.0 (45 tunggal + 10 campuran final), 5 seed per konfigurasi;
  - noise floor terukur 10 seed, noise floor estimasi 5 seed probe pada run seed index 0 (G2-1);
  - baseline (d) pada seed index 0 tiap konfigurasi (G2-7);
  - ablation H2b pada kelima seed tiap konfigurasi campuran.
- **Jumlah pekerjaan:** 13.516 tugas: 31 noise floor terukur, 8.525 run, 1.705 noise floor estimasi, 1.705 baseline (d), dan 1.550 ablation.
- **Provenance bersih:** E1 dijalankan dari worktree terpisah pada commit `df626f2`, sehingga pengembangan Phase 4 di repositori utama tidak membuat baris `run_log` bertanda `git_dirty` (masalah E0, ADR 0011).
- **Mesin:** mesin lokal (G2-6), 6 proses paralel dari 8 inti logis. LightGBM tetap satu thread per proses dan deterministik, sehingga jumlah proses tidak memengaruhi hasil.

### Ablation H2b (`ablation_run`, ADR 0006 butir 2)

- Untuk run campuran, setiap komponen dihapus satu per satu dengan seed run yang sama. Seed tiap langkah korupsi diturunkan dari isi spesifikasinya, sehingga komponen lain disuntikkan dengan RNG yang sama.
- Model dilatih dengan seed learner run dan dinilai pada test set bersih yang sama (BR-01, BR-80).
- **Keuntungan nyata** = AUC tanpa komponen itu − AUC campuran penuh. `auc_full` dihitung ulang dan dibandingkan dengan `auc_dirty` run sebagai pemeriksaan konsistensi.
- Jika komponen duplikat dihapus, jumlah baris berubah sehingga baris yang dipilih langkah berikutnya bisa berbeda. Ini bagian dari arti "memulihkan duplikat".

### Temuan dan potensi pemulihan (F-S12, `ceteris.recovery`)

| Temuan (`issue_type`) | Fitur yang dinormalkan ke nilai tanpa temuan | Volume (`rows_affected_pct`) | Jenis korupsi |
| --- | --- | --- | --- |
| `missing` | 7 fitur missing | Proporsi baris dengan minimal satu sel kosong, dari data setelah kontrak input (terobservasi) | `missing_mcar`, `missing_mar` |
| `label_noise` | `label_noise_rate` | `label_noise_rate` (diestimasi) | `label_uniform`, `label_class_conditional` |
| `duplicate_conflict` | `dup_conflict_rate` | `dup_conflict_rate` (terobservasi) | `duplicate_conflict` |
| `outlier` | 3 fitur outlier | `outlier_row_frac_iforest` (diestimasi) | `outlier` |
| `duplicate_exact` | `dup_row_rate` | `dup_row_rate` (terobservasi) | `duplicate_exact` |

- `const_col_frac` dan `type_inconsistency_rate` punya nilai tanpa temuan, tetapi tidak punya volume baris dan tidak punya padanan korupsi. Keduanya belum menjadi temuan di `ScanReport` v1.
- Temuan hanya dilaporkan bila salah satu fiturnya berbeda dari nilai tanpa temuan. Urutan menurut potensi menurun, seri dipecah menurut nama (AC-12).
- Jalur riset (LODO, H2b) dan jalur scan memakai fungsi yang sama.

### LODO bersarang (F-S11, `ceteris.evaluate`)

- **Pembagian dalam:** dataset latih fold dibagi menjadi proper-train dan kalibrasi dengan `round(0,2 × (N − 1))` dataset kalibrasi (6 dari 30), seed `derive_seed("lodo_inner", dataset uji)`.
- **Tuning:** grid G2-9, grouped CV 3 lipatan (GroupKFold) di proper-train. Skor = rata-rata MAE per dataset yang ditahan (BR-85); seri dipecah menurut urutan grid.
- **Baseline (c) ikut di-tuning** dengan grid dan prosedur yang sama. Alasannya: membandingkan meta-model ter-tuning dengan baseline tanpa tuning akan menguntungkan meta-model secara tidak adil. Baseline (a), (b), dan sanity linear tidak punya hiperparameter.
- **Semua metode dilatih di proper-train**, termasuk baseline, sehingga data latihnya sama.
- **Interval tiap metode:** kuantil conformal berbobot dataset dari residu dataset kalibrasi fold (BR-22).
- **Skor OOD per fold:** kNN (k = 5, standarisasi z) terhadap profil proper-train. Skor ini dipakai H4.
- **Keluaran:** `lodo_result`, satu berkas per (metode, dataset uji). Potensi pemulihan run campuran dari model fold ditulis ke `lodo_recovery.parquet`, dan waktu prediksi meta-model per estimasi ke `lodo_timing.parquet` (H1b).

### Artefak v1 (`ceteris.metamodel.build_artifact_v1`)

- **Hiperparameter:** dipilih dengan grouped CV per dataset atas seluruh korpus, memakai grid yang sama.
- **Skor kalibrasi conformal:** residu absolut LODO bersarang meta-model untuk semua run. Setiap skor berasal dari model fold yang tidak melihat datasetnya, sehingga kuantil memakai 31 dataset, bukan hanya 6 dataset kalibrasi satu fold. Model fold dilatih pada data lebih sedikit daripada model akhir, sehingga residunya cenderung konservatif.
- **`coverage_summary`:** coverage LODO bersarang per dataset (bukti H3).
- **Referensi OOD:** profil seluruh run. Ambang = persentil skor OOD leave-one-dataset-out dengan standarisasi yang sama dengan referensi.
- **Field metadata baru:** `meta_params`, `calibration_basis`, `relative_quantile`, dan `finding_order`. Semuanya punya nilai bawaan, sehingga artefak pilot tetap bisa dimuat. Format artefak tetap "1".
- **Label eksperimental:** artefak dibangun dengan `experimental = true` sampai pemilik repo menyetujui G3 (BR-35). Opsi `--final` baru dipakai setelah itu.

### `ScanReport`

- `findings` diisi tanpa field baru, sehingga `schema_version` tetap "1.0" (BR-60).
- `delta_relative` diisi hanya bila artefak memuat meta-model relatif (G3-4).
- Teks laporan yang menampilkan `recovery_potential` wajib memakai label "potensi pemulihan ideal" (BR-41).

## Hasil E1 **[F]**

Belum ada. E1 sedang berjalan. Angka diisi dari `runs/e1/report.json` (`python -m ceteris.evaluate e1`) setelah E1 dan LODO bersarang selesai, bukan diketik manual.

## Keputusan G3 yang harus ditutup **[T]**

Rekomendasi agent ditulis setelah hasil E1 tersedia. Opsi di bawah sudah bisa dinilai sekarang.

| # | Butir | Opsi | Dasar keputusan dari E1 |
| --- | --- | --- | --- |
| G3-1 | Validitas noise floor estimasi (hal terbuka #2, H5) | A: H5 lolos, BR-05 tetap. B: H5 gagal, `T` tetap 0,01 dan noise floor estimasi hanya informatif (ADR 0006) | `h5` di laporan E1. Kappa bisa tinggi semu bila `T` didominasi lantai 0,01; karena itu subset P5 ikut menentukan |
| G3-2 | Ambang OOD tinggi (hal terbuka #3) | A: persentil ke-95 skor OOD LODO, seperti pilot. B: persentil di desil tempat MAE atau coverage memburuk tajam. C: persentil ke-90 | Tabel `ood_bins` (MAE dan coverage per desil) dan `h4` |
| G3-3 | Pelebaran interval saat OOD tinggi (hal terbuka #3) | A: tidak dilebarkan, karena BR-33 sudah memaksa `tidak_yakin`. B: kuantil terpisah untuk desil OOD teratas | Coverage desil OOD teratas di `ood_bins` |
| G3-4 | ΔAUC relatif saat scan (K7, ADR 0011) | A: meta-model terpisah untuk ΔAUC relatif (rencana skripsi), dengan interval dari kuantil relatif. B: tetap null | `relative_metamodel` di laporan E1 (MAE, coverage) |
| G3-5 | Urutan temuan (fallback H2b) | A: H2b lolos, urutan potensi. B: H2b gagal, `finding_order = volume` dan klaim urutan tidak ditampilkan | `h2b` |
| G3-6 | Potensi pemulihan negatif | A: dilaporkan apa adanya. B: dipotong di 0 dan ditandai. C: temuan berpotensi ≤ 0 tidak diberi angka | Proporsi potensi negatif di `lodo_recovery`. Dry run pada artefak uji E0 memberi potensi `label_noise` negatif pada churn label noise 30%: normalisasi satu fitur menghasilkan profil di luar manifold korpus |
| G3-7 | Label eksperimental | Dicabut hanya untuk klaim yang hipotesisnya lolos (BR-64). Klaim yang gagal mengikuti `product.md` 5.2 | Hasil H1–H5 dan register klaim |

## Konsekuensi

- Bila H1 gagal, klaim "ΔAUC diperkirakan X ± Y" tidak dibuka; produk memakai "indikasi risiko" tanpa angka (`product.md` 5.2), dan tinjauan H1 di Phase 5 menentukan urutan Sprint C.
- Artefak v1 tidak di-commit (folder `artifacts/` diabaikan git). Artefak dibangun ulang dari run store E1 dengan `python -m ceteris.metamodel build`.

## Alternatif yang ditolak

- **Kalibrasi artefak dari 6 dataset kalibrasi satu pembagian.** Kuantil dari 6 dataset terlalu bergantung pada pembagian acak, sedangkan residu LODO bersarang memakai 31 dataset dan setiap skornya tetap bebas kebocoran.
- **Baseline (c) tanpa tuning.** Perbandingan H1a akan bias ke arah meta-model.
- **Menjalankan E1 dari repositori utama.** Pengembangan paralel akan menandai baris `run_log` sebagai `git_dirty`.
