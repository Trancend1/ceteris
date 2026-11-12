# ADR 0009: Paket keputusan G1 — keacakan learner, estimator label noise, mekanisme korupsi

- **Status:** Diterima **[K]** (keputusan pemilik repo, 12/11/2026). Semua butir mengikuti rekomendasi; butir yang menyangkut rumusan skripsi tetap dikonfirmasi ke pembimbing.
- **Tanggal:** 12/11/2026
- **Rilis terdampak:** R0, Phase 2 (sebelum G1, saat `configs/learner.yaml`, skema profil, dan spesifikasi korupsi dibekukan)
- **Rujukan:** BR-03, BR-04, BR-05, BR-12, BR-82, BR-83, BR-84; F-S02, F-S05, F-S06; `business-rules.md` hal terbuka #10 dan #11; `architecture.md` hal terbuka #2; ADR 0005, 0007, 0008

Tiga keputusan di bawah menutup hal yang harus selesai sebelum Phase 2 membekukan learner, profil, dan korupsi di G1. Implementasinya dikerjakan di Phase 2. Satu nilai tetap **[T]**: `bagging_fraction`, dibekukan bersama `learner.yaml` di G1.

## Ringkasan

| # | Keputusan | Pilihan **[K]** | Yang berubah |
| --- | --- | --- | --- |
| K1 | Sumber keacakan learner acuan dan probe | Opsi A: bagging baris | `configs/learner.yaml` versi baru; glosarium "Probe"; hal terbuka BR #11 ditutup |
| K2 | Estimator label noise (F-S05) | Opsi A: cleanlab ≥ 2.8.0, < 3 | Dependensi baru; hal terbuka BR #10 dan arsitektur #2 ditutup |
| K3a | Grid level korupsi | Grid rencana skripsi sebagai kandidat G1 | `configs/corruption.yaml` |
| K3b | Mekanisme MAR | Pemicu dari korelasi tertinggi; bobot peringkat dan jumlah sel tepat dipertahankan | `ceteris/corrupt.py`, ADR 0008 |
| K3c | Label noise class-conditional | Asimetris 2:1 (biner) dan berbasis confusion matrix (multikelas) | `ceteris/corrupt.py`, ADR 0008 |
| K3d | Outlier | Pagar Tukey dengan k ∼ U[3; 10], satu kolom per baris | `ceteris/corrupt.py`, ADR 0008 |
| K3e | Kolom sasaran missing | Dua varian: kolom ber-importance tinggi dan rendah | `ceteris/corrupt.py`, `configs/corruption.yaml` |

---

## K1. Sumber keacakan learner acuan dan probe

### Konteks

- **[F]** Dokumentasi LightGBM 4.7.0: `seed` hanya menurunkan seed lain. Keacakan baru muncul bila bagging (`bagging_freq` > 0 dan `bagging_fraction` < 1), sub-sampling fitur (`feature_fraction` < 1), atau `extra_trees` aktif. Sampling bin (`data_random_seed`) hanya berpengaruh di atas `bin_construct_sample_cnt` = 200.000 baris, jauh di atas korpus (≤ 50.000 baris).
- **[F]** `configs/learner.yaml` (0.1.0-draft) tidak mengaktifkan satu pun. Pemeriksaan Phase 1: seed 1 dan 987654 memberi prediksi identik.
- Akibatnya noise floor terukur (BR-04) selalu 0, sehingga `T` selalu 0,01 dan H5 tidak bisa diuji. Probe di jalur scan punya masalah yang sama untuk noise floor estimasi.
- **Inkonsistensi dokumen:** BR-03 menyatakan satu versi spesifikasi learner berlaku juga untuk probe saat scan, sedangkan glosarium mendefinisikan probe sebagai "Model LightGBM default". Menurut urutan otoritas, BR-03 menang; glosarium perlu diselaraskan.

### Opsi

| Opsi | Isi | Kelebihan | Kekurangan |
| --- | --- | --- | --- |
| A | Bagging baris: `bagging_fraction` < 1, `bagging_freq` = 1 | Definisi BR-04 ("seed berbeda") dan split tetap tidak berubah; variasi berasal dari sampel baris, sebanding dengan variasi data latih | Learner tidak lagi "default LightGBM"; AUC rata-rata bergeser sedikit |
| B | Sub-sampling fitur: `feature_fraction` < 1 | Sama-sama mempertahankan BR-04 | Variasi bergantung pada jumlah fitur; bisa berinteraksi dengan korupsi yang hanya mengenai beberapa kolom |
| C | A dan B sekaligus | Noise floor paling besar | Dua sumber variasi; paling jauh dari default |
| D | Learner tetap deterministik; noise floor diukur dari resampling data latih (misalnya bootstrap) | Learner tetap default | Mengubah definisi BR-04 lebih dulu (AGENTS.md butir 4); bootstrap pada dasarnya bagging di level data |

### Pengukuran cepat

**[F]** Pemeriksaan cepat pada 12/11/2026, **bukan hasil eksperimen** dan tidak tersimpan di run store. Model dilatih pada partisi latih D₀ dari 31 dataset korpus Phase 1 dengan 5 seed, lalu dinilai pada partisi uji yang sama. Noise floor per dataset = rentang AUC antar seed. Nilai 0,8 hanya nilai uji, bukan usulan nilai final.

| Opsi diuji | Noise floor median | Q1–Q3 | Maks | = 0 | > 0,01 | Pergeseran AUC rata-rata vs default (median; min–maks) |
| --- | --- | --- | --- | --- | --- | --- |
| Default (sekarang) | 0 | 0–0 | 0 | 31/31 | 0/31 | — |
| A: bagging, `bagging_fraction` 0,8 | 0,0011 | 0,0003–0,0036 | 0,0286 | 0/31 | 5/31 | +0,0002; −0,0251 s.d. +0,0197 |
| B: `feature_fraction` 0,8 | 0,0007 | 0,0002–0,0033 | 0,0183 | 0/31 | 3/31 | 0,0000; −0,0068 s.d. +0,0052 |
| C: A dan B | 0,0008 | 0,0002–0,0031 | 0,0205 | 0/31 | 2/31 | +0,0001; −0,0220 s.d. +0,0138 |

Noise floor terbesar pada opsi A: madelon (0,0286), kc1 (0,0204), jm1 (0,0167), churn (0,0133). Pada dataset seperti itu `T` naik di atas 0,01, sehingga subset "noise floor dekat 0,01" untuk H5 (ADR 0006) benar-benar terisi.

Pembacaan: A dan B sama-sama menghilangkan noise floor nol. B menggeser AUC lebih sedikit dari learner default; A memberi variasi yang sedikit lebih besar dan berasal dari sampel baris, sumber variasi yang paling dekat dengan "data latih yang berbeda".

### Keputusan

**[K] Opsi A**, dengan `deterministic: true` tetap aktif agar hasil per seed tetap identik (BR-03). Alasannya: variasi dari sampel baris paling sesuai dengan makna noise floor sebagai "variasi tanpa korupsi". Opsi B adalah alternatif yang sah bila pembimbing lebih mengutamakan kedekatan dengan learner default. Spesifikasi yang sama dipakai probe (BR-03), dan glosarium "Probe" diselaraskan. Nilai `bagging_fraction` dibekukan bersama `learner.yaml` di G1.

---

## K2. Estimator label noise (F-S05)

### Konteks

- **[F]** cleanlab berlisensi Apache-2.0 sejak 2.8.0 (`business-rules.md` bagian 8). Versi terbaru 2.9.0 (13/01/2026) butuh Python ≥ 3.10 dan bergantung pada numpy, scikit-learn, pandas, tqdm, dan termcolor.
- **[F]** API yang relevan: `cleanlab.count.num_label_issues(labels, pred_probs, ...)` menaksir jumlah label bermasalah dari probabilitas out-of-fold; `estimate_noise_matrices(..., cv_n_folds=5, seed=...)` memakai 5 lipatan sebagai bawaan.
- Estimasi label noise juga menjadi masukan ADR 0007 (ambang kebocoran adaptif).

### Opsi

| Opsi | Isi | Kelebihan | Kekurangan |
| --- | --- | --- | --- |
| A | cleanlab ≥ 2.8.0, < 3 | Implementasi confident learning yang dirujuk literatur (Northcutt dkk. 2021); lisensi permisif | Dependensi baru beserta dependensi transitifnya |
| B | Implementasi confident joint sendiri | Kontrol penuh, tanpa dependensi | Risiko bug pada komponen paling berpengaruh di profil; harus divalidasi terhadap cleanlab juga |
| C | Laju ketidaksesuaian sederhana (prediksi out-of-fold ≠ label) | Cepat, tanpa dependensi | Bias pada dataset sulit: kesalahan model terbaca sebagai label noise |

### Keputusan

**[K] Opsi A**, dikunci `>=2.8.0,<3`. Rincian yang ikut dibekukan di G1:

- probabilitas out-of-fold dari 5 lipatan berstrata, memakai spesifikasi learner acuan (BR-03) dengan seed turunan BR-84;
- sampel ≤ 100.000 baris (BR-12);
- fitur profil `label_noise_rate` = jumlah isu label dibagi jumlah baris;
- divalidasi di Phase 2 terhadap label noise yang disuntikkan pada korpus sebelum G1.

---

## K3. Mekanisme korupsi

Lima perbedaan antara rencana skripsi dan implementasi Phase 1 (ADR 0008). Semua opsi tetap memenuhi BR-82 (jumlah baris atau sel terdampak tepat) dan BR-83 (urutan campuran).

| # | Rencana skripsi | Implementasi Phase 1 | Pilihan **[K]** |
| --- | --- | --- | --- |
| K3a Grid level | Missing 5–50%, label 2–30%, outlier 1–20%, duplikat 5–50% (5 level per jenis); ±10 campuran; 5 seed | 0,05; 0,1; 0,2; 0,3 untuk semua jenis; tanpa campuran | Grid rencana skripsi sebagai kandidat G1; disesuaikan di pilot E0 bila ΔAUC di bawah noise floor |
| K3b MAR | Kolom pemicu numerik dengan korelasi tertinggi; peluang naik secara logistik menurut peringkat | Kolom pemicu acak; bobot linear menurut peringkat; jumlah sel tepat | Pemicu dari korelasi absolut tertinggi (rencana skripsi); bobot peringkat dan jumlah sel tepat dipertahankan (implementasi). Bobot logistik hanya dipakai bila pembimbing memintanya |
| K3c Class-conditional | Biner: laju positif → negatif dua kali laju sebaliknya; multikelas: pindah ke kelas yang paling sering tertukar menurut confusion matrix probe pada D₀ | round(level × n_c) per kelas pindah ke kelas berikutnya | Rencana skripsi; kelas positif = kelas minoritas (diputuskan pemilik repo, karena rencana skripsi tidak menyebutnya) |
| K3d Outlier | Nilai di luar [Q1 − k·IQR; Q3 + k·IQR], k ∼ U[3; 10] | `scale` tetap 3,0 di luar min/maks teramati | Pagar Tukey dengan k ∼ U[3; 10] per sel (rencana skripsi); satu kolom numerik per baris terdampak (implementasi) |
| K3e Kolom sasaran missing | Terpisah untuk fitur ber-importance tinggi dan rendah | 3 kolom acak | Dua varian, 3 kolom importance tertinggi dan 3 terendah menurut learner acuan pada D₀ |

### Dampak

- **Komputasi (hitungan kasar, bukan hasil):** dengan rekomendasi K3a dan K3e, ada sekitar 45 konfigurasi tunggal dan ±10 campuran, × 5 seed, sehingga ±275 run per dataset dan ±8.500 run untuk 31 dataset. Angka final dihitung di pilot E0.
- **Kebocoran informasi bersih ke korupsi tidak terjadi:** K3c dan K3e memakai D₀ hanya di jalur riset untuk memilih kelas atau kolom sasaran. Profil tetap dihitung dari data kotor saja (BR-20).
- **Ancaman validitas yang tetap dicatat:** outlier sintetis dibuat dengan aturan IQR, sedangkan profil juga memuat fitur IQR. Fitur Isolation Forest dan pelaporan per jenis korupsi menjadi mitigasinya.

---

## Yang tidak diputuskan di sini

- Statistik noise floor dan jumlah seed probe (`business-rules.md` hal terbuka #1, G2).
- Hiperparameter probe kebocoran dan pilihan ambang tetap atau adaptif (hal terbuka #6, ADR 0007).

## Tindak lanjut

1. Sudah dilakukan (12/11/2026): BR-03 dan bagian 8 `business-rules.md` diperbarui; hal terbuka BR #10, BR #11, arsitektur #2, dan product 7.2 #2 ditutup; glosarium "Probe" diselaraskan dengan BR-03; ADR 0007 dan 0008 diberi catatan.
2. Phase 2, sebelum G1: `learner.yaml` dan `corruption.yaml` naik versi; `ceteris/corrupt.py` mengikuti K3b–K3e; cleanlab ditambahkan ke dependensi; uji BR-82, BR-83, dan determinisme diperbarui, termasuk uji bahwa seed berbeda memberi hasil berbeda.
