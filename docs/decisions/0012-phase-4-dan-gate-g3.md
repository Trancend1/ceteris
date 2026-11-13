# ADR 0012: Phase 4 — korpus penuh E1, LODO bersarang, artefak v1, dan gate G3

- **Status:** Diterima **[K]**. Gate G3 disetujui pemilik repo 14/11/2026: semua rekomendasi G3-1 sampai G3-7 dan opsi 3 untuk H3.
- **Tanggal:** 13/11/2026
- **Rilis terdampak:** R0, Phase 4
- **Rujukan:** `execution-plan.md` Phase 4; BR-02, BR-22, BR-23, BR-24, BR-33, BR-40–BR-43, BR-64, BR-81, BR-85; ADR 0006, 0011; [analysis-plan.md](../analysis-plan.md)

G3 membuka klaim angka dan interval (`product.md` 5.1). Gerbang ini butuh artefak v1, laporan akurasi, register klaim, dan hasil H1–H5 yang dilaporkan apa adanya.

## Keputusan implementasi **[K]**

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

### Tafsiran ukuran rencana analisis

Butir ini memperjelas pelaksanaan rencana analisis yang dibekukan. Ukuran dan kriterianya tidak berubah.

- **H2, kurva dosis–respons:** median antar-seed per level, dengan titik (0, 0). Nilai pada `affected_row_frac` = 0,10 diinterpolasi linear. Bila 0,10 di luar rentang level, nilainya NaN dan tidak diekstrapolasi.
- **H2, varian kolom missing:** dirata-ratakan hanya bila kedua varian mencapai 0,10; bila tidak, NaN. Akibatnya nilai satu varian tidak tercampur dengan nilai dua varian antar-dataset. Dataset dengan nilai NaN dikeluarkan dari uji Friedman dan dicatat di `excluded_datasets`.
- **H2, peran Friedman:** kolom kriteria rencana hanya menyebut post-hoc. Karena itu `passed` mengikuti kriteria itu, sedangkan p Friedman dilaporkan terpisah (`friedman_significant`). Bila post-hoc lolos tetapi Friedman tidak signifikan, hal itu disebut eksplisit di laporan G3.
- **H1b, biaya:** detik baseline (d) dan detik prediksi meta-model per estimasi diringkas dengan median per dataset lalu median antar-dataset (BR-85).
- **Bootstrap:** semua CI, termasuk H4, memakai 10.000 resample atas dataset (rencana bagian 1).
- **Noise floor:** analisis gagal dengan galat bila sebuah dataset punya kurang dari 10 seed terukur atau sebuah run kurang dari 5 seed estimasi (G2-1).

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

Sumber: `runs/e1/report.json`, dihasilkan dari run store oleh `python -m ceteris.evaluate e1 --store runs/e1` (kode `10ce452`), dan `runs/e1/lodo_recovery.parquet`. Semua angka berlabel **eksperimental** sampai G3 disetujui (BR-35). Ringkasan per dataset memakai median antar-dataset (BR-85).

### Eksekusi dan provenance

- **Durasi:** 13.516 tugas selesai dalam ±22 jam dinding dengan 6 proses (13/11/2026). Waktunya sedikit di atas proyeksi 17–20 jam, tetapi waktu CPU-nya masih di bawah batas 2× proyeksi (G2-6).
- **Penolakan:** 13.136 tugas berhasil dan 380 ditolak. Semua penolakan bersifat struktural: korupsi outlier butuh kolom numerik, sedangkan empat dataset hanya berisi kolom kategorikal (kr-vs-kp, splice, PhishingWebsites, dna). Masing-masing kehilangan 10 konfigurasi outlier, yaitu 95 tugas per dataset. Tidak ada kegagalan lain.
- **Isi run store:** 8.325 run korupsi dan 3.325 baris ablation.
- **Provenance:** semua baris `run_log` mencatat commit `df626f2` dengan `git_dirty = false`.
- **Konsistensi ablation:** `auc_full` ablation sama persis dengan `auc_dirty` run-nya (selisih maksimum 0).
- **Profil:** tidak ada fitur profil yang kosong atau NaN. Log memuat `ConstantInputWarning` dari korelasi Spearman pada kolom konstan, tetapi peringatan itu tidak memengaruhi nilai fitur.

### Hipotesis

| Hipotesis | Hasil | Lolos? |
| --- | --- | --- |
| **H1a** | Median MAE per dataset: meta-model 0,0035; (a) 0,0102; (b) 0,0101; (c) 0,0046. Median selisih terhadap (a) −0,0071 (CI 95% −0,0079 s.d. −0,0057), menang di 31/31 dataset. Terhadap (b) −0,0068, menang 31/31. Terhadap (c) −0,0010 (CI −0,0018 s.d. −0,0002), menang 22/31. p Holm: 1,4·10⁻⁹; 1,4·10⁻⁹; 0,004 | **Ya** |
| **H1b** | Median selisih MAE (meta − d) −0,0074, CI 95% −0,0144 s.d. −0,0050; batas atas < 0,005. Baseline (d) butuh median 8,6 detik per estimasi, meta-model 0,0056 detik (±1.550× lebih murah, di luar profil yang dipakai keduanya) | **Ya** |
| **H2** | Median ΔAUC pada `affected_row_frac` 0,10 (27 dataset): label uniform 0,0091; label class-conditional 0,0059; duplikat-konflik 0,0039; missing MAR 0,00007; missing MCAR 0,00006; duplikat eksak 0,000002; outlier −0,000004. Friedman p = 1,8·10⁻²². Label noise tertinggi, tetapi **terendah adalah outlier, bukan MCAR**. MCAR, MAR, outlier, dan duplikat eksak tidak berbeda bermakna satu sama lain (p Holm ≥ 0,39), dan keempatnya ≈ 0. Empat dataset kategorikal dikeluarkan karena tidak punya outlier | **Tidak**, menurut kriteria yang dibekukan |
| **H2b** (eksploratif) | Median τ per dataset: urutan potensi 0,27, urutan volume −0,12. Median selisih 0,28 (CI 0,21 s.d. 0,47), Wilcoxon satu sisi p = 1,3·10⁻⁶; 1.450 run campuran, 31 dataset | **Ya** |
| **H3** | Coverage per dataset median 0,956, rentang 0,53–1,00. Hanya **7 dari 31** dataset (23%, CI 10–41%) dalam rentang 85–95%. 17 dataset di atas 95%: umumnya multikelas dengan ΔAUC kecil. 7 dataset di bawah 85%: phoneme 0,53, kc1 0,55, jm1 0,61, madelon 0,66, wilt 0,78, ozone 0,79, first-order 0,84; umumnya biner dengan ΔAUC besar. Kuantil conformal berbobot dataset menjamin coverage rata-rata, bukan coverage tiap dataset | **Tidak** |
| **H4** | Spearman skor OOD vs galat absolut 0,186, CI 95% 0,001 s.d. 0,355 (10.000 resample dataset). Batas bawah nyaris 0. Hubungannya tidak monoton: desil OOD 5–8 punya MAE 0,007–0,011 dan coverage 0,85–0,88, tetapi desil teratas kembali baik (MAE 0,004, coverage 0,97). 5% skor teratas didominasi segment dan electricity, dengan MAE lebih rendah dan coverage lebih tinggi daripada sisanya | **Ya**, tetapi lemah |
| **H5** | Selisih absolut median noise floor estimasi vs terukur 0,0003 (CI 0,0002–0,0004); bias −0,0002. Subset dekat 0,01 (8 dataset): selisih 0,0021, bias −0,0019 (estimasi lebih rendah). Kappa = 1,0 di keduanya, tetapi tidak informatif: hanya madelon yang noise floor terukurnya di atas 0,01 (0,0116), sehingga `T` hampir selalu 0,01 apa pun noise floor-nya | **Ya**, dengan catatan |

### Ukuran pendukung (tanpa uji)

- **Meta-model:** RMSE 0,0067, bias 0,0005, Spearman per dataset 0,66.
- **Status material:** precision 0,93 dan recall 0,47 pada `T` = 0,01. Sebanyak **86% prediksi LODO berstatus `tidak_yakin`**, karena median lebar interval (0,034) lebih besar dari `T`.
- **Per jenis korupsi:**
  - label noise dan duplikat-konflik punya Spearman 0,77–0,94 dan MAE 0,005–0,006;
  - missing, outlier, dan duplikat eksak punya MAE ≤ 0,0012 tetapi Spearman ≈ 0, karena ΔAUC-nya hampir nol.
- **Meta-model ΔAUC relatif:** MAE 0,0070 (dalam satuan relatif), coverage median 0,97.
- **Potensi pemulihan:** 32% potensi LODO negatif: duplikat-konflik 69%, missing 59%, outlier 38%, label noise 8%, duplikat eksak 8%.

### Artefak v1 kandidat

Folder `artifacts/metamodel-1.0.0-rc1`, tidak di-commit.

- Status: `experimental = true`.
- `corpus_snapshot`: `openml-cc18:31:ca50952a4348`.
- Data latih: 8.325 run.
- Hiperparameter: `num_leaves` 7, `learning_rate` 0,03, `min_data_in_leaf` 10.
- Kuantil conformal: 0,0158.
- Ambang OOD: 4,68 (p95 skor OOD LODO dengan standarisasi referensi akhir).
- Tanpa meta-model relatif; urutan temuan menurut potensi.

Scan end-to-end selesai dalam ±15 detik. Churn termasuk data latih artefak, jadi hasil scan itu bukan bukti akurasi.

## Keputusan G3 **[K]**

Opsi yang ditimbang ada di tabel pertama. Rekomendasi agent di tabel kedua **disetujui seluruhnya oleh pemilik repo pada 14/11/2026**.

| # | Butir | Opsi | Dasar keputusan dari E1 |
| --- | --- | --- | --- |
| G3-1 | Validitas noise floor estimasi (hal terbuka #2, H5) | A: H5 lolos, BR-05 tetap. B: H5 gagal, `T` tetap 0,01 dan noise floor estimasi hanya informatif (ADR 0006) | `h5` di laporan E1. Kappa bisa tinggi semu bila `T` didominasi lantai 0,01; karena itu subset P5 ikut menentukan |
| G3-2 | Ambang OOD tinggi (hal terbuka #3) | A: persentil ke-95 skor OOD LODO, seperti pilot. B: persentil di desil tempat MAE atau coverage memburuk tajam. C: persentil ke-90 | Tabel `ood_bins` (MAE dan coverage per desil) dan `h4` |
| G3-3 | Pelebaran interval saat OOD tinggi (hal terbuka #3) | A: tidak dilebarkan, karena BR-33 sudah memaksa `tidak_yakin`. B: kuantil terpisah untuk desil OOD teratas | Coverage desil OOD teratas di `ood_bins` |
| G3-4 | ΔAUC relatif saat scan (K7, ADR 0011) | A: meta-model terpisah untuk ΔAUC relatif (rencana skripsi), dengan interval dari kuantil relatif. B: tetap null | `relative_metamodel` di laporan E1 (MAE, coverage) |
| G3-5 | Urutan temuan (fallback H2b) | A: H2b lolos, urutan potensi. B: H2b gagal, `finding_order = volume` dan klaim urutan tidak ditampilkan | `h2b` |
| G3-6 | Potensi pemulihan negatif | A: dilaporkan apa adanya. B: dipotong di 0 dan ditandai. C: temuan berpotensi ≤ 0 tidak diberi angka | Proporsi potensi negatif di `lodo_recovery`. Dry run pada artefak uji E0 memberi potensi `label_noise` negatif pada churn label noise 30%: normalisasi satu fitur menghasilkan profil di luar manifold korpus |
| G3-7 | Label eksperimental | Dicabut hanya untuk klaim yang hipotesisnya lolos (BR-64). Klaim yang gagal mengikuti `product.md` 5.2 | Hasil H1–H5 dan register klaim |

### Rekomendasi agent (13/11/2026)

| # | Rekomendasi | Alasan |
| --- | --- | --- |
| G3-1 | **A**: BR-05 tetap, dengan catatan bahwa kappa tidak informatif | Selisih jauh di bawah 0,005 di kedua kelompok. Hanya satu dataset yang noise floor-nya di atas 0,01, sehingga dalam praktik `T` ≈ 0,01. Bias negatif di subset dekat 0,01 dicatat |
| G3-2 | **A**: p95, dengan KL-05 tetap tertutup | Tidak ada ambang yang memisahkan estimasi buruk: galat terbesar ada di desil tengah, bukan desil teratas. p95 dipertahankan karena konservatif sesuai BR-33, dan klaim bahwa skor OOD menandai estimasi tidak andal belum didukung |
| G3-3 | **A**: tidak dilebarkan | Desil OOD teratas tidak kekurangan coverage (0,97) |
| G3-4 | **B**: tetap null | Interval ΔAUC absolut saja gagal H3. Menambah angka relatif yang tidak punya hipotesis sendiri menambah klaim tanpa bukti |
| G3-5 | **A**: urutan potensi, berlabel eksploratif | H2b lolos dengan selisih τ yang besar |
| G3-6 | **C**: potensi ≤ 0 tidak diberi angka | 32% potensi negatif. Angka negatif tidak bermakna sebagai "potensi pemulihan", sedangkan memotongnya ke 0 menyembunyikan bahwa itu artefak kontrafaktual. Urutan tetap memakai nilai aslinya |
| G3-7 | Buka KL-01 (estimasi titik) dan KL-03 (H1b). KL-02 interval, KL-04 status, dan KL-09 dampak per jenis tetap tertutup atau eksperimental. KL-06 urutan dibuka dengan label eksploratif | H1a dan H1b lolos; H2 dan H3 gagal |

**Butir baru yang butuh keputusan pemilik repo (AGENTS.md bagian 8):**

- **H3 gagal, dan `product.md` 5.2 hanya mengatur fallback bila H1 gagal.** Status (BR-31–BR-33) memakai interval, sehingga kegagalan coverage per dataset menyentuh status dan keputusan gate `block` setelah G3 (BR-51). Opsi:
  1. interval dan status tetap berlabel eksperimental setelah G3, dan gate tidak `block`;
  2. coverage kondisional, misalnya kuantil per kelompok profil (Mondrian conformal) diuji di Phase 5. Ini analisis eksploratif setelah pembekuan (BR-86) dan butuh revisi rencana analisis bertanggal;
  3. keduanya.

  Rekomendasi agent: **3**.

  **[K] Diputuskan pemilik repo 14/11/2026: opsi 3, dengan conformal ternormalisasi sebagai kandidat utama (bukan Mondrian).**
  - Verdict H3 tetap **tidak lolos**. Interval (KL-02) dan status (KL-04) tetap berlabel eksperimental setelah G3. `material` dipetakan ke **warn**, bukan **block** (BR-51), sampai interval lolos validasi.
  - Penyebab kegagalan menurut diagnostik: satu lebar interval untuk dataset dengan tingkat kesulitan berbeda (Spearman coverage per dataset vs MAE −0,87, vs sd ΔAUC −0,78), ditambah kuantil fold yang tidak stabil karena hanya dari 6 dataset kalibrasi (0,005–0,038 antar-fold). Coverage marginal tepat 0,90.
  - Analisis lanjutan X1 dijalankan di Phase 5 sebagai analisis eksploratif menurut protokol yang ditulis lebih dulu di `analysis-plan.md` bagian 10. Hasilnya tidak mengubah verdict H3. Bila X1 lolos, KL-02 paling cepat dibuka di G4 setelah divalidasi ulang.
- **86% prediksi berstatus `tidak_yakin`** karena interval lebih lebar dari `T`. Ini risiko utama produk (`product.md` 6.2, tingkat tidak yakin), terpisah dari OOD.

## Konsekuensi

- **Artefak final `1.0.0`** dibangun dari run store E1 dengan urutan temuan menurut potensi, tanpa meta-model relatif (G3-4), dan ambang OOD p95 (G3-2).
- **Label eksperimental tetap menyala di tingkat artefak.** `ScanReport` hanya punya satu flag `model.experimental` (BR-35), sedangkan interval (KL-02) dan status (KL-04) tetap eksperimental karena H3 gagal. Pencabutan label per klaim butuh perubahan kontrak `ScanReport` dan diputuskan terpisah.
- **Potensi pemulihan ≤ 0 tampil tanpa angka** (BR-45, G3-6); urutan tetap memakai nilai aslinya.

- Bila H1 gagal, klaim "ΔAUC diperkirakan X ± Y" tidak dibuka; produk memakai "indikasi risiko" tanpa angka (`product.md` 5.2), dan tinjauan H1 di Phase 5 menentukan urutan Sprint C.
- Artefak v1 tidak di-commit (folder `artifacts/` diabaikan git). Artefak dibangun ulang dari run store E1 dengan `python -m ceteris.metamodel build`.

## Alternatif yang ditolak

- **Kalibrasi artefak dari 6 dataset kalibrasi satu pembagian.** Kuantil dari 6 dataset terlalu bergantung pada pembagian acak, sedangkan residu LODO bersarang memakai 31 dataset dan setiap skornya tetap bebas kebocoran.
- **Baseline (c) tanpa tuning.** Perbandingan H1a akan bias ke arah meta-model.
- **Menjalankan E1 dari repositori utama.** Pengembangan paralel akan menandai baris `run_log` sebagai `git_dirty`.
