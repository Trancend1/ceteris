# Rencana Eksekusi Ceteris

Dokumen ini menurunkan roadmap di [product.md](product.md) bagian 5 menjadi **sprint dan phase** yang berurutan, lengkap dengan scope, deliverable, dan kriteria selesai. Ia tidak mengubah roadmap, aturan, atau arsitektur; bila bertentangan, dokumen sumber menang ([AGENTS.md](../AGENTS.md) bagian 2).

Penanda: **[F]** fakta terverifikasi · **[K]** keputusan desain · **[T]** terbuka. **Status dokumen: disetujui pemilik repo pada 10/11/2026 [K].** Dua hal tetap **[T]**: mekanisme login R1 dan urutan G4 terhadap Sprint C (lihat Phase 6 dan bagian 5).

## 1. Prinsip

1. **Berurutan.** Satu phase dimulai hanya setelah kriteria selesai phase sebelumnya terpenuhi. Tidak ada tanggal atau durasi; yang ada hanya rilis, gerbang, dan kriteria keluar (AGENTS.md bagian 4).
2. **Gerbang terakhir adalah Web UI R1 (G7).** Rencana ini berhenti di sana. Gate CI (R2), dashboard dan trust (R4), konektor (R3), dan KPI pengguna R1 berada di luar rencana ini.
3. **Desain mendahului visual.** Tidak ada kode UI, instalasi Next.js, mockup visual, atau komponen sebelum dokumen desain UI disetujui (G6). Phase 9 hanya menghasilkan dokumen; Phase 10–11 hanya boleh dimulai setelah persetujuan tertulis pemilik repo.
4. **Klaim mengikuti bukti.** Semua angka mode learned berlabel *eksperimental* sampai G3 (BR-35). Hasil negatif diterima dan dilaporkan apa adanya.
5. **Tidak membangun fitur R1+ selama R0 berjalan** (AGENTS.md bagian 1).

## 2. Peta sprint, phase, dan gerbang

```text
Sprint A  Fondasi dan data riset
  Phase 0  Fondasi repo                      [selesai]
  Phase 1  Data, korupsi, run store, learner
  Phase 2  Profil kualitas data           ──► G1
Sprint B  Bukti ilmiah (R0)
  Phase 3  Pilot dan scan eksperimental   ──► G2
  Phase 4  Korpus penuh dan artefak v1    ──► G3
  Phase 5  Validasi data kotor asli       ──► G4  ──► tinjauan H1
Sprint C  Platform R1
  Phase 6  Keputusan pra-R1 dan backlog
  Phase 7  API, worker, registry
  Phase 8  Histori, login, self-host      ──► G5
Sprint D  Web UI R1
  Phase 9  Desain UI (dokumen saja)       ──► G6  (persetujuan pemilik repo)
  Phase 10 Fondasi UI
  Phase 11 Implementasi F-L02             ──► G7  (gerbang terakhir)
```

Gerbang G1–G4 didefinisikan di [product.md](product.md) bagian 5.1 dan G5–G7 di bagian 5.3. Baris gerbang di bawah hanya mengaitkan gerbang dengan phase; definisinya tidak diulang.

## 3. Kriteria selesai yang berlaku di setiap phase

Selain kriteria khusus phase, setiap phase menunggu hal berikut:

- Build, `ruff check`, `ruff format --check`, dan `mypy` bersih; uji yang relevan lulus.
- Setiap aturan `BR-xx` yang diimplementasikan punya uji yang disebut di kolom Verifikasi, dengan ID aturan di nama atau docstring uji.
- Dokumen yang terdampak diperbarui; keputusan baru menjadi ADR di `docs/decisions/`.
- Tidak ada dependensi baru tanpa pemeriksaan lisensi dan persetujuan.
- Catatan serah-terima singkat (apa yang berubah, apa yang sengaja tidak, risiko, langkah berikutnya) dan tinjauan oleh peran yang berbeda dari pembuatnya (`WORKFLOW.md` bagian 8 dan 11).

---

## Sprint A — Fondasi dan data riset

### Phase 0 — Fondasi repo

**Status: selesai.**

| | |
| --- | --- |
| Scope | Dokumen, aturan agent, ADR 0001–0004, kerangka paket `ceteris`, perkakas kualitas |
| Deliverable | `docs/`, `AGENTS.md`, `.mcp.json`, `pyproject.toml`, `uv.lock`, `.gitignore`, 10 modul stub, uji impor AC-3 |
| Kriteria selesai | Terpenuhi: 2 uji lulus; `ruff`, format, dan `mypy` strict bersih; semua di `main` |

### Phase 1 — Data, korupsi, run store, learner acuan

| | |
| --- | --- |
| Scope | F-S01 `corpus`, F-S02 `corrupt`, F-S03 `train`, F-S07 `store` |
| Deliverable | Loader OpenML-CC18 dengan hash dan lisensi tercatat; split tetap; fungsi korupsi deterministik; harness pelatihan learner acuan (LightGBM) yang mengukur ΔAUC; skema run store Parquet + DuckDB; turunan seed (BR-84); draf `configs/learner.yaml` dan `configs/corruption.yaml` |
| Kriteria selesai | Uji properti `affected_row_frac` sesuai level yang diminta (BR-82); uji determinisme (BR-03, AC-12); test set tidak pernah diubah dan korupsi hanya pada partisi latih (BR-80); unduhan ulang idempoten; setiap baris `run_log` mencatat commit dan seed; cakupan paket ≥ 80% (NFR-11) |
| Di luar scope | Profil, meta-model, scan |

### Phase 2 — Profil kualitas data dan G1

| | |
| --- | --- |
| Scope | F-S04 `dqprofile` v1 dan praproses kontrak input, F-S05 estimator label noise, kerangka pengukuran noise floor terukur (sisi `train`, F-S06) |
| Deliverable | `ceteris.dqprofile` v1 (satu implementasi untuk riset dan scan, AC-1); kontrak input dengan penolakan eksplisit (BR-10–BR-17); estimator label noise; harness probe noise floor |
| Syarat masuk | **[T]** #6 daftar hal terbuka `business-rules.md` (definisi kolom ID dan kebocoran target) diputuskan; persetujuan pembimbing atas RQ2b dan H5 |
| Kriteria selesai | Uji isolasi profil: `dqprofile` hanya menerima data kotor (BR-20, AC-2); uji impor AC-3 lulus; pelanggaran berat menghentikan scan tanpa estimasi parsial; spesifikasi learner acuan dan skema profil dibekukan sebagai versi |
| **Gerbang G1** | Lihat `product.md` 5.1. Setelah ini perubahan skema profil atau learner berarti versi baru (AGENTS.md bagian 5) |

---

## Sprint B — Bukti ilmiah (R0)

### Phase 3 — Pilot dan scan eksperimental

| | |
| --- | --- |
| Scope | Pilot E0 pada 5 dataset; F-S08 (versi pilot), F-S09 baseline (a)–(d), F-S10 (prototipe kalibrator conformal), F-S13 `ceteris scan`, F-S14 status hasil |
| Deliverable | Rencana analisis bertanggal dan dibekukan (BR-86); meta-model pilot; baseline; `ScanReport` v1 (Pydantic) dan CLI; status menurut BR-30–BR-35; keputusan mesin komputasi untuk korpus penuh |
| Keputusan yang harus ditutup | **[T]** BR #1 statistik noise floor dan jumlah seed probe; BR #4 kuantil conformal; BR #5 pemotongan interval di nol; arsitektur #7 mesin komputasi |
| Kriteria selesai | Uji kontrak `ScanReport` (BR-60); uji tabel status: contoh 2 dan contoh 5 di `business-rules.md` lulus persis; uji konsistensi jalur riset dan scan (BR-16); seluruh keluaran berlabel eksperimental (BR-35); pemuat artefak dipisah dari kode pelatihan agar uji AC-3 mencakupnya |
| **Gerbang G2** | Lihat `product.md` 5.1 |

### Phase 4 — Korpus penuh dan artefak v1

| | |
| --- | --- |
| Scope | Pelatihan pada korpus penuh; F-S08, F-S10 (penuh, termasuk skor OOD), F-S11 evaluator LODO bersarang, F-S12 potensi pemulihan |
| Deliverable | Artefak v1 dengan metadata wajib (`profile_schema_version`, `learner_spec_version`, `corpus_snapshot`, tanggal latih, ringkasan coverage): meta-model, kalibrator, referensi OOD, laporan akurasi (MAE, coverage, Spearman per jenis korupsi, kondisi tidak andal); register klaim |
| Keputusan yang harus ditutup | **[T]** BR #2 validitas noise floor estimasi (H5); BR #3 ambang OOD tinggi dan pelebaran interval |
| Kriteria selesai | Hipotesis H1–H5 dilaporkan apa adanya, termasuk yang gagal; dataset uji LODO tidak dipakai melatih, men-tuning, atau mengkalibrasi (BR-81); versi profil dan versi artefak harus cocok, ketidakcocokan menghasilkan galat (AC-9); `ceteris scan` memuat artefak v1 tanpa melatih (AC-4); semua uji wajib AGENTS.md bagian 6 lulus |
| **Gerbang G3** | Lihat `product.md` 5.1 |

### Phase 5 — Validasi data kotor asli dan tinjauan H1

| | |
| --- | --- |
| Scope | E4 pada 3–5 pasangan data kotor-bersih nyata; uji konsistensi jalur akhir |
| Deliverable | Laporan validasi eksternal; pembaruan laporan akurasi; `ScanReport` `schema_version` 1.0 yang dibekukan untuk dikonsumsi produk |
| Kriteria selesai | Galat ≤ 2× MAE LODO pada pasangan nyata, atau hasil negatif dilaporkan apa adanya; jalur riset dan jalur scan konsisten (BR-16); klaim akurasi pada data nyata hanya tampil sesuai bukti |
| **Gerbang G4** | Lihat `product.md` 5.1 |
| **Tinjauan H1** | Bila H1 gagal, lakukan bagian 5.2 `product.md` (klaim diganti "indikasi risiko" tanpa angka) dan tinjau ulang urutan Sprint C–D sebelum melanjutkan |

---

## Sprint C — Platform R1

### Phase 6 — Keputusan pra-R1 dan backlog

| | |
| --- | --- |
| Scope | Menutup semua hal terbuka berbatas "Sebelum R1"; menulis backlog R1 |
| Deliverable | ADR untuk tiap keputusan di bawah (berurutan mulai 0005); user story F-L01–F-L05 beserta acceptance criteria dipindahkan dari draf Long-MVP ke backlog |
| Keputusan yang harus ditutup | **[T]** satu repository atau dipisah (arsitektur #1); penanganan cleanlab AGPL-3.0 (arsitektur #2, BR #10); versi hosted di R1 atau tidak (arsitektur #3); batas ukuran unggahan dan strategi sampling (arsitektur #5, BR #7); alias endpoint draf awal (arsitektur #6); model distribusi (product 7.2 #2) |
| Ketidaksesuaian dokumen | **[T]** F-L05 menyebut login di R1, sedangkan `architecture.md` bagian 2 menempatkan OIDC di R2. Tentukan mekanisme login R1 dan perbaiki dokumen yang keliru |
| Kriteria selesai | Tidak ada hal terbuka berbatas "Sebelum R1" yang tersisa; ADR tersimpan; dokumen yang terdampak diperbarui dalam satu tempat yang bertanggung jawab |

### Phase 7 — API, worker, dan model registry

| | |
| --- | --- |
| Scope | F-L01 REST API dan worker antrian, F-L04 model registry |
| Deliverable | FastAPI di bawah `/v1` (`POST /datasets`, `POST /scans`, `GET /scans/{id}`, `GET /scans/{id}/report`); worker yang membungkus `ceteris.scan`; Redis Queue; Postgres; object store S3-compatible; registry artefak dengan manifest; bentuk galat `{"error": {...}}`; Docker Compose |
| Kriteria selesai | `ScanReport` identik di CLI, Python API, dan REST (AC-5; uji konsistensi jalur SDK vs API); API, antrian, dan metadata store tidak menyimpan data mentah (AC-6); akses sumber data read-only (AC-7); worker hanya membaca registry (AC-4); contract test dan uji schemathesis lulus; artefak baru hanya dirilis bila tidak lebih buruk dari yang sebelumnya (BR-63, NFR-8); NFR-2 (p95 ≤ 300 ms untuk endpoint sinkron) dan NFR-9 (trace berkorelasi `scan_id`) terpenuhi |

### Phase 8 — Histori, login, dan self-host

| | |
| --- | --- |
| Scope | F-L03 histori dan perbandingan antar-scan, F-L05 login dan paket self-host |
| Deliverable | `GET /datasets/{id}/scans`; login sesuai keputusan Phase 6; paket self-host (Docker Compose, Helm chart bila diputuskan); pipeline CI dengan SAST, pemindaian dependensi dan lisensi (NFR-6) |
| Kriteria selesai | Uji beban: scan median ≤ 5 menit untuk 100.000 baris × 100 kolom (NFR-1); enkripsi dan TLS sesuai NFR-5; retensi sesuai NFR-7 bila hosted dibangun; kontrak API berversi (NFR-10, AC-10); perbandingan antar-scan hanya pada versi model yang sama dan scan lama tidak dihitung ulang otomatis (BR-61, BR-62) |
| **Gerbang G5** | Lihat `product.md` 5.3 |

---

## Sprint D — Web UI R1

### Phase 9 — Desain UI (dokumen saja)

| | |
| --- | --- |
| Scope | Desain F-L02 (unggah lewat web dan laporan HTML). **Tidak ada kode, instalasi, atau visual hi-fi.** |
| Deliverable | Dokumen desain UI di `docs/` (alur pengguna dari unggah sampai laporan; arsitektur informasi; wireframe low-fidelity; inventaris komponen shadcn/ui per layar sesuai ADR 0003; spesifikasi tiap grafik ECharts; keadaan kosong, memuat, galat, dan penolakan kontrak input; aturan tampil ketidakpastian dan status `tidak_yakin`; rencana aksesibilitas; rencana pengujian UI); ADR bila ada keputusan baru |
| Keputusan yang harus ditutup | **[T]** label status UI terhadap BR-50/BR-51 dan presisi ΔAUC, tanda, koma desimal, format tanggal (ADR 0003, pedoman 7 dan 8); apakah tampilan histori (F-L03) masuk UI R1; kalimat kondisi (BR-06) dan label eksperimental (BR-35) selalu menyertai angka |
| Kriteria selesai | Setiap layar punya daftar komponen dan keadaan; setiap grafik punya data masukan yang dipetakan ke field `ScanReport`; tidak ada kebutuhan UI yang menghitung status sendiri |
| **Gerbang G6** | Lihat `product.md` 5.3. **Tanpa G6, Phase 10 dan 11 tidak dimulai** |

### Phase 10 — Fondasi UI

| | |
| --- | --- |
| Scope | Kerangka aplikasi Next.js sesuai desain yang disetujui |
| Deliverable | Aplikasi Next.js; `components.json` dan shadcn/ui; tema dari token desain (mode terang dan gelap); pembungkus `<CeterisChart>` (tema dari CSS variable, resize, loading dan kosong, `aria` dan `decal`, impor modular); klien API dari OpenAPI; kerangka Playwright dan jalur CI |
| Kriteria selesai | Uji pembungkus grafik (tema berganti, resize saat sidebar dilipat, keadaan kosong); lint, tipe, dan build bersih; setiap komponen yang dipakai tercatat beserta alasannya (AGENTS.md butir 12); UI tidak menghitung status sendiri |

### Phase 11 — Implementasi F-L02 dan gerbang terakhir

| | |
| --- | --- |
| Scope | Halaman unggah, status scan, dan laporan; ekspor laporan HTML |
| Deliverable | Unggah dan polling status; laporan dengan tabel temuan (shadcn + TanStack Table), grafik ECharts sesuai spesifikasi, status berupa ikon dan teks, kalimat kondisi dan label eksperimental; penanganan penolakan kontrak input; ekspor HTML |
| Kriteria selesai | Alur unggah → laporan lulus uji Playwright; tampil benar mulai lebar 390 px; dapat dinavigasi dengan papan ketik; tidak ada angka tanpa interval dan kalimat kondisi (BR-06); keluaran sesuai `ScanReport` dengan label eksperimental bila berlaku (BR-35); kebijakan retensi data ditampilkan di layar unggah bila hosted dibangun (BR-72); tinjauan aksesibilitas dan tinjauan Critic selesai |
| **Gerbang G7 (terakhir)** | Lihat `product.md` 5.3. **Rencana ini berhenti di sini** |

---

## 4. Hal terbuka menurut phase

| Hal terbuka **[T]** | Ditutup di |
| --- | --- |
| Definisi kolom ID dan kebocoran target (BR #6); persetujuan RQ2b dan H5 | Sebelum Phase 2 (G1) |
| Statistik noise floor dan seed probe (BR #1); kuantil conformal (BR #4); pemotongan interval (BR #5); mesin komputasi (arsitektur #7) | Phase 3 (G2) |
| Validitas noise floor estimasi (BR #2); ambang OOD (BR #3) | Phase 4 (G3) |
| Repository tunggal atau dipisah; cleanlab; hosted; batas unggahan; alias endpoint; model distribusi; login R1 vs OIDC | Phase 6 |
| Label status UI, presisi angka, tampilan histori | Phase 9 (G6) |
| Perilaku gate saat layanan mati (`fail_mode`), keputusan gate untuk scan ditolak (BR #8), tabel effort (BR #9) | Di luar rencana ini (sebelum R2) |

## 5. Risiko urutan

| Risiko | Dampak | Mitigasi |
| --- | --- | --- |
| H1 gagal | Sprint C–D berubah isi | Tinjauan H1 di akhir Phase 5; klaim diganti "indikasi risiko" |
| Pasangan data kotor-bersih untuk E4 sulit didapat | G4 tertahan, menunda Sprint C | **[T]** pilihan: tetap berurutan, atau mulai Phase 6 setelah G3 dan jalankan E4 paralel. Rencana ini memakai urutan ketat |
| Estimasi kebanyakan `tidak_yakin` karena OOD | UI menampilkan terlalu banyak rentang tanpa titik | Ukur sejak Phase 5; perluas korpus bila perlu |
| Komputasi korpus penuh (62.000–72.000 fit LightGBM) melebihi mesin yang ada | Phase 4 tertahan | Putuskan mesin di Phase 3 |
| Desain UI disetujui terlambat | Sprint D tertahan | Phase 9 hanya berisi dokumen sehingga persetujuan bisa disiapkan sejak G5 tercapai; G6 tetap mendahului Phase 10 |
