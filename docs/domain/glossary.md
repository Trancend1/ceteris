# Glosarium Ceteris

Satu-satunya sumber definisi istilah. Dokumen lain memakai istilah ini apa adanya dan tidak mendefinisikannya ulang. Rumus dan ambang yang mengikat ada di [business-rules.md](../business-rules.md); glosarium hanya menunjuk aturannya.

Istilah teknis berbahasa Inggris dipertahankan bila itu bentuk yang dipakai di kode dan literatur.

## 1. Konsep inti

| Istilah | Definisi | Aturan |
| --- | --- | --- |
| **Data quality intelligence** | Kategori produk Ceteris. "Intelligence" berarti tahu temuan mana yang penting, bukan menemukan lebih banyak hal yang kotor. | — |
| **Estimasi dampak** | Taksiran kerugian yang disebabkan kekotoran data pada hasil yang dipakai orang (model, metrik, biaya), selalu disertai ukuran keyakinan. Inti produk. | — |
| **Ceteris paribus** | "Hal lain dianggap sama". Estimasi dampak membandingkan data kotor dengan versi bersihnya, dengan learner, split, dan evaluasi yang sama. | BR-01 |
| **Source-faithful advisory** | Prinsip: menandai, mengukur, mengarantina; tidak mengimputasi atau memperbaiki data secara diam-diam. | BR-70 |
| **Mode learned** | ΔAUC ditaksir meta-model dari quality profile. Satu-satunya mode yang dibuktikan skripsi. | BR-21 |
| **Mode exact** | Selisih metrik bisnis (YoY, MoM, agregat) dihitung ulang dengan dan tanpa temuan. Tanpa meta-model. | — |
| **Mode cost** | Dampak dalam rupiah, dari cost model yang diberikan pengguna. | — |
| **Lapisan** (Scan, Impact Engine, Control, Trust, Translate) | Pengelompokan fitur menurut hubungannya dengan estimasi dampak: masukan, inti, dan tiga konsumen. | — |

## 2. Data dan ukuran

| Istilah | Definisi | Aturan |
| --- | --- | --- |
| **D₀ (dataset dasar)** | Dataset setelah protokol penyaringan dan pembersihan awal yang tetap. "Relatif bersih", bukan bersih mutlak. | — |
| **Dₖ (dataset kotor)** | D₀ dengan korupsi terkontrol pada partisi latih saja. | BR-80 |
| **Versi bersih** | Dalam riset: D₀. Dalam scan: pembanding hipotetis yang tidak dimiliki pengguna; karena itu ΔAUC diestimasi, bukan diukur. | BR-06 |
| **AUC** | Area under the ROC curve; multikelas memakai macro one-vs-rest. | BR-01 |
| **ΔAUC** | AUC model yang dilatih pada versi bersih dikurangi AUC model yang dilatih pada versi kotor, pada test set bersih yang sama. Positif berarti rugi. | BR-01 |
| **ΔAUC relatif** | ΔAUC dibagi headroom (AUC bersih − 0,5): proporsi kemampuan di atas tebakan acak yang hilang. | BR-02 |
| **Kalimat kondisi** | Kalimat wajib yang menyertai setiap ΔAUC: "dibanding model yang dilatih pada versi bersih dan dievaluasi pada data bersih". | BR-06 |
| **Learner acuan** | LightGBM dengan konfigurasi tetap; model yang dampaknya ditaksir. ΔAUC tidak berlaku untuk learner lain. | BR-03 |
| **Probe** | Model LightGBM default yang dilatih cepat pada data apa adanya saat profil dihitung; memberi proxy kesulitan, feature importance, dan noise floor estimasi. Bukan learner acuan. | BR-12 |
| **Noise floor** | Variasi AUC yang muncul hanya karena seed berbeda. **Terukur**: dari dua model versi bersih (riset). **Estimasi**: dari probe pada data kotor (scan). | BR-04 |
| **Ambang kerugian material (T)** | Batas di atasnya ΔAUC dianggap berarti. | BR-05 |
| **Level nominal** | Tingkat korupsi yang diminta (misalnya "10%"); artinya berbeda antar-jenis korupsi. | BR-82 |
| **`affected_row_frac`** | Proporsi baris latih kotor yang benar-benar berubah akibat korupsi, termasuk baris tambahan dari korupsi duplikat; satuan pembanding antar-jenis korupsi. | BR-82 |

## 3. Profil dan estimasi

| Istilah | Definisi | Aturan |
| --- | --- | --- |
| **Quality profile** | Vektor fitur yang merangkum kondisi kualitas sebuah dataset, dihitung hanya dari data kotor. Skema saat ini: `dqprofile` v1. | BR-20 |
| **Fitur terobservasi / diestimasi** | Terobservasi: dihitung langsung (missing rate, duplikat). Diestimasi: hasil model lain yang bisa keliru (label noise, outlier). | — |
| **Meta-fitur** | Fitur konteks dataset (jumlah baris, kolom, class imbalance) tanpa informasi kualitas; dasar baseline (c). | — |
| **Meta-model** | Model regresi yang memetakan quality profile ke ΔAUC. Dilatih pada korpus riset, dimuat sebagai artefak saat scan. | BR-21 |
| **Artefak** | Keluaran riset yang berversi dan dipakai produk: meta-model, kalibrator, referensi OOD, laporan akurasi, spesifikasi learner, kode profil. | BR-23 |
| **Interval 90%** | Rentang prediksi ΔAUC dari conformal prediction berbasis grup dataset. | BR-22 |
| **Coverage** | Proporsi kasus di mana ΔAUC aktual jatuh di dalam interval. Interval 90% yang baik bercakupan sekitar 90%. | — |
| **Skor OOD** | Jarak kNN profil ke profil korpus pelatihan. Tinggi berarti dataset tidak mirip apa pun yang pernah dilihat meta-model. | BR-24 |
| **Confident learning** | Metode estimasi label noise dari prediksi out-of-fold; diimplementasikan pustaka cleanlab. | — |

## 4. Temuan dan keputusan

| Istilah | Definisi | Aturan |
| --- | --- | --- |
| **Scan** | Satu kali penilaian sebuah dataset: kontrak input → profil → estimasi → status → laporan. | — |
| **Kontrak input** | Syarat bentuk data agar bisa dipindai, beserta praproses yang diterapkan. | BR-10–BR-17 |
| **Temuan (finding)** | Satu masalah kualitas pada dataset atau kolom, dengan `issue_type`, `rows_affected_pct`, dan sumbernya (`internal`, `soda`, `gx`). | — |
| **Status** | Kesimpulan satu scan: `material`, `tidak_material`, atau `tidak_yakin`. | BR-30–BR-34 |
| **Eksperimental** | Label pada semua angka mode learned sebelum gerbang G3. | BR-35 |
| **Potensi pemulihan ideal** | Selisih estimasi saat ini dengan estimasi setelah fitur satu temuan dinormalkan. Kontrafaktual model, bukan efek kausal cleaning. | BR-40–BR-42 |
| **Gate** | Titik keputusan otomatis di pipeline. **Gate CI**: sebelum training/deploy. **Promotion gate**: sebelum tabel naik dari bronze ke silver. | BR-50–BR-54 |
| **allow / warn / block** | Keputusan gate: lanjut, lanjut dengan peringatan, berhenti. | BR-51 |
| **Quarantine** | Menahan tabel atau baris bermasalah tanpa mengubah isinya. | BR-53 |
| **Simulator what-if** | Estimasi atas profil yang diubah secara hipotetis; berlabel "simulasi". | BR-44 |
| **`ScanReport`** | Kontrak JSON berversi untuk hasil scan; sama di CLI dan API. | BR-60 |
| **Trust signal** | Status dan estimasi dampak terkini per tabel, untuk konsumen data. | — |
| **Health score** | Roll-up estimasi dampak per tabel; bukan jumlah rule gagal. | — |
| **Register klaim** | Daftar klaim produk beserta bukti yang dibutuhkan dan gerbang setelah klaim itu boleh tampil. | BR-64 |

## 5. Riset

| Istilah | Definisi | Aturan |
| --- | --- | --- |
| **Korpus** | Kumpulan dataset tabular klasifikasi dari OpenML-CC18 yang lolos saringan (2.000–50.000 baris, missing asli ≤ 5% per sel, ditambah kontrak input scan BR-10 dan BR-11; [ADR 0008](../decisions/0008-protokol-korpus-dan-semantik-korupsi.md)); sasaran 30–50 dataset. | BR-10, BR-11 |
| **Korupsi** | Kekotoran yang disuntikkan secara terkontrol: missing (MCAR, MAR), label noise (uniform, class-conditional), outlier, duplikat (eksak, konflik label), dan campuran. | BR-80, BR-83 |
| **MCAR / MAR** | Missing completely at random: hilang tanpa pola. Missing at random: peluang hilang bergantung pada nilai kolom lain. | — |
| **Run** | Satu kombinasi (dataset, konfigurasi korupsi, seed) yang menghasilkan satu pasangan profil dan ΔAUC. | BR-84 |
| **LODO bersarang** | Leave-one-dataset-out: setiap dataset bergiliran menjadi data uji dan tidak dipakai untuk melatih, men-tuning, atau mengkalibrasi. | BR-81 |
| **Baseline (a)–(d)** | Pembanding meta-model: (a) rata-rata ΔAUC, (b) skor kualitas gabungan terkalibrasi, (c) meta-fitur saja, (d) dose–response (melatih ulang pada data yang dikorupsi bertingkat). | — |
| **RQ1–RQ4, RQ2b** | Pertanyaan penelitian: akurasi estimasi; dampak per jenis korupsi; urutan temuan; ketidakpastian dan OOD; data kotor asli. | — |
| **E0–E4** | Eksperimen: E0 pilot, E1 akurasi, E2 dampak per jenis, E3 ketidakpastian, E4 data kotor asli dan konsistensi jalur. | — |
| **Uji konsistensi jalur** | Pemeriksaan bahwa jalur riset dan jalur scan memberi profil dan prediksi yang sama untuk data yang sama. | BR-16 |
| **Rencana analisis** | Dokumen bertanggal berisi uji statistik dan kriteria; dibekukan di G2. | BR-86 |

## 6. Proses

| Istilah | Definisi |
| --- | --- |
| **Gerbang G1–G7** | Titik sinkronisasi riset dan produk. G1: skema profil dan learner dibekukan. G2: pilot lolos. G3: artefak v1 dirilis, klaim angka dibuka. G4: validasi eksternal. G5: platform R1 siap. G6: desain UI disetujui. G7: Web UI R1 selesai. |
| **Rilis R0–R5** | Tahap produk. R0 = bukti mode learned (Short-MVP); R1 scan untuk tim; R2 gate; R3 kontrol; R4 trust dan exact; R5 translate. |
| **Short-MVP / Long-MVP** | Nama draft untuk R0 dan untuk R1–R5. |
| **Design partner** | Organisasi yang memberi data nyata dan umpan balik untuk memvalidasi fitur di luar bukti skripsi. |

## 7. Istilah yang dihindari

| Jangan dipakai | Pakai | Alasan |
| --- | --- | --- |
| "Naik X jika diperbaiki" | "Potensi pemulihan ideal hingga X" | Bukan efek kausal cleaning (BR-41) |
| "Skor kualitas" (0–100) | Estimasi dampak + status | Skor tunggal tidak menjawab dampak |
| "Data bersih" tanpa keterangan | "Versi bersih" atau D₀ | "Bersih" selalu relatif terhadap protokol |
| "Akurat", "terbukti" sebelum G3 | "Eksperimental" | Klaim mengikuti bukti (BR-64) |
| `dqimpact` | `ceteris` | Nama kerja lama paket dan CLI |
