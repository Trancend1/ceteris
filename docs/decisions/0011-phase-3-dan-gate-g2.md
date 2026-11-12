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

## Hasil E0

<!-- E0 -->

## Keputusan G2 yang masih terbuka

<!-- G2 -->

## Bukti Phase 3

<!-- BUKTI -->
