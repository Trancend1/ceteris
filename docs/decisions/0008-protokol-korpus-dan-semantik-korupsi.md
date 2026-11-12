# ADR 0008: Protokol korpus dan semantik korupsi Phase 1

- **Status:** Diterima **[K]** (keputusan pemilik repo, 11/11/2026); nilai yang berlabel DRAF dibekukan di G1 atau diputuskan di pilot E0
- **Tanggal:** 11/11/2026
- **Rilis terdampak:** R0, Phase 1 (F-S01, F-S02, F-S03, F-S07)
- **Rujukan:** BR-10, BR-11, BR-80, BR-82, BR-83, BR-84; glosarium "Korpus" dan "`affected_row_frac`"; `configs/experiment.yaml`, `configs/corruption.yaml`, `configs/learner.yaml`

## Konteks

Glosarium menyaring korpus OpenML-CC18 pada 2.000–50.000 baris dengan missing asli ≤ 5%, tetapi tidak menyebut apakah missing diukur per sel atau per baris, dan tidak menyelaraskan korpus dengan kontrak input scan. Semantik level korupsi per jenis juga belum tertulis, padahal BR-82 membandingkan jenis korupsi lewat `affected_row_frac`.

**[F]** Metadata OpenML (dicek 11/11/2026) memperkirakan 30 dataset lolos. **[F]** Penyiapan nyata pada 11/11/2026 memberi angka yang berbeda: CC18 berisi 72 dataset, 37 berada di rentang baris, dan **31 lolos**. Enam ditolak: letter (26 kelas), isolet (617 fitur, 26 kelas), har (561 fitur), Bioresponse (1.776 fitur), Internet-Advertisements (1.558 fitur), dan sick (missing 5,54% per sel). Selisih dengan perkiraan metadata ada pada dua dataset: madelon lolos karena fiturnya tepat 500 (metadata menghitung target sebagai fitur), dan sick ditolak oleh hitungan missing pada data sebenarnya.

## Keputusan

1. **Saringan korpus = glosarium + kontrak input scan.** 2.000–50.000 baris, missing asli ≤ 5% **per sel fitur**, ≤ 500 kolom fitur (BR-10), 2–20 kelas dengan tiap kelas ≥ 20 baris (BR-11). Syarat ≥ 20 baris per kelas diperiksa juga pada **partisi latih**, karena scan hanya melihat partisi latih (BR-17). Meta-model hanya belajar dari bentuk data yang memang diterima scan.
2. **Protokol D₀ minimal:** baris dengan target kosong dibuang; kolom teks, objek, dan boolean menjadi kategorikal; kolom numerik nullable pandas (Int64, Float64) menjadi tipe numpy (int64 bila tanpa nilai kosong, selain itu float64); target menjadi kategorikal berurut. Hanya tipe yang berubah; tidak ada imputasi atau perbaikan lain (BR-70).
3. **Satu parser ARFF untuk seluruh korpus:** `liac-arff` milik scikit-learn. **[F]** Parser `pandas` (pilihan "auto") gagal pada sebagian CC18 dengan pandas 3.1 karena kategori bertipe integer.
4. **Split tetap per dataset:** stratified, `test_frac` 0,2 (**DRAF**, mengikuti ilustrasi Contoh 4), seed hanya dari `dataset_id`, sehingga semua run pada satu dataset memakai partisi uji yang sama. Hash partisi uji dicatat dan diperiksa sebelum dan sesudah setiap run (BR-80).
5. **Semantik level korupsi:**
   - missing MCAR dan MAR: tepat round(level × n) sel per kolom terpilih, hanya pada sel yang belum kosong; MAR memilih sel dengan peluang naik menurut peringkat satu kolom pendorong;
   - label uniform: tepat round(level × n) baris berganti ke kelas lain secara acak; class-conditional: round(level × n_c) baris per kelas berpindah ke kelas berikutnya;
   - outlier: tepat round(level × n) baris, masing-masing satu kolom numerik diganti nilai di luar rentang teramati sejauh `scale` × IQR;
   - duplikat eksak dan konflik label: round(level × n) baris salinan **ditambahkan**; `affected_row_frac` = baris tambahan / total baris kotor.
6. **`affected_row_frac` dihitung dari perbandingan nyata** antara baris kotor dan baris asalnya, bukan dari niat korupsi.
7. **Seed:** seed run dari (`dataset_id`, `config_id`, indeks seed) (BR-84); seed korupsi dan learner diturunkan dari seed run dengan label tujuan. Learner yang sama dan seed yang sama dipakai untuk model versi bersih dan versi kotor. Urutan kanonik dan seed per langkah diturunkan dari isi spesifikasi, sehingga urutan masukan tidak mengubah hasil; `config_id` memuat hash seluruh spesifikasi learner.
8. **Dua modul pendukung** di paket `ceteris`: `seeding` (turunan seed, aman untuk jalur scan) dan `experiment` (orkestrasi satu run riset; mengimpor `corpus` dan `corrupt`, sehingga ikut dilarang di jalur scan oleh uji impor AC-3).

## Konsekuensi

- Korpus berada di batas bawah sasaran 30–50 dataset. Bila pilot E0 menunjukkan korpus terlalu kecil, perluasan dilakukan lewat suite lain, bukan dengan melonggarkan BR-10 atau BR-11.
- Grid level di `configs/corruption.yaml` dan spesifikasi learner di `configs/learner.yaml` masih DRAF.
- **[T]** Dengan `configs/learner.yaml` sekarang (tanpa bagging, `feature_fraction` 1), seed tidak memengaruhi LightGBM: **[F]** seed 1 dan 987654 memberi prediksi identik (dicek 11/11/2026). Akibatnya noise floor terukur (BR-04) akan selalu 0. Sumber keacakan learner harus diputuskan sebelum G1 (`business-rules.md` bagian 11).
- Duplikat menambah ukuran partisi latih, sehingga learner melihat lebih banyak baris pada run duplikat; ini disengaja karena begitulah duplikat muncul di data nyata.

## Pembaruan 12/11/2026

[ADR 0009](0009-paket-keputusan-g1.md) mengubah sebagian butir 5 dan menutup **[T]** keacakan learner:

- MAR memilih kolom pemicu dengan korelasi absolut tertinggi; bobot peringkat dan jumlah sel tepat tetap.
- Label noise class-conditional: laju asimetris 2:1 pada data biner (kelas minoritas sebagai positif) dan perpindahan ke kelas yang paling sering tertukar menurut confusion matrix learner acuan pada D₀ untuk multikelas.
- Outlier ditempatkan di luar pagar Tukey dengan k ∼ U[3; 10] per sel; tetap satu kolom numerik per baris terdampak.
- Missing disuntikkan ke 3 kolom ber-importance tertinggi atau 3 terendah, sebagai dua konfigurasi terpisah.
- Grid level mengikuti rencana skripsi; learner acuan memakai bagging baris.

Butir lain di ADR ini tetap berlaku. Implementasinya dikerjakan di Phase 2.

## Alternatif yang ditolak

- Saringan glosarium saja (36 dataset): 6 dataset berbentuk yang akan ditolak scan pengguna.
- Missing per baris: membuang adult (0,9% sel, 7,4% baris) tanpa alasan kuat.
- Duplikat mengganti baris: mencampur dua kerusakan (duplikasi dan kehilangan data).
