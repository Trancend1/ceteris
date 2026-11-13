# ADR 0014: Phase 5 — sumber E4, tipe kolom CSV, holdout epoch 1, dan arsip epoch 0

- **Status:** Diterima **[K]** oleh pemilik repo 14/11/2026 (empat pilihan di bawah). Rincian pelaksanaan diusulkan agent.
- **Tanggal:** 14/11/2026
- **Rilis terdampak:** R0, Phase 5
- **Rujukan:** BR-10, BR-11, BR-14, BR-16, BR-80, BR-81, BR-84; hal terbuka #12 `business-rules.md`; [ADR 0008](0008-protokol-korpus-dan-semantik-korupsi.md), [ADR 0013](0013-epoch-eksperimen-dan-pelestarian.md); [analysis-plan.md](../analysis-plan.md) bagian 11

## Keputusan **[K]**

### 1. Sumber data E4: CleanML, versi bersih manual

- Pasangan E4 diambil dari benchmark CleanML, dari dataset dengan error nyata dan versi bersih buatan manusia.
- Arsip `CleanML-datasets-2020.zip` diunduh dari tautan Dropbox di README repositori `chu-data-lab/CleanML`, dengan persetujuan pemilik repo 14/11/2026.
- Lisensi data tidak tercantum di repositori **[F]**. Karena itu:
  - data hanya dipakai untuk riset lokal;
  - data tidak didistribusikan ulang dan tidak di-commit;
  - arsip asli dicatat dengan SHA-256 di manifest epoch 0.
- Kandidat, kelayakan, split, dan ukuran ada di `analysis-plan.md` bagian 11, ditulis sebelum data diunduh.

### 2. Tipe kolom CSV (hal terbuka #12 ditutup)

- E4 memakai Parquet dengan tipe eksplisit.
- Scan CSV tetap membaca tipe apa adanya (`pandas.read_csv`) dan tidak menebak.
- Untuk setiap kolom fitur bertipe integer (atau float yang semua nilainya bilangan bulat) dengan ≤ 20 nilai unik, scan CSV menambahkan peringatan `csv_integer_low_cardinality: <kolom>` ke `input_warnings`. Angka 20 sama dengan batas kelas BR-11.
- Profil dan estimasi tidak berubah, dan kontrak `ScanReport` tidak berubah.

### 3. Dataset holdout epoch 1: ±15 dataset

Pelaksanaan aturan seleksi ADR 0013 butir 5:

1. **Kumpulan kandidat:**
   - dataset di studi OpenML 14 (OpenML100), 218, dan 271 (AutoML benchmark);
   - dikurangi semua anggota OpenML-CC18 (studi 99);
   - dikurangi dataset yang namanya (tanpa beda huruf besar-kecil) sama dengan dataset korpus epoch 0.
2. **Pra-saring dari kualitas OpenML,** tanpa mengunduh data: jumlah baris, jumlah fitur, jumlah kelas, ukuran kelas minoritas, dan jumlah nilai kosong, memakai batas saringan korpus Phase 1.
3. **Undian:** kandidat yang lolos diurutkan dengan permutasi berseed `derive_seed("holdout", "epoch-1")`.
4. **Penyiapan:** dataset disiapkan berurutan menurut permutasi itu dengan `ceteris.corpus.prepare_dataset` (protokol D₀, saringan penuh, split tetap) di `data/holdout-epoch-1/`, sampai 15 dataset lolos. Yang dihitung hanya atribut saringan; tidak ada run korupsi, profil, atau eksplorasi lain.
5. **Segel:**
   - daftar ID, versi OpenML, checksum sumber, dan hash D₀ serta test set dicatat di `docs/epochs/epoch-0/holdout.json`, beserta SHA-256 berkas itu;
   - di-commit sebelum rencana analisis epoch 1 ditulis;
   - bila kandidat yang lolos kurang dari 15, semuanya dipakai dan kekurangannya dicatat.

### 4. Arsip epoch 0: dua salinan

- **Salinan lokal:** `D:\DevSpace\Archive\ceteris\epoch-0\` (di luar repo), dibuat agent.
- **Salinan awan:** diunggah pemilik repo. Lokasinya dicatat di `MANIFEST.md` setelah diunggah.
- Kedua salinan diverifikasi terhadap SHA-256 di manifest.

## Konsekuensi

- Hal terbuka #12 `business-rules.md` ditutup. Hal terbuka ADR 0013 #1 dan #2 ditutup.
- Penutupan epoch 0 baru lengkap setelah salinan awan tercatat.

## Alternatif yang ditolak

- **Heuristik tipe otomatis untuk CSV.** Menebak bentuk data bertentangan dengan bagian 2 `business-rules.md`, dan akan membuat jalur CSV berbeda dari jalur riset.
- **Batas baris korpus untuk E4.** Dataset CleanML banyak yang kecil. RQ4 justru menguji data nyata di luar rentang korpus, jadi status `tidak_yakin` karena OOD adalah hasil yang sah.
- **Holdout dari anggota CC18 yang gagal saringan.** Mereka gagal saringan yang sama, sehingga tidak akan lolos sekarang.
