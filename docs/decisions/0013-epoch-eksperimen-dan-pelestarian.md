# ADR 0013: Epoch eksperimen, pelestarian epoch 0, dan dataset holdout

- **Status:** Diterima **[K]** oleh pemilik repo 14/11/2026. Tiga butir tetap **[T]** (bagian "Hal terbuka").
- **Tanggal:** 14/11/2026
- **Rilis terdampak:** R0, Phase 5; putaran eksperimen setelah R0
- **Rujukan:** BR-64, BR-81, BR-84, BR-85, BR-86; ADR 0011, [ADR 0012](0012-phase-4-dan-gate-g3.md); [analysis-plan.md](../analysis-plan.md); [execution-plan.md](../execution-plan.md) Phase 5; [claims-register.md](../claims-register.md)

## Konteks

- E1 menjawab semua hipotesis rencana analisis yang dibekukan. H1a, H1b, H2b, H4 (lemah), dan H5 lolos; H2 dan H3 gagal ([ADR 0012](0012-phase-4-dan-gate-g3.md)) **[F]**.
- Hasil E1 menunjukkan bagian yang perlu diperbaiki: kalibrasi interval (H3), potensi pemulihan negatif (32%), skor OOD yang tidak monoton (H4), level korupsi yang dampaknya ≈ 0, outlier yang tidak berlaku pada dataset kategorikal, dan kappa H5 yang tidak informatif **[F]**.
- Hasil eksperimen dipakai sebagai artefak historis untuk skripsi. Karena itu setiap putaran eksperimen harus utuh dan terlestarikan: data, informasi, dan insight-nya tidak boleh hilang atau tertimpa oleh putaran berikutnya.
- Perbaikan apa pun yang dirancang setelah melihat hasil pada 31 dataset korpus akan terlihat baik pada dataset yang sama. Bukti konfirmatori butuh dataset yang belum pernah dilihat (BR-86).

## Keputusan **[K]**

### 1. Epoch

**Epoch** adalah satu putaran eksperimen utuh dengan:

- satu versi rencana analisis yang dibekukan sebelum dijalankan;
- satu versi protokol eksperimen dan satu set `corpus_snapshot`;
- hasil semua hipotesisnya dilaporkan apa adanya, termasuk yang gagal.

Epoch tidak menggantikan sprint, phase, atau gerbang; ia mengelompokkan pekerjaan eksperimen di dalamnya. Refinement metode atau data tidak boleh masuk ke epoch yang sedang berjalan. Refinement selalu menjadi bagian epoch berikutnya.

### 2. Batas epoch 0

| Butir | Sumber | Status per 14/11/2026 |
| --- | --- | --- |
| Pilot E0 dan keputusan G2 | ADR 0011 | Selesai |
| E1 korpus penuh, LODO bersarang, H1–H5 (termasuk analisis E2 dan E3 atas run store E1) | ADR 0012 | Selesai |
| Diagnostik deskriptif yang hanya membaca run store (penyebab H3, akurasi per jenis, bin OOD, penolakan struktural) | ADR 0012 | Selesai |
| E4 / RQ4 pada pasangan data kotor-bersih nyata | `analysis-plan.md` bagian 4 | Phase 5 |
| Uji konsistensi jalur akhir (BR-16) | `analysis-plan.md` bagian 4 | Phase 5 |

Yang **tidak** termasuk epoch 0: X1 (`analysis-plan.md` bagian 10) dan setiap perubahan pada meta-model, kalibrasi, skor OOD, grid korupsi, korpus, atau learner.

### 3. X1 dipindah ke epoch 1

- Keputusan G3 di ADR 0012 menjadwalkan X1 di Phase 5. Keputusan ini **mengubahnya**: X1 mengubah cara kalibrasi, sehingga termasuk refinement dan masuk epoch 1.
- Protokol X1 di `analysis-plan.md` bagian 10 tetap berlaku karena ditulis sebelum dijalankan. Selain run store E1, X1 juga dievaluasi pada dataset holdout (butir 5).
- Akibatnya KL-02 (interval) dan KL-04 (status) tetap eksperimental setidaknya sampai epoch 1 selesai dan validasi holdout lolos. Verdict H3 epoch 0 tetap **tidak lolos**.

### 4. Pelestarian epoch

Setiap epoch dilestarikan dengan empat bagian. Untuk epoch 0, tempatnya `docs/epochs/epoch-0/` (dibuat saat penutupan).

1. **Arsip tidak berubah** (di luar git, karena `runs/` dan `artifacts/` diabaikan git):
   - run store semua eksperimen epoch (E0 ±49 MB, E1 ±283 MB per 14/11/2026), termasuk `report.json`, `lodo_recovery.parquet`, dan `lodo_timing.parquet`;
   - log runner (`*_progress.log`, `*_lodo.log`);
   - artefak yang dibangun dari epoch itu (`metamodel-0.1.0-pilot`, `metamodel-1.0.0-rc1`, dan `metamodel-1.0.0`);
   - salinan config (`configs/`) dan rencana analisis pada commit penutupan.
2. **Manifest** (`MANIFEST.md`, di repo): SHA-256 tiap berkas arsip, commit kode tiap eksperimen (dari `run_log`), versi protokol, `corpus_snapshot`, versi rencana analisis, lokasi arsip, dan hash daftar dataset holdout (butir 5).
3. **Log insight** (`insights.md`, di repo): satu baris per insight berisi ID, pernyataan, penanda [F]/[K]/[T], sumber (kunci `report.json`, query run store, atau ADR), dan tanggal. Isinya mencakup hasil negatif, kegagalan dan penolakan run, proyeksi biaya yang meleset, keputusan gerbang, dan pertanyaan yang dibawa ke epoch berikutnya. Angka di sini dibaca dari arsip, tidak diketik ulang tanpa sumber.
4. **Laporan penutupan** (`closure.md`, di repo): daftar periksa kriteria tutup (butir 6) beserta buktinya.

### 5. Dataset holdout

- **Dipilih dan disegel sekarang**, sebelum refinement epoch 1 dirancang.
- **Aturan seleksi:** saringan korpus Phase 1 yang sama ([ADR 0008](0008-protokol-korpus-dan-semantik-korupsi.md)), dari dataset OpenML di luar 31 dataset korpus epoch 0. Bila kandidat lebih banyak dari kebutuhan, dataset diambil dengan undian berseed `derive_seed("holdout", "epoch-1")` (BR-84).
- **Yang boleh dilihat saat penyegelan:** hanya atribut saringan (jumlah baris, kolom, kelas, dan proporsi missing). Tidak ada run korupsi, profil, atau eksplorasi lain.
- **Segel:** daftar ID dataset, versi OpenML, dan hash-nya dicatat di manifest epoch 0 dan di-commit sebelum rencana analisis epoch 1 ditulis.
- **Pemakaian:** holdout hanya dipakai untuk evaluasi konfirmatori epoch 1. Ia tidak dipakai untuk melatih, men-tuning, mengkalibrasi, atau memilih metode (BR-81). Setelah dipakai, holdout menjadi bagian korpus terlihat dan epoch berikutnya butuh holdout baru.

### 6. Kriteria tutup epoch

Sebuah epoch ditutup bila semua butir berikut terpenuhi:

- Semua butir batas epoch (butir 2) dilaporkan apa adanya, termasuk hasil negatif.
- Arsip lengkap dan hash setiap berkas cocok dengan manifest.
- `report.json` yang dibangkitkan ulang dari arsip dengan commit tercatat identik dengan aslinya (AC-12).
- Log insight dan laporan penutupan di-commit.
- Untuk epoch 0: dataset holdout sudah disegel.

Penutupan epoch 0 menjadi bagian kriteria selesai Phase 5. Setelah ditutup, arsip epoch hanya boleh dibaca. Epoch berikutnya boleh membaca arsip itu, tetapi tidak menulis ke sana dan tidak mengubah verdict-nya.

### 7. Agenda epoch 1 (sementara, belum dibekukan)

Urutan rekomendasi yang disetujui pemilik repo. Rencana analisis v2 menetapkan ukuran dan kriteria rincinya sebelum apa pun dijalankan.

1. **Sisi model, memakai ulang run store E1 dengan fold yang sama:**
   - X1, conformal ternormalisasi (kalibrasi interval);
   - skor OOD alternatif, diukur dengan H4 dan kemonotonan per desil;
   - monotone constraint meta-model untuk potensi pemulihan negatif, hanya bila syarat non-inferiority MAE (margin ditetapkan di rencana v2) ditulis lebih dulu, karena perubahan ini menyentuh H1a.
2. **Sisi data, butuh run baru:** level korupsi yang lebih kuat, outlier untuk kolom kategorikal, dataset dengan noise floor > 0,01 untuk H5, dan learner kedua (`analysis-plan.md` bagian 8).
3. **Konfirmasi:** semua perubahan dievaluasi pada dataset holdout. Hasil pada 31 dataset korpus epoch 0 berlabel eksploratif.

Kedua sisi diukur sebagai lengan terpisah terhadap epoch 0 sebagai pembanding, agar setiap efek bisa diatribusikan ke perubahannya. Perluasan level korupsi tidak dibingkai sebagai perbaikan H2: dampak MCAR yang kecil pada LightGBM adalah temuan epoch 0 yang sah.

## Hal terbuka **[T]**

| # | Butir | Rekomendasi agent | Ditutup sebelum |
| --- | --- | --- | --- |
| 1 | Lokasi arsip di luar git (drive eksternal, penyimpanan awan, atau keduanya) | Dua salinan di dua media, keduanya tercatat di manifest | Penutupan epoch 0 |
| 2 | Jumlah dataset holdout | ±15. Dengan 10 dataset, CI Clopper–Pearson untuk kriteria proporsi seperti H3 terlalu lebar untuk informatif | Penyegelan holdout |
| 3 | Posisi epoch 1 terhadap Sprint C | Diputuskan di tinjauan H1 akhir Phase 5 | G4 |

## Konsekuensi

- Phase 5 berisi E4, uji konsistensi jalur akhir, penyegelan holdout, dan penutupan epoch 0. X1 keluar dari Phase 5.
- KL-02 dan KL-04 tidak bisa dibuka di G4; paling cepat setelah epoch 1 lolos validasi holdout dan disetujui pemilik repo.
- Setiap epoch berikutnya mengikuti prosedur yang sama: rencana analisis dibekukan, holdout baru disegel, arsip dan manifest dibuat saat penutupan.
- Naskah skripsi dapat merujuk satu epoch secara utuh lewat manifest dan log insight-nya tanpa bergantung pada keadaan repo terkini.

## Alternatif yang ditolak

- **X1 tetap di Phase 5 (keputusan G3 semula).** Mencampur refinement ke dalam epoch 0 sehingga epoch 0 tidak lagi mewakili desain awal apa adanya.
- **Epoch 1 tanpa holdout.** Hasilnya hanya bisa eksploratif karena refinement dirancang dari data yang sama.
- **Menyimpan run store di git.** Ukurannya ratusan MB dan akan bertambah tiap epoch; manifest berhash memberi jaminan integritas yang sama tanpa membebani repo.
- **Menjalankan sisi model dan sisi data epoch 1 bersamaan.** Perbaikan tidak bisa diatribusikan ke penyebabnya.
