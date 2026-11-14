# ADR 0015: Epoch 1 berjalan sejajar dengan Sprint C

- **Status:** Diterima **[K]** oleh pemilik repo 14/11/2026.
- **Tanggal:** 14/11/2026
- **Rilis terdampak:** R0 (epoch 1), R1 (Sprint C dan D)
- **Rujukan:** [ADR 0013](0013-epoch-eksperimen-dan-pelestarian.md) (hal terbuka #3, agenda butir 7), [ADR 0014](0014-phase-5-e4-dan-holdout.md) (hasil E4); [execution-plan.md](../execution-plan.md) prinsip 1, Phase 6–8; `product.md` 5 (kriteria keluar R1); [insights.md epoch 0](../epochs/epoch-0/insights.md) I-08, I-14, I-15, I-21

## Konteks

- **Kriteria keluar R1** adalah "5 ML engineer menjalankan scan pada data sendiri" (`product.md` 5). Isi R1 (F-L01–F-L05) adalah platform yang mengonsumsi artefak meta-model. Mutu estimasi tetap ditentukan artefaknya.
- **Keadaan artefak epoch 0 [F]:**
  - 86% prediksi LODO berstatus `tidak_yakin` (I-08);
  - interval dan status tetap eksperimental karena H3 gagal;
  - pada data kotor asli E4, keempat pasangan berskor OOD tinggi dan meta-model melebih-lebihkan dampaknya (I-14, I-15).
- **Data pengguna R1 tidak bisa menjadi data latih epoch 1,** karena data mentah tidak meninggalkan lingkungan pengguna (BR-70, AC-6). Menunggu R1 selesai tidak menambah bahan untuk epoch 1.
- **Pekerjaan platform R1 tidak bergantung pada mutu artefak.** Model registry (F-L04) dirancang untuk mengganti versi artefak (BR-23, BR-63).

## Keputusan **[K]**

1. **Hal terbuka ADR 0013 #3 ditutup.** Epoch 1 berjalan **sejajar** dengan Phase 6–8 sebagai jalur riset tersendiri.
   - Prinsip "berurutan" (`execution-plan.md` prinsip 1) tetap berlaku di antara phase produk.
   - Jalur epoch 1 tidak menahan phase produk, dan phase produk tidak menahan epoch 1.
2. **Urutan di dalam epoch 1:**
   1. rencana analisis epoch 1 dibekukan sebelum apa pun dijalankan;
   2. sisi model dijalankan lebih dulu (memakai ulang run store E1, murah);
   3. sisi data dijalankan dengan run baru di latar;
   4. evaluasi konfirmatori pada 15 dataset holdout;
   5. epoch 1 ditutup menurut ADR 0013 butir 6.
3. **Uji 5 ML engineer menunggu epoch 1.** Uji pengguna untuk kriteria keluar R1 baru dilakukan setelah epoch 1 ditutup. Uji itu memakai artefak terbaik yang lolos evaluasi holdout dan aturan rilis artefak (BR-63). Bila epoch 1 tidak menghasilkan artefak yang lebih baik, uji tetap memakai artefak `1.0.0` dengan labelnya apa adanya, dan keputusan itu dicatat.
4. **Selama Phase 7–8, platform memakai artefak `1.0.0`** lewat registry. Penggantian artefak tidak mengubah kontrak API atau `ScanReport`.
5. **Agenda epoch 1 (ADR 0013 butir 7) ditambah satu butir:** jenis kekotoran nyata yang tidak tercakup grid korupsi, mulai dari inkonsistensi representasi nilai kategorikal (I-21). Butir ini butuh jenis korupsi baru dan fitur profil baru, sehingga berarti skema profil v2 dan run ulang korpus. Butir ini diukur sebagai lengan tersendiri; rencana analisis epoch 1 menentukan apakah lengan ini masuk epoch 1 atau ditunda **[T]**.

## Konsekuensi

- **Sumber daya:** jalur riset dan jalur produk memakai mesin lokal 4 inti yang sama. Run sisi data epoch 1 dijalankan di latar dan dapat memperlambat pekerjaan produk; pemindahan ke VM awan mengikuti aturan P8 (`analysis-plan.md` bagian 7).
- **Kriteria keluar R1 bergantung pada penutupan epoch 1.** Bila epoch 1 tertunda, G5 dan Sprint D tetap berjalan, tetapi uji pengguna R1 menunggu.
- **Phase 6:** keputusan pra-R1 sebaiknya memperhitungkan bahwa versi artefak akan berganti satu kali sebelum uji pengguna.

## Alternatif yang ditolak

- **Epoch 1 setelah R1.** Uji pengguna R1 akan memakai artefak yang kelemahannya sudah diketahui (status hampir selalu `tidak_yakin`, OOD pada data nyata), dan kesan pertama 5 pengguna hanya bisa didapat sekali. Data pengguna juga tidak bisa dipakai untuk memperbaiki model.
- **Epoch 1 sebelum Phase 6.** Pekerjaan platform tidak bergantung pada mutu artefak, sehingga menahannya hanya memperlambat R1.
