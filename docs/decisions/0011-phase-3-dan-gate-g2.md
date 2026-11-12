# ADR 0011: Phase 3 — desain pilot E0, kalibrator, scan eksperimental, dan gate G2

- **Status:** Diusulkan. Keputusan K1–K7 sudah diambil pemilik repo pada 12/11/2026. Keputusan G2 (bagian "Keputusan G2") masih menunggu hasil E0 dan persetujuan; sebelum G2 disetujui, rencana analisis belum dibekukan.
- **Tanggal:** 12/11/2026
- **Rilis terdampak:** R0, Phase 3
- **Rujukan:** `execution-plan.md` Phase 3; BR-04, BR-05, BR-22, BR-24, BR-30–BR-35, BR-60, BR-86; ADR 0006, 0010; [analysis-plan.md](../analysis-plan.md)

G2 membuka scan berlabel eksperimental: pilot E0 lolos, rencana analisis dibekukan, dan meta-model pilot tersedia (`product.md` 5.1).

## Keputusan yang sudah diambil (12/11/2026)

| # | Butir | Keputusan | Akibat |
| --- | --- | --- | --- |
| K1 | Dataset pilot | phoneme (1489), kr-vs-kp (3), churn (40701), segment (40984), adult (1590): biner dan multikelas, numerik dan kategorikal, termasuk satu dataset besar | `configs/e0.yaml` |
| K2 | Grid E0 | 45 konfigurasi tunggal dari `corruption.yaml` ditambah 10 kandidat campuran 2–3 jenis pada level sedang–tinggi, 5 seed per konfigurasi | 1.375 run |
| K3 | Seed noise floor di E0 | 10 seed terukur per dataset; 10 seed probe estimasi pada run seed index 0 tiap konfigurasi | Statistik dan jumlah seed final dibandingkan pada 2, 3, 5, dan 10 seed |
| K4 | OOD selama pilot | Ambang sementara = persentil ke-95 skor OOD leave-one-dataset-out (k = 5, standarisasi z) pada profil pilot, berlabel eksperimental, diganti di G3. Hal terbuka #3 tetap **[T]** | BR-33 tetap berlaku di scan pilot |
| K5 | Kuantil conformal (hal terbuka #4) | Bobot sama per dataset; tereduksi ke Contoh 3 bila jumlah run per dataset sama | `business-rules.md` bagian 3 |
| K6 | Pemotongan interval (hal terbuka #5) | Tidak dipotong di nol | `business-rules.md` bagian 3 |
| K7 | ΔAUC relatif saat scan | Null selama pilot. Rencana skripsi memakai meta-model terpisah untuk Δ relatif; diputuskan di Phase 4 | `ScanReport.estimate.delta_relative` |

## Keputusan implementasi **[K]** (diusulkan agent, ditinjau di G2)

- **Pemuat artefak terpisah:** `ceteris.artifact` dipisah dari pelatihan `ceteris.metamodel`, sehingga uji AC-3 mencakup pemuat artefak. `metamodel` juga dilarang di jalur scan.
- **Format artefak** (satu folder):
  - `metadata.json` (metadata wajib `architecture.md` 6.2);
  - `model.txt`;
  - `calibration.parquet`;
  - `ood_reference.parquet`;
  - `learner.yaml`.

  Saat dimuat, kuantil conformal dihitung ulang dan dicocokkan, dan hash spesifikasi learner diperiksa.
- **Kalibrasi artefak pilot:** skor kalibrasi adalah residu absolut leave-one-dataset-out, sehingga setiap skor berasal dari model yang tidak melihat datasetnya. Meta-model akhir dilatih pada semua dataset pilot. LODO bersarang dengan proper-train dan kalibrasi terpisah (F-S11) dibangun di Phase 4.
- **Hiperparameter meta-model pilot:** tetap, tanpa tuning:
  - `learning_rate` 0,05;
  - `num_leaves` 15;
  - `min_data_in_leaf` 20;
  - 300 ronde;
  - deterministik.
- **`ScanReport` 1.0:**
  - `status.reasons` ditambahkan;
  - `findings` kosong sampai F-S12;
  - snapshot skema JSON berversi di `tests/contracts/`.
- **Noise floor:**
  - tabel `noise_floor` di run store, satu baris per seed;
  - seed probe estimasi `noise_floor_seeds` diturunkan dari `PROFILE_SEED` dan sama di jalur riset dan scan;
  - data kotor run dan noise floor estimasinya dibangun oleh satu fungsi (`dirty_train`).
- **E0 dijalankan dari commit bersih:** setiap baris `run_log` mencatat commit dan status `git_dirty`.

## Hasil E0 **[F]**

Sumber: `runs/e0/report.json`, dihasilkan dari run store oleh `python -m ceteris.evaluate e0 --store runs/e0 --corpus data/corpus`. Semua angka per dataset diringkas dengan median antar-dataset (BR-85).

### Eksekusi dan provenance

- **Tugas:** 1.655 tugas selesai dalam 67 menit dengan 4 proses. Rinciannya:
  - 1.325 run;
  - 5 × 10 seed noise floor terukur;
  - 265 noise floor estimasi.
- **60 tugas gagal, semuanya karena struktur data.** kr-vs-kp hanya berisi kolom kategorikal, sehingga 10 konfigurasi yang memuat outlier (5 tunggal, 5 campuran) ditolak `CorruptionNotApplicable`, terdiri atas 50 run dan 10 noise floor estimasi. Penolakan tercatat di `run_log`. Tidak ada kegagalan lain.
- **Commit:** semua run mencatat commit `c297d19`.
- **`git_dirty`:** 1.313 baris `run_log` bertanda `git_dirty`, karena modul Phase 3 lain ditulis selagi E0 berjalan. Kode yang dijalankan tetap kode `c297d19`, karena worker memuat modul saat mulai.
- **Bukti reproduksi:**
  - di antara `c297d19` dan commit Phase 3, jalur kode E0 hanya bertambah 26 baris (fungsi baru `noise_floor_value`);
  - lima run bertanda dirty, satu per dataset, dihitung ulang dari commit bersih dan hasilnya identik (ΔAUC, AUC, `affected_row_frac`, 25 fitur profil).

### Noise floor

- **Noise floor terukur di bawah 0,01 di semua dataset**, dengan rata-rata |selisih| antar-pasangan seed pada 10 seed:

  | Dataset | Noise floor terukur |
  | --- | --- |
  | kr-vs-kp | 0,0001 |
  | phoneme | 0,0015 |
  | adult | 0,0004 |
  | churn | 0,0043 |
  | segment | 0,0001 |

  Satu-satunya nilai di atas 0,01 adalah rentang 10 seed di churn (0,0105). Akibatnya `T` = 0,01 hampir di semua kasus.
- **Rentang dan persentil ke-95 |selisih| membesar seiring jumlah seed**, misalnya churn naik dari 0,0046 (2 seed) ke 0,0105 (10 seed). Rata-rata |selisih| dan simpangan baku stabil antara 5 dan 10 seed.
- **Pratinjau H5 (bukan uji):** median selisih absolut noise floor estimasi terhadap terukur ≤ 0,0008 untuk semua statistik dan jumlah seed. Bias median antara −0,0004 dan 0,0000.

### Dampak per jenis korupsi

- **Median ΔAUC per jenis tunggal dan level:**

  | Jenis | Level | Median ΔAUC |
  | --- | --- | --- |
  | Label uniform | 0,02 / 0,10 / 0,30 | 0,0003 / 0,0073 / 0,0590 |
  | Label class-conditional | 0,30 | 0,0558 |
  | Duplikat-konflik | 0,50 | 0,0152 |
  | Missing MCAR | 0,50 | 0,0007 |
  | Missing MAR | 0,50 | 0,0012 |
  | Outlier | 0,20 | 0,0007 |
  | Duplikat eksak | semua level | ≈ 0 |

- **Kriteria pilot rencana skripsi** (≥ 30% run tiap jenis di atas `T`, berstatus asumsi) dibandingkan dengan median per dataset:

  | Jenis | Median per dataset | Seluruh run | Kriteria |
  | --- | --- | --- | --- |
  | Label uniform | 40% | — | terpenuhi |
  | Label class-conditional | 40% | — | terpenuhi |
  | Duplikat-konflik | 44% | — | terpenuhi |
  | Campuran | 26% | 36% | tidak terpenuhi |
  | Missing MCAR | 0% | 12% | tidak terpenuhi |
  | Missing MAR | 0% | 10% | tidak terpenuhi |
  | Outlier | 0% | 1% | tidak terpenuhi |
  | Duplikat eksak | 0% | 1% | tidak terpenuhi |

  Statistik noise floor tidak mengubah angka ini, karena `T` didominasi lantai 0,01.
- **Campuran:** kandidat yang memuat label noise punya median ΔAUC 0,007–0,016. Kandidat tanpa label noise ≤ 0,005.

### Komputasi

- **Median detik per run** (4 proses paralel):

  | Dataset | Detik per run |
  | --- | --- |
  | phoneme | 1,7 |
  | kr-vs-kp | 2,7 |
  | churn | 2,9 |
  | adult | 11,1 |
  | segment | 11,7 |

- **Noise floor estimasi dengan 10 seed:** 7–56 detik per run.
- **Proyeksi kasar korpus penuh** (31 dataset × 55 konfigurasi × 5 seed, ditambah noise floor estimasi per konfigurasi): **≈ 68 jam CPU**, atau ≈ 17 jam dengan 4 proses. Proyeksinya memakai log(detik) linear terhadap log(baris × kolom × kelas efektif) dari 5 dataset pilot, sehingga ketidakpastiannya besar untuk dataset 10 kelas dengan ratusan kolom.

### Meta-model dan scan pilot (eksploratif, n = 5 dataset)

- **LODO pilot, median MAE:**

  | Metode | Median MAE |
  | --- | --- |
  | Meta-model | 0,0091 |
  | Baseline (a) | 0,0105 |
  | Baseline (b) | 0,0142 |
  | Baseline (c) | 0,0114 |

  Meta-model lebih baik dari (a) di 5/5 dataset dan dari (c) di 3/5. Ini bukan uji H1a.
- **Artefak pilot sementara:**
  - kuantil conformal ±0,022;
  - coverage LODO per dataset 86–94% (median 90,5%);
  - ambang OOD sementara 6,04.
- **Scan pada data E0 nyata** berjalan 3–23 detik. Karena setengah lebar interval (0,022) lebih besar dari `T` (0,01), status `material` hanya mungkin bila estimasi di atas 0,032, sehingga sebagian besar scan pilot berstatus `tidak_yakin`.

## Keputusan G2 yang masih terbuka **[T]**

| # | Butir | Opsi | Rekomendasi dan alasan |
| --- | --- | --- | --- |
| G2-1 | Statistik noise floor dan jumlah seed (hal terbuka #1, P1 rencana analisis) | A: rata-rata \|selisih\| antar-pasangan seed, 10 seed terukur dan 5 seed estimasi. B: persentil ke-95 \|selisih\|, 10 seed keduanya. C: rentang, 10 seed keduanya | **A.** Paling dekat dengan definisi BR-04 ("selisih AUC dua model ... seed berbeda"). Nilainya stabil terhadap jumlah seed, sehingga scan cukup 5 seed (biaya separuh) dan tetap sebanding dengan nilai terukur 10 seed. Statistik tidak mengubah status di pilot karena `T` didominasi lantai 0,01 |
| G2-2 | Level grid untuk jenis yang jarang di atas `T` (P3, agenda bimbingan A12) | A: grid tetap; kriteria ≥ 30% dicatat tidak terpenuhi untuk missing, outlier, dan duplikat eksak, dan hal itu dilaporkan sebagai temuan. B: tambah level tinggi, yaitu missing 0,65 dan 0,80 serta outlier 0,30 dan 0,50 (+10 konfigurasi, +18% komputasi). C: tunda sampai dibahas dengan pembimbing | **A, dan bawa ke pembimbing.** Pada level tertinggi sekarang (missing 0,50, duplikat eksak 0,50) median ΔAUC masih ≤ 0,0012. LightGBM menangani nilai kosong secara bawaan, dan pohon kebal terhadap outlier serta duplikat eksak. Dampak rendah ini adalah bagian jawaban H2, bukan kegagalan desain |
| G2-3 | Campuran final (P2) | A: kesepuluh kandidat. B: hanya kandidat yang memuat label noise | **A.** Rentang dampaknya lebar (median ΔAUC 0,0001–0,016). Kombinasi "volume besar, dampak kecil" dengan "volume kecil, dampak besar" adalah kasus yang diuji H2b |
| G2-4 | Dataset dengan noise floor > 0,01 (P4, DV-06) | A: dipertahankan; `T = max(0,01; nf)` sudah menyesuaikan. B: dikeluarkan. C: split berulang | **A.** Tidak ada dataset pilot di atas 0,01 dengan statistik A. Korpus 31 dataset sudah di batas bawah sasaran, dan BR-05 sudah menangani noise floor tinggi |
| G2-5 | Subset "noise floor dekat 0,01" untuk kappa H5 (P5, ADR 0006) | A: kuartil teratas noise floor terukur di korpus, minimal 8 dataset. B: noise floor terukur ≥ 0,005 | **A.** Di pilot, ambang tetap 0,005 menghasilkan subset kosong (maksimum 0,0043). Batas berbasis kuartil selalu berisi cukup dataset untuk kappa |
| G2-6 | Mesin komputasi korpus penuh (arsitektur #7) | A: mesin lokal 4 inti, runner bisa dilanjutkan, ≈ 17–20 jam dinding dalam 2–3 sesi. B: VM awan ≥ 16 vCPU, ≈ 5 jam | **A.** Proyeksi muat di mesin yang ada dan data korpus publik tidak perlu dipindahkan. Pindah ke B bila proyeksi E1 nyata lebih dari 2× |
| G2-7 | Baseline (d) (P7) | Operasionalisasi usulan (lihat di bawah). Waktu implementasi: sekarang sebelum G2 ditutup, atau di awal Phase 4 | **Sekarang**, karena F-S09 (a)–(d) adalah scope Phase 3. Pilot (d) pada subset E0 juga memberi angka biaya untuk H1b |
| G2-8 | Jumlah perbandingan Holm untuk H1a (DV-11) | 3 (baseline a–c) atau 4 | **3.** H1b terhadap (d) diuji terpisah sebagai non-inferiority |
| G2-9 | Grid tuning meta-model di LODO bersarang (P6) | Usulan: `num_leaves` {7, 15, 31} × `learning_rate` {0,03; 0,1} × `min_data_in_leaf` {10, 40}, 300 ronde, grouped CV 3 lipatan per dataset di proper-train | Grid kecil (12 kombinasi) agar tuning tidak mendominasi biaya |

**Operasionalisasi baseline (d) yang diusulkan (G2-7).** Untuk satu run, hanya data kotor Dₖ yang dipakai:

1. **Taksiran proporsi baris terdampak saat ini, per jenis:**
   - missing: proporsi baris dengan minimal satu sel kosong;
   - label noise: `label_noise_rate`;
   - duplikat eksak: `dup_row_rate`;
   - duplikat-konflik: `dup_conflict_rate`;
   - outlier: `outlier_row_frac_iforest`.

   Jenis "terdeteksi" adalah jenis dengan taksiran > 0.
2. **Pembagian Dₖ:** berstrata menjadi latih 80% dan hold-out 20%, dengan seed tetap. Korupsi tambahan hanya disuntikkan ke bagian latih.
3. **Dosis:** +5%, +10%, dan +20% baris terdampak, dibagi antar-jenis terdeteksi sebanding dengan taksirannya. Mekanismenya:
   - missing MCAR pada 3 kolom ber-importance tertinggi;
   - label uniform;
   - outlier;
   - duplikat eksak;
   - duplikat-konflik.
4. **Pengukuran:** learner acuan dilatih untuk keempat titik (saat ini dan tiga dosis), dan AUC diukur pada hold-out.
5. **Ekstrapolasi:** garis AUC terhadap proporsi terdampak total diekstrapolasi ke nol, sehingga Δ = AUC(0) − AUC(saat ini). Kuadratik dilaporkan sebagai pembanding. Bila tidak ada jenis terdeteksi, Δ = 0.
6. **Subset:** 1 seed × semua konfigurasi × semua dataset, dengan waktu CPU dicatat.

## Bukti Phase 3

- **Uji:** 168 uji lulus, cakupan paket 92%; `ruff check`, `ruff format --check`, dan `mypy` strict bersih.
- **Kriteria selesai Phase 3 (`execution-plan.md`):**

  | Kriteria | Bukti |
  | --- | --- |
  | Uji kontrak `ScanReport` (BR-60) | Snapshot skema JSON berversi; field tak dikenal dan interval terbalik ditolak; kalimat kondisi BR-06 tetap |
  | Uji tabel status | Contoh 2 (kasus A–E) dan baris status Contoh 5 lulus persis; uji properti BR-30 dan BR-34 lulus |
  | Konsistensi jalur riset dan scan (BR-16) | Profil tersimpan sama persis dengan profil scan; selisih prediksi < 1e-9 |
  | Label eksperimental (BR-35) | Artefak pilot `experimental = true`, dan `ScanReport.model.experimental` mengikutinya |
  | Pemuat artefak dipisah dari pelatihan | `ceteris.artifact`; uji AC-3 mencakup `artifact` dan melarang `metamodel` di jalur scan |

- **Belum ada:**
  - potensi pemulihan (F-S12);
  - LODO bersarang (F-S11);
  - skor OOD penuh (Phase 4).

  Baris gate Contoh 5 (kebijakan ditolak saat disimpan, BR-50 dan BR-51) adalah fitur R2.

## Setelah G2 disetujui

1. Nilai G2-1 sampai G2-9 masuk `analysis-plan.md` bagian 7, dan rencana analisis dibekukan dengan tanggal (BR-86).
2. `business-rules.md` hal terbuka #1 ditutup. Campuran final masuk `configs/corruption.yaml` (versi naik).
3. Artefak meta-model pilot dibangun ulang dengan statistik noise floor final dan disimpan sebagai `artifacts/metamodel-0.1.0-pilot/`.
4. Status ADR ini dan Phase 3 di `execution-plan.md` menjadi selesai, sehingga Phase 4 bisa dimulai.
