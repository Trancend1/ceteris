# Rencana analisis R0

- **Status:** **Dibekukan 12/11/2026** (gate G2 disetujui pemilik repo, BR-86). Setiap analisis yang tidak tertulis di sini berlabel **eksploratif**, dan perubahan dicatat sebagai revisi bertanggal di bagian 9.
- **Tanggal:** 12/11/2026
- **Rujukan:**
  - `product.md` 6.1 (kriteria bukti H1–H5);
  - `business-rules.md` BR-04, BR-05, BR-22, BR-81, BR-85, BR-86;
  - [ADR 0006](decisions/0006-kerangka-pengujian-rq2b-dan-h5.md), [ADR 0011](decisions/0011-phase-3-dan-gate-g2.md);
  - `execution-plan.md` Phase 3–5.

Dokumen ini menetapkan ukuran, uji, dan kriteria **sebelum** korpus penuh dijalankan, agar analisis tidak bisa disesuaikan dengan hasil. Angka di laporan dan naskah dibaca dari run store (`corruption_run`, `noise_floor`, `lodo_result`, `ablation_run`), bukan diketik manual.

## 1. Ketentuan umum

| Butir | Ketentuan |
| --- | --- |
| Unit analisis | Dataset, bukan run (BR-85). Metrik dihitung per dataset lalu diringkas dengan median dan IQR |
| Jumlah dataset | Korpus penuh: 31 dataset lolos saringan Phase 1. Tidak ada saringan noise floor tambahan (bagian 7 P4) |
| Taraf uji | α = 0,05 |
| Koreksi ganda | Holm, di dalam satu keluarga hipotesis |
| Bootstrap | 10.000 resample atas dataset, seed tetap `derive_seed("analysis", "bootstrap")`, CI persentil 95% |
| Hasil tidak signifikan | Dilaporkan dengan CI, tidak ditulis sebagai "tidak ada perbedaan" |
| Hasil negatif | Dilaporkan apa adanya; fallback mengikuti `product.md` 5.2 dan ADR 0006 |
| Label | Semua angka mode learned berlabel eksperimental sampai G3 (BR-35) |

## 2. Protokol evaluasi: LODO bersarang (F-S11, BR-81)

1. **Fold luar:** satu dataset beserta semua run-nya menjadi data uji; N − 1 dataset sisanya menjadi data latih.
2. **Pembagian dalam:** dataset latih dibagi **per dataset** menjadi proper-train (≈ 80% dataset) dan kalibrasi (≈ 20% dataset), dengan seed tetap per fold.
3. **Tuning:** hiperparameter meta-model dipilih dengan grouped CV per dataset, hanya di proper-train. Grid tuning ada di bagian 7 (P6).
4. **Kalibrasi:** meta-model final dilatih di proper-train. Residu absolut pada dataset kalibrasi menghasilkan kuantil 90% berbobot sama per dataset (`business-rules.md` bagian 3).
5. **Prediksi:** ΔAUC dan interval untuk semua run dataset uji, ditulis ke `lodo_result`.

Dataset uji tidak dipakai untuk melatih, men-tuning, atau mengkalibrasi apa pun. Uji pembagian fold memastikan irisan dataset kosong.

## 3. Metode yang dibandingkan

| Metode | Definisi |
| --- | --- |
| Meta-model | LightGBM regresi, 25 fitur profil v1 → ΔAUC |
| Sanity check | Regresi linear pada fitur yang sama (dilaporkan, tidak diuji) |
| Baseline (a) | Rata-rata ΔAUC data latih fold |
| Baseline (b) | Tiap indikator kekotoran (fitur dengan nilai tanpa temuan) dinormalkan 0–1 menurut peringkat di data latih fold. Skor = 100 × (1 − rata-rata indikator), bobot sama tanpa tuning, lalu regresi linear ΔAUC pada skor |
| Baseline (c) | LightGBM dengan fitur konteks dan probe saja, tanpa indikator kekotoran |
| Baseline (d) | Dose–response: suntikan +5%, +10%, dan +20% baris terdampak dari jenis yang terdeteksi, AUC pada hold-out data kotor, garis diekstrapolasi ke nol (kuadratik sebagai pembanding). Dijalankan pada subset tetap 1 seed × semua konfigurasi × semua dataset. Operasionalisasi rinci di ADR 0011 G2-7 (bagian 7, P7) |

## 4. Hipotesis, ukuran, dan uji

| Hipotesis | Ukuran per dataset | Uji | Kriteria |
| --- | --- | --- | --- |
| **H1a** akurasi | MAE estimasi ΔAUC | Wilcoxon signed-rank satu sisi (MAE meta-model < MAE baseline), terpisah untuk baseline (a), (b), (c); Holm atas **3** perbandingan | p Holm < 0,05 untuk ketiganya, dan median selisih MAE negatif dengan CI 95% bootstrap |
| **H1b** non-inferiority | Selisih MAE (meta-model − d); detik CPU per estimasi | Batas atas CI 95% bootstrap dari median selisih MAE | Batas atas < 0,005 dan biaya komputasi meta-model ≥ 10× lebih murah |
| **H2** dampak per jenis | ΔAUC per jenis tunggal pada `affected_row_frac` yang sama (BR-82): interpolasi linear kurva dosis–respons per dataset pada `affected_row_frac` = 0,10 | Friedman antar-jenis (blok = dataset); post-hoc Wilcoxon berpasangan dengan Holm | Label noise median dampak tertinggi, MCAR terendah, dan post-hoc keduanya signifikan |
| **H2b** urutan temuan (eksploratif, ADR 0006) | Kendall τ antara urutan temuan dan keuntungan AUC nyata dari memulihkan satu jenis korupsi pada konfigurasi campuran (`ablation_run`) | Wilcoxon berpasangan antar-dataset: τ urutan potensi pemulihan vs τ urutan volume | τ potensi > τ volume, signifikan. Bila gagal, urutan jatuh ke volume dan klaim urutan tidak ditampilkan |
| **H3** coverage | Coverage empiris interval 90% dan lebar rata-rata | Proporsi dataset dengan coverage 85–95%, CI binomial Clopper–Pearson | ≥ 80% dataset dalam rentang |
| **H4** OOD | Spearman skor OOD vs galat absolut atas semua prediksi LODO | CI 95% bootstrap (resample dataset) | Batas bawah CI > 0 |
| **H5** noise floor estimasi | Selisih dan bias (estimasi − terukur) noise floor per dataset; kappa kesepakatan status bila `T` dihitung dari noise floor estimasi vs terukur | Median selisih absolut dengan CI 95% bootstrap; kappa Cohen | Median selisih ≤ 0,005 **dan** kappa ≥ 0,6, untuk seluruh dataset dan untuk subset noise floor dekat 0,01 (kuartil teratas, bagian 7 P5). Bias selalu dilaporkan. Bila gagal: `T` tetap 0,01 dan noise floor estimasi hanya informatif (ADR 0006) |
| **RQ4** data kotor asli (eksploratif) | Galat absolut, coverage, kesepakatan status pada 3–5 pasangan kotor-bersih | Deskriptif dengan CI bootstrap | Galat ≤ 2× MAE LODO. Pasangan dengan versi bersih ground truth menjadi bukti utama |
| **BR-16** konsistensi jalur | Selisih profil dan prediksi jalur riset vs jalur scan | Deskriptif | Profil identik dan selisih prediksi < 1e-9 |

Ukuran pendukung H1a, dilaporkan tanpa uji: RMSE, bias, Spearman prediksi vs aktual per dataset, MAE pada run dengan kerugian material, serta precision dan recall status material. Semua hasil RQ1 juga dilaporkan per jenis korupsi.

## 5. Noise floor (BR-04, BR-05)

- **Noise floor terukur:** per dataset, AUC model versi bersih untuk k seed pada split tetap.
- **Noise floor estimasi:** per run, AUC out-of-fold probe pada data kotor untuk k seed probe tetap (`noise_floor_seeds`), sama di jalur riset dan scan.
- **Statistik dan k:** rata-rata |selisih AUC| antar-pasangan seed. Noise floor terukur memakai k = 10, noise floor estimasi k = 5 (bagian 7 P1, `dqprofile.noise_floor_value`).
- **Ambang:** `T = max(0,01; noise floor)`.

## 6. Data dan konfigurasi korupsi

- Grid tunggal: `configs/corruption.yaml` (45 konfigurasi), 5 seed per konfigurasi.
- Campuran: kesepuluh kandidat pilot, dipindah ke `configs/corruption.yaml` saat rencana ini dibekukan (bagian 7 P2).
- Snapshot korpus dibekukan dan diberi tag `corpus_snapshot` sebelum LODO final.

## 7. Nilai yang ditetapkan di G2 dari pilot E0

| # | Butir | Nilai | Dasar |
| --- | --- | --- | --- |
| P1 | Statistik noise floor dan jumlah seed | **[K]** Rata-rata \|selisih AUC\| antar-pasangan seed; 10 seed terukur, 5 seed estimasi | ADR 0011 G2-1 |
| P2 | Konfigurasi campuran final | **[K]** Kesepuluh kandidat `configs/e0.yaml` | ADR 0011 G2-3 |
| P3 | Penyesuaian level grid bila ΔAUC di bawah noise floor | **[K]** Grid tetap. Kriteria pilot ≥ 30% tidak terpenuhi untuk missing, outlier, dan duplikat eksak, dan dilaporkan sebagai temuan H2. Dibawa ke pembimbing | ADR 0011 G2-2 |
| P4 | Aturan dataset dengan noise floor > 0,01 | **[K]** Dipertahankan; `T = max(0,01; nf)` menyesuaikan | ADR 0011 G2-4 |
| P5 | Batas subset "noise floor dekat 0,01" untuk kappa H5 | **[K]** Kuartil teratas noise floor terukur di korpus, minimal 8 dataset | ADR 0011 G2-5 |
| P6 | Grid tuning meta-model di LODO bersarang | **[K]** `num_leaves` {7, 15, 31} × `learning_rate` {0,03; 0,1} × `min_data_in_leaf` {10, 40}, 300 ronde, grouped CV 3 lipatan per dataset di proper-train | ADR 0011 G2-9 |
| P7 | Operasionalisasi baseline (d) | **[K]** Seperti ADR 0011 G2-7, diimplementasikan di `ceteris.metamodel.baseline_d` | ADR 0011 G2-7 |
| P8 | Mesin komputasi korpus penuh | **[K]** Mesin lokal 4 inti dengan runner yang bisa dilanjutkan. Pindah ke VM awan bila waktu nyata lebih dari 2× proyeksi (≈ 68 jam CPU) | ADR 0011 G2-6 |
| P9 | Jumlah perbandingan Holm H1a | **[K]** 3 (baseline a–c) | ADR 0011 G2-8 |

## 8. Yang tidak termasuk rencana ini

- Learner kedua sebagai robustness check: diputuskan setelah G2 (agenda bimbingan). Bila dijalankan, hasilnya eksploratif.
- Simulator what-if (BR-44): di luar klaim yang dibuktikan.

## 9. Riwayat revisi

| Tanggal | Perubahan |
| --- | --- |
| 12/11/2026 | Draf pertama untuk gate G2 |
| 12/11/2026 | Nilai P1–P9 diisi dari keputusan G2 (ADR 0011); rencana dibekukan saat G2 disetujui |
| 14/11/2026 | Bagian 10 ditambahkan: protokol analisis eksploratif X1 (conformal ternormalisasi) setelah H3 gagal di E1 ([ADR 0012](decisions/0012-phase-4-dan-gate-g3.md)). Ditulis sebelum X1 dijalankan; bagian 1–8 dan verdict H1–H5 tidak berubah |

## 10. Analisis eksploratif setelah pembekuan

Analisis di bagian ini ditulis setelah hasil E1 diketahui, sehingga berlabel **eksploratif** (BR-86) dan tidak dapat mengubah verdict hipotesis di bagian 4.

### X1 — Conformal ternormalisasi untuk coverage per dataset

**Latar:**
- H3 gagal: 7 dari 31 dataset dalam rentang 85–95%, sedangkan coverage marginal 0,90.
- Diagnostik E1 menunjukkan coverage per dataset turun seiring kesulitan dataset (Spearman vs MAE −0,87) karena lebar interval sama untuk semua run.
- X1 menguji apakah lebar yang menyesuaikan kesulitan memperbaiki coverage per dataset.

**Metode (ditetapkan sebelum dijalankan) [K]:**

1. **Protokol luar sama dengan bagian 2.** Fold LODO, pembagian proper-train dan kalibrasi, hiperparameter meta-model per fold (`fold_params_json` di `lodo_result`), dan prediksi titik dipakai ulang dari E1. Prediksi titik tidak dilatih ulang.
2. **Model kesulitan σ̂(x).**
   - Residu out-of-fold meta-model di proper-train dihitung dengan grouped CV 3 lipatan per dataset (pembagian seperti P6).
   - LightGBM regresi dilatih pada fitur profil yang sama → |residu| OOF, dengan hiperparameter meta-model fold itu, tanpa tuning tambahan.
   - σ̂(x) = max(prediksi, ε), dengan ε = 0,001.
3. **Kalibrasi.**
   - Skor nonconformity di dataset kalibrasi: s = |ΔAUC − ŷ| / σ̂(x).
   - Kuantil 90% berbobot sama per dataset (BR-22) memberi q̃.
   - Interval: ŷ ± q̃ · σ̂(x).
4. **Status.** Status dari interval baru memakai aturan BR-30–BR-34 dan `T` per dataset yang sama dengan E1.
5. **Satu kali jalan.** ε, model σ̂, dan pembagian fold tidak diubah setelah hasil terlihat. Varian lain (misalnya Mondrian per tipe tugas, atau kalibrasi dari residu LODO semua dataset) butuh revisi bertanggal baru sebelum dijalankan.

**Ukuran dan kriteria:**

| # | Ukuran | Kriteria / pelaporan |
| --- | --- | --- |
| X1-1 | Proporsi dataset dengan coverage 85–95%, CI Clopper–Pearson | **Lolos eksploratif** bila ≥ 80% dataset (kriteria H3) |
| X1-2 | Coverage marginal, rata-rata berbobot sama per dataset | Dilaporkan; diharapkan ≈ 0,90 |
| X1-3 | Selisih per dataset \|coverage − 0,90\| (X1 − E1), median dengan CI 95% bootstrap (bagian 1) | Dilaporkan |
| X1-4 | Lebar interval median per dataset dan proporsi status `tidak_yakin` | Dibandingkan dengan E1 (86% `tidak_yakin`) |
| X1-5 | Spearman coverage per dataset vs MAE per dataset | Dilaporkan sebagai diagnostik ketergantungan pada kesulitan |

**Tafsiran:**
- Verdict H3 tetap **tidak lolos**, apa pun hasil X1.
- Bila X1-1 lolos, metode ini menjadi kandidat kalibrasi artefak berikutnya. KL-02 dan KL-04 tetap tertutup sampai validasi ulang di G4 (RQ4) dan keputusan pemilik repo.
- Bila X1-1 gagal, hasilnya dilaporkan apa adanya dan interval tetap eksperimental.
- **Data:** run store E1 saja; tidak ada run korupsi baru. Keacakan, bila ada, memakai `derive_seed("x1", dataset_id)` (BR-84).
- **Jadwal:** Phase 5, sebelum tinjauan hasil.
