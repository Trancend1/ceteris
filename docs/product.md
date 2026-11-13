# Produk Ceteris

Dokumen ini menjawab **apa** yang dibangun, **untuk siapa**, dan **dalam urutan apa**. Cara membangunnya ada di [architecture.md](architecture.md); aturan angka dan keputusan ada di [business-rules.md](business-rules.md); definisi istilah ada di [domain/glossary.md](domain/glossary.md).

Penanda status yang dipakai di semua dokumen: **[F]** fakta terverifikasi · **[K]** keputusan desain · **[T]** terbuka, belum diputuskan. Pernyataan tanpa penanda berstatus **[K]**. Tanggal ditulis DD/MM/YYYY.

**Status per 10/11/2026.** **[F]** Ceteris berada di tahap konsep: belum ada kode, artefak model, atau pengguna. Seluruh isi dokumen ini adalah rencana yang dikonsolidasikan dari draft proyek (Fondasi, Skripsi, Short-MVP, Long-MVP). Angka target adalah usulan awal, bukan hasil pengukuran.

## 1. Visi

> Platform *data quality intelligence* yang menilai setiap temuan kualitas data dari dampaknya pada model, metrik, dan bisnis, lalu memakai estimasi dampak itu untuk memprioritaskan, menahan, dan memberi sinyal kepercayaan.

Nama Ceteris diambil dari *ceteris paribus*: produk ini menjawab "jika semua hal lain sama, berapa kerugian yang disebabkan kekotoran data ini?".

Tiga hal membentuk produk:

1. **Inti: estimasi dampak.** Tools kualitas data menjawab "apa yang kotor". Ceteris menjawab "rugi berapa, dan seberapa yakin". Semua fitur lain memberi masukan ke estimasi itu atau memakainya.
2. **Kejujuran sebagai fitur.** Setiap estimasi membawa interval dan bisa berstatus *tidak yakin*. Ceteris lebih baik menjawab "tidak yakin" daripada memberi angka yang tidak didukung bukti ([BR-33](business-rules.md#4-status-hasil-scan), [BR-34](business-rules.md#4-status-hasil-scan)).
3. **Source-faithful advisory.** Ceteris menandai, mengukur, dan mengarantina. Ceteris tidak mengimputasi atau memperbaiki data secara diam-diam ([BR-70](business-rules.md#8-data-dan-privasi)).

## 2. Masalah dan pengguna

### 2.1 Masalah

| # | Masalah | Akibat |
| --- | --- | --- |
| M1 | Tools kualitas data melaporkan null, duplikat, dan rule gagal, tetapi tidak melaporkan konsekuensinya. | Temuan diurutkan menurut volume, bukan dampak. |
| M2 | Tim ML melatih ulang model secara berkala tanpa tahu apakah kekotoran data latih kali ini material. | Kerugian baru terlihat setelah model di produksi. |
| M3 | Di warehouse, konsumen data adalah angka yang dikutip (YoY, MoM, agregat). Selisih yang mengubah angka itu tenggelam di antara ratusan temuan struktural. | Tidak ada yang tahu tabel mana yang sedang tidak bisa dipercaya. |

### 2.2 Target pengguna

Pengguna pertama (*wedge*) adalah **P1, ML engineer**. Persona lain dilayani setelah mode *learned* terbukti dan gate dipakai.

| Persona | Pekerjaan | Yang dipakai sekarang | Yang diberikan Ceteris | Dilayani mulai |
| --- | --- | --- | --- | --- |
| **P1** ML engineer / pemilik model | Melatih ulang dan merilis model | Latih ulang lalu bandingkan AUC; Deepchecks, Cleanlab | Estimasi ΔAUC + interval sebelum melatih, status, gate CI | R0 (uji coba), R1 |
| **P2** Data engineer | Menjaga pipeline dan promosi tabel bronze → silver | Soda, Great Expectations, dbt tests | Temuan yang sama diurutkan menurut dampak; promotion gate; saran fix | R3 |
| **P3** Head of data / analytics lead | Memastikan angka yang dikutip bisa dipercaya | Dashboard monitoring | Health score sebagai roll-up dampak; dampak ke metrik bisnis | R4 |
| **P4** Konsumen data (dashboard, model, AI assistant) | Memakai tabel | — | Trust signal per tabel | R4 |

Pada R0 ada dua peran tambahan yang bukan persona pasar: **peneliti** (menjalankan eksperimen) dan **penguji** (pembimbing, penguji sidang, pengguna uji coba yang menjalankan `ceteris scan`).

## 3. Scope

### 3.1 Aturan scope

**Sebuah fitur masuk hanya bila menghasilkan atau mengonsumsi estimasi dampak.** Fitur yang tidak tersambung ke dampak boleh ada sebagai fondasi, tetapi tidak diposisikan sebagai pembeda. Untuk rilis R0 berlaku aturan yang lebih ketat: fitur masuk hanya bila diperlukan untuk menjawab minimal satu pertanyaan penelitian (RQ) atau menjalankan eksperimen.

### 3.2 Lapisan produk

| Lapisan | Peran terhadap estimasi dampak | Isi |
| --- | --- | --- |
| **Scan** | Masukan | Kontrak input, quality profile, temuan; impor temuan Soda/GX; konektor |
| **Impact Engine** | Inti | Mode *learned* (ΔAUC), *exact* (Δ metrik bisnis), *cost* (rupiah); interval; skor OOD; status |
| **Control** | Konsumen | Prioritas, simulator, gate CI, promotion gate, quarantine, saran fix |
| **Trust** | Konsumen + umpan balik | Data contract, trust signal, health score, akurasi lapangan |
| **Translate** | Konsumen | Dampak dalam rupiah untuk percakapan dengan bisnis |

### 3.3 Yang dibuktikan dan yang belum

Skripsi membuktikan **hanya mode *learned***: ΔAUC pada data tabular klasifikasi bisa ditaksir dari quality profile untuk dataset yang belum pernah dilihat, dengan interval terkalibrasi. Mode *exact* dan *cost* tidak bergantung pada skripsi dan divalidasi lewat jalur sendiri. Produk hanya menampilkan klaim yang buktinya sudah ada ([BR-64](business-rules.md#7-versi-histori-dan-klaim)).

### 3.4 Di luar scope

| Hal | Alasan |
| --- | --- |
| Menggantikan profiling, validasi rule, atau deteksi anomali (Soda, Great Expectations, Evidently, Cleanlab) | Bukan inti; Ceteris membaca hasil tools itu |
| ΔF1, regresi, learner acuan selain LightGBM | Butuh riset tersendiri setara skripsi |
| Data time series dan teks | Di luar korpus yang divalidasi |
| Auto-apply fix sebagai default | Bertentangan dengan source-faithful advisory |
| Penjelasan temuan berbasis LLM | Butuh evaluasi tersendiri |
| Klaim "pertama" dalam pesan produk | Kebaruan dibatasi: data latih, dataset baru, sebelum model ada, interval per dataset |

## 4. Feature index

Setiap fitur dipetakan ke kebutuhan (persona, RQ, atau user story), ke komponen di [architecture.md](architecture.md#4-komponen-paket-ceteris), dan ke aturan di [business-rules.md](business-rules.md). ID `F-S` adalah fitur rilis R0; `F-L` adalah fitur R1–R5. Fitur `F-S` tetap dipakai di rilis sesudahnya tanpa perubahan perilaku.

### 4.1 R0 — bukti mode learned (Short-MVP)

| ID | Fitur | Lapisan | Kebutuhan | Komponen | Aturan |
| --- | --- | --- | --- | --- | --- |
| F-S01 | Loader korpus dan split | Riset | RQ1–RQ3 | `ceteris.corpus` | BR-80 |
| F-S02 | Corruption engine | Riset | RQ1–RQ3 | `ceteris.corrupt` | BR-80, BR-82, BR-83 |
| F-S03 | Training harness learner acuan | Riset | Semua RQ | `ceteris.train` | BR-01, BR-03 |
| F-S04 | `dqprofile` v1 + praproses kontrak input | Scan | Semua RQ; M1 | `ceteris.dqprofile` | BR-10–BR-17, BR-20 |
| F-S05 | Estimator label noise | Scan | Semua RQ | `ceteris.dqprofile` | BR-12 |
| F-S06 | Noise floor terukur dan estimasi | Impact Engine | RQ3 (H5) | `ceteris.dqprofile`, `ceteris.train` | BR-04, BR-05 |
| F-S07 | Run store dan experiment registry | Riset | Reprodusibilitas | `ceteris.store` | BR-84, BR-86 |
| F-S08 | Meta-model trainer | Impact Engine | RQ1 | `ceteris.metamodel` | BR-21, BR-23 |
| F-S09 | Baseline (a)–(d) | Riset | RQ1 | `ceteris.metamodel` | BR-85 |
| F-S10 | Kalibrator conformal dan skor OOD | Impact Engine | RQ3 | `ceteris.uncertainty` | BR-22, BR-24 |
| F-S11 | Evaluator LODO bersarang | Riset | RQ1–RQ3 | `ceteris.evaluate` | BR-81, BR-85 |
| F-S12 | Potensi pemulihan per temuan | Control | RQ2b; M1 | `ceteris.recovery` | BR-40–BR-43 |
| F-S13 | `ceteris scan` (CLI dan Python API) | Scan | RQ4; P1 | `ceteris.scan` | BR-06, BR-60 |
| F-S14 | Status hasil | Impact Engine | RQ3, RQ4; M2 | `ceteris.scan` | BR-30–BR-35 |

### 4.2 R1–R5 — produk (Long-MVP)

| ID | Fitur | Lapisan | Kebutuhan | Komponen | Aturan | Rilis |
| --- | --- | --- | --- | --- | --- | --- |
| F-L01 | REST API dan worker antrian | Platform | P1 · US1.1, US1.4 | API, antrian, worker | BR-60 | R1 |
| F-L02 | Laporan HTML dan unggah lewat web | Scan | P1 · US1.2, US1.3 | Web UI, reporter | BR-06, BR-35, BR-72 | R1 |
| F-L03 | Histori dan perbandingan antar-scan | Impact Engine | P1 · US2.1 | API, metadata store | BR-61, BR-62 | R1 |
| F-L04 | Model registry dan versi model | Impact Engine | US2.2 | Model registry | BR-23, BR-63 | R1 |
| F-L05 | Login dan paket self-host | Platform | US8.1, US8.3 | API, deployment | BR-71 | R1 |
| F-L06 | Gate CI, kebijakan per dataset, notifikasi | Control | P1 · US3.1–US3.3; M2 | API (gate), worker | BR-50–BR-54 | R2 |
| F-L07 | Simulator what-if | Control | P1 · US4.1 | API, Impact Engine | BR-44 | R2 |
| F-L08 | Prioritizer (potensi pemulihan / effort) | Control | P2 · US4.2; M1 | `ceteris.recovery` + tabel effort | BR-41–BR-43 | R2 |
| F-L09 | RBAC dan audit log; multi-tenant menyusul di R3 | Platform | US8.1, US8.2 | API, metadata store | BR-54 | R2–R3 |
| F-L10 | Konektor warehouse/lake dan impor temuan Soda/GX | Scan | P2 · US5.1, US5.2 | Adapter worker | BR-70 | R3 |
| F-L11 | Promotion gate, quarantine, saran fix SQL/dbt | Control | P2 · US5.3, US5.4 | API (gate), worker | BR-53 | R3 |
| F-L12 | Mode exact (dampak ke metrik bisnis) | Impact Engine | P3 · US7.1; M3 | Exact engine | BR-64 | R4 |
| F-L13 | Trust signal, health score, data contract | Trust | P3, P4 · US6.1, US6.3, US6.4; M3 | API, metadata store | BR-64 | R4 |
| F-L14 | Umpan balik akurasi lapangan | Trust | US6.2 | API, metadata store | BR-64, BR-73 | R4 |
| F-L15 | Mode cost (rupiah) | Translate | P3 · US7.2 | Cost model | BR-64 | R5 |

User story `US x.y` dan acceptance criteria-nya dirinci di draft Long-MVP dan dipindahkan ke backlog saat rilis terkait dimulai.

## 5. Prioritas: Now / Next / Later

Roadmap **tidak memakai tanggal**. Sebuah rilis selesai ketika kriteria keluarnya terpenuhi.

| Horizon | Rilis | Tujuan | Fitur | Kriteria keluar |
| --- | --- | --- | --- | --- |
| **Now** | R0 | Bukti ilmiah mode learned | F-S01–F-S14 | Artefak model v1 dirilis (G3); validasi eksternal dan uji konsistensi jalur lulus (G4) |
| **Next** | R1 Scan untuk tim | Tim ML memakai scan tanpa peneliti | F-L01–F-L05 | 5 ML engineer menjalankan scan pada data sendiri; NFR-1, NFR-5, NFR-7, NFR-10 terpenuhi |
| **Next** | R2 Gate | Scan menjadi keputusan di pipeline | F-L06–F-L09 | Gate dipakai di ≥ 2 pipeline nyata; tidak ada block keliru yang tidak terjelaskan |
| **Later** | R3 Kontrol | Data engineer terlayani | F-L10, F-L11, multi-tenant | 1 design partner warehouse memakai promotion gate |
| **Later** | R4 Trust dan exact | Dampak per tabel dan per metrik bisnis | F-L12–F-L14 | Mode exact divalidasi bersama design partner; dashboard akurasi lapangan aktif |
| **Later** | R5 Translate | Dampak dalam rupiah | F-L15 | Cost model dipakai ≥ 1 tim |

### 5.1 Urutan kerja di dalam Now

R0 berjalan lewat empat gerbang. Gerbang adalah titik di mana artefak dibekukan atau klaim dibuka.

| Gerbang | Yang dibekukan atau dibuka | Akibat bagi produk |
| --- | --- | --- |
| **G1** | Skema `dqprofile` v1 dan spesifikasi learner acuan dibekukan | Kode profil bisa dipakai jalur scan |
| **G2** | Pilot (E0) lolos; rencana analisis dibekukan; meta-model pilot tersedia | Scan berjalan dengan label *eksperimental* |
| **G3** | Meta-model v1, kalibrator, referensi OOD, laporan akurasi | Klaim angka dan interval boleh tampil; gate boleh *block* |
| **G4** | Validasi pada data kotor asli (E4) | Klaim akurasi pada data nyata boleh tampil |

### 5.2 Jika bukti tidak mendukung

Hasil negatif diterima. Jika hipotesis akurasi (H1) gagal, klaim "ΔAUC diperkirakan X ± Y" diganti menjadi "indikasi risiko" tanpa angka, dan baseline dose–response dipertimbangkan sebagai mekanisme estimasi yang lebih lambat. Urutan Next dan Later ditinjau ulang sebelum R1 dimulai.

Jika hipotesis coverage (H3) gagal, interval dan status tetap tampil dengan label eksperimental, dan gate tidak memberi **block** (BR-51). Perbaikan interval diuji di epoch 1 dengan protokol tertulis lebih dulu, dan klaim interval dibuka paling cepat setelah validasi pada dataset holdout. Ini berlaku sejak G3 karena H3 gagal di E1 ([ADR 0012](decisions/0012-phase-4-dan-gate-g3.md), [ADR 0013](decisions/0013-epoch-eksperimen-dan-pelestarian.md)).

### 5.3 Gerbang R1 hingga Web UI

**[K]** Disetujui pemilik repo pada 10/11/2026. Urutan phase dan kriteria selesainya ada di [execution-plan.md](execution-plan.md); rencana itu berhenti di G7.

| Gerbang | Yang dibekukan atau dibuka | Akibat bagi produk |
| --- | --- | --- |
| **G5** | Platform R1 siap: OpenAPI `/v1` dibekukan, API lolos uji kontrak, self-host berjalan dari repositori bersih | UI boleh mengonsumsi API |
| **G6** | Dokumen desain UI disetujui tertulis oleh pemilik repo | Kode UI dan implementasi visual boleh dimulai; sebelumnya dilarang |
| **G7** | Web UI R1 (F-L02) selesai dan tervalidasi | Gerbang terakhir rencana eksekusi; R2 dan seterusnya di luar rencana |

## 6. Success metrics

### 6.1 R0 — kriteria bukti

Target di bawah adalah kriteria hipotesis skripsi; rinciannya ada di rencana analisis yang dibekukan di G2.

| Ukuran | Target | Hipotesis |
| --- | --- | --- |
| MAE estimasi ΔAUC per dataset | Lebih rendah dari baseline (a) rata-rata, (b) skor gabungan, (c) meta-fitur saja | H1a |
| Dibanding baseline (d) dose–response | Tidak lebih buruk dari margin 0,005 MAE, dengan biaya komputasi ≥ 10× lebih murah | H1b |
| Urutan dampak per jenis korupsi | Label noise paling merusak, MCAR paling ringan, pada proporsi baris terdampak yang sama | H2 |
| Urutan temuan | Kendall τ antara urutan temuan dan keuntungan AUC nyata per jenis korupsi lebih tinggi untuk urutan potensi pemulihan daripada urutan volume (Wilcoxon berpasangan antar dataset); eksploratif | H2b **[K]** |
| Coverage interval 90% | 85–95% pada ≥ 80% dataset | H3 |
| Skor OOD | Berkorelasi positif dengan galat estimasi | H4 |
| Noise floor estimasi | Selisih median dengan noise floor terukur ≤ 0,005; kappa status ≥ 0,6, dilaporkan untuk seluruh dataset dan subset dengan noise floor dekat 0,01; bias dilaporkan; fallback `T` = 0,01 bila gagal ([ADR 0006](decisions/0006-kerangka-pengujian-rq2b-dan-h5.md)) | H5 **[K]** |
| Data kotor asli | Galat ≤ 2× MAE LODO pada 3–5 pasangan kotor-bersih; jalur riset dan jalur scan konsisten | RQ4 (eksploratif) |

### 6.2 R1 dan sesudahnya — KPI produk

| KPI | Definisi | Target awal | Mulai diukur |
| --- | --- | --- | --- |
| **North star: keputusan yang berubah** | % scan yang menurut pengguna mengubah keputusan (pertanyaan satu klik di laporan) | ≥ 30% | R1 |
| Aktivasi | % pengguna baru yang menyelesaikan scan pertama pada data sendiri | ≥ 60% | R1 |
| Pemakaian berulang | % pengguna dengan ≥ 3 scan pada dataset yang sama dalam 30 hari | ≥ 40% | R1 |
| Tingkat OOD | % scan berstatus tidak yakin karena OOD | < 30% | R1 |
| Tingkat penolakan input | % scan ditolak kontrak input | < 15% | R1 |
| Waktu ke laporan | Median durasi scan 100.000 baris | ≤ 5 menit | R1 |
| Adopsi gate | Jumlah pipeline aktif yang memanggil gate | ≥ 2 di R2 | R2 |
| Ketepatan gate | % block yang dikonfirmasi pengguna sebagai benar | ≥ 80% | R2 |
| Ketersediaan | Uptime API dan gate (hosted) | ≥ 99,5% | R2 |
| Akurasi lapangan | Selisih prediksi dengan hasil aktual yang dilaporkan | Sebanding dengan MAE LODO | R4 |

Tingkat OOD adalah KPI yang paling menentukan nilai produk: bila sebagian besar scan nyata berstatus tidak yakin, estimasi yang jujur tetap tidak berguna. Karena itu ia diukur sejak R1 dan menentukan apakah korpus perlu diperluas.

## 7. Risiko dan hal terbuka

### 7.1 Risiko utama

| Risiko | Mitigasi |
| --- | --- |
| H1 gagal; angka ΔAUC tidak bisa diklaim | Fallback di bagian 5.2 |
| Sebagian besar scan nyata berstatus tidak yakin karena OOD | Ukur sejak R1; perluas korpus ke data besar dan bertimestamp |
| Gate memblokir secara keliru sehingga tim mematikannya | Block hanya sesudah G3; default warn; alasan selalu disertakan |
| Kewajiban lisensi AGPL cleanlab: tidak berlaku untuk versi ≥ 2.8.0, yang berlisensi Apache-2.0 sejak 08/01/2026 **[F]** | Versi dikunci `>=2.8.0,<3` ([ADR 0009](decisions/0009-paket-keputusan-g1.md)) |
| Kompetitor menambah estimasi dampak | Laporan akurasi terbuka; fokus pada interval yang jujur |

### 7.2 Hal terbuka

| # | Hal terbuka **[T]** | Diputuskan paling lambat |
| --- | --- | --- |
| 1 | Model distribusi: open-core, self-host berlisensi, atau keduanya | Sebelum R1 |
| 2 | **Ditutup [K]**: estimator label noise memakai cleanlab `>=2.8.0,<3` ([ADR 0009](decisions/0009-paket-keputusan-g1.md)) | — |
| 3 | Apakah R1 memerlukan versi hosted | Sebelum R1 |
| 4 | Design partner warehouse untuk R3–R4 | Pencarian dimulai saat R1 |
| 5 | Tabel effort per jenis temuan: ditetapkan tim atau dipelajari dari umpan balik | Sebelum R2 |
| 6 | Laporan HTML untuk demo sidang (diambil dari F-L02 setelah G4, bukan dibangun di R0) | G4 |

Hal terbuka yang menyangkut aturan angka ada di [business-rules.md](business-rules.md#11-daftar-hal-terbuka); yang menyangkut teknis ada di [architecture.md](architecture.md#11-hal-terbuka).
