# Desain Web UI R1 (F-L02)

- **Status:** Draf Phase 9, **belum disetujui (G6)**. Tidak ada kode UI, instalasi, atau visual hi-fi sebelum G6 (`execution-plan.md` prinsip 3).
- **Tanggal:** 15/11/2026
- **Scope:** F-L02 (unggah lewat web dan laporan HTML; US1.2, US1.3), ditambah layar masuk (F-L05, US8.1) dan daftar scan sederhana (bagian dari F-L03, keputusan K-3 di bawah).
- **Rujukan:** [execution-plan.md](../execution-plan.md) Phase 9; [backlog/r1.md](../backlog/r1.md); [ADR 0003](../decisions/0003-web-ui-shadcn.md); [ADR 0021](../decisions/0021-figma-manual-menggantikan-figcraft.md); kontrak `tests/contracts/scan_report_1.0.schema.json` dan `tests/contracts/openapi_v1.json`.

Dokumen ini adalah sumber kebenaran desain UI. Wireframe di `exports/` hanya lampiran. Aturan angka dan status tetap di `business-rules.md`; dokumen ini hanya mengatur cara menampilkannya.

## 1. Keputusan yang ditutup di Phase 9

Diputuskan pemilik repo pada 15/11/2026.

| # | Keputusan **[K]** | Menutup |
| --- | --- | --- |
| K-1 | UI R1 hanya menampilkan **status scan** dari `ScanReport.status.value`. Label gate (Lolos, Ditahan) tidak ada di R1 dan diputuskan bersama F-L06 di R2, sehingga tidak ada pemetaan ke `allow`/`warn`/`block` (BR-50, BR-51) di UI R1. | ADR 0003 pedoman 7 |
| K-2 | ΔAUC tampil **tiga desimal dengan tanda eksplisit dan koma desimal**; tanggal DD/MM/YYYY; antarmuka R1 hanya berbahasa Indonesia. Rincian di bagian 6. | ADR 0003 pedoman 8 |
| K-3 | Histori masuk UI R1 sebagai **daftar scan sederhana** per dataset. Grafik tren dan perbandingan antar-scan (BR-62) tidak masuk UI R1. | Hal terbuka "tampilan histori" |

Label status di UI (K-1):

| `status.value` | Label | Ikon (lucide) | Gaya `Badge` |
| --- | --- | --- | --- |
| `material` | Material | `triangle-alert` | `destructive` |
| `tidak_material` | Tidak material | `circle-check` | `secondary` |
| `tidak_yakin` | Tidak yakin | `circle-help` | `outline`, garis putus-putus |

Status tidak pernah dibedakan hanya dengan warna: ikon dan teks selalu tampil bersama (ADR 0003 pedoman 6).

## 2. Alur pengguna

```text
00 Masuk ──► 01 Unggah ──► 02 Status scan ──► 03 Laporan ──► 04 Daftar scan
                 ▲              │ failed            │              │
                 └──────────────┘                   └──────────────┘
                 (penolakan kontrak input           (buka laporan lain
                  atau galat: ulangi unggah)         dari dataset yang sama)
```

1. Pengguna masuk dengan akun lokal (`POST /v1/auth/login`).
2. Di layar unggah, pengguna memilih berkas CSV atau Parquet, mengisi nama dataset dan kolom target, lalu memulai scan (`POST /v1/datasets`, lalu `POST /v1/scans`).
3. Layar status melakukan polling `GET /v1/scans/{id}` sampai `done` atau `failed`.
4. Saat `done`, laporan terbuka (`GET /v1/scans/{id}/report`). Saat `failed`, alasan ditampilkan dan pengguna bisa kembali ke unggah.
5. Dari laporan, pengguna bisa membuka daftar scan dataset yang sama (`GET /v1/datasets/{id}/scans`) atau mengekspor HTML (`?format=html`).

## 3. Arsitektur informasi

| Rute | Layar | Sumber data |
| --- | --- | --- |
| `/masuk` | 00 Masuk | `POST /v1/auth/login` |
| `/` | 01 Unggah (halaman awal setelah masuk) | `POST /v1/datasets`, `POST /v1/scans` |
| `/scan/{scan_id}` | 02 Status scan, lalu 03 Laporan saat `done` | `GET /v1/scans/{id}`, `GET /v1/scans/{id}/report` |
| `/dataset/{dataset_id}` | 04 Daftar scan | `GET /v1/datasets/{id}/scans` |

Lebar minimum 390 px; di bawah 768 px sidebar menjadi `Sheet` (perilaku bawaan komponen `sidebar`) dan tabel berubah menjadi kartu bertumpuk.

### 3.1 Template shadcn yang menjadi dasar **[K]**

Arahan pemilik repo 15/11/2026: desain mengikuti template (block) resmi shadcn/ui, lalu disesuaikan dengan Ceteris. Block diperiksa di registry `@shadcn` (gaya `new-york-v4`) lewat MCP shadcn.

| Layar | Block dasar | Bagian block yang dipakai |
| --- | --- | --- |
| 00 Masuk | `login-03` | Latar `bg-muted`, merek di atas kartu, `Card` dengan `CardHeader` rata tengah, `FieldGroup` |
| 01–04 | `dashboard-01` | `SidebarProvider`, `AppSidebar variant="inset"`, `SidebarInset`, `SiteHeader`, `SectionCards`, kartu grafik, `DataTable` |

Kerangka aplikasi (dari `dashboard-01`):

- **Sidebar** (`inset`, bisa dilipat): `SidebarHeader` berisi merek; `NavMain` dengan tombol utama "Scan baru" (menggantikan "Quick Create") dan butir "Laporan scan" serta "Daftar scan"; `NavSecondary` berisi "Dokumentasi"; `SidebarFooter` berisi `NavUser` (email dari `GET /v1/me`, menu "Keluar").
- **SiteHeader**: `SidebarTrigger`, `Separator`, judul halaman, dan aksi halaman di kanan.
- **Isi**: kolom `gap-6` dengan urutan pita, `SectionCards`, kartu grafik, lalu `Tabs` dan `DataTable`.

Penyesuaian terhadap block (yang dibuang atau diganti):

| Bagian block | Perlakuan di Ceteris | Alasan |
| --- | --- | --- |
| `ChartAreaInteractive` dan komponen `chart` (Recharts) | Diganti kartu grafik berisi `<CeterisChart>` (ECharts) | ADR 0003: komponen `chart` shadcn tidak dipakai |
| Seret-lepas baris (`@dnd-kit`), `Checkbox` pilih baris, "Customize columns", "Add section", `Drawer` rincian baris | Dibuang | Urutan temuan dari API tidak boleh diubah (BR-43); UI hanya menampilkan |
| Pengurutan kolom `DataTable` | Dimatikan di tabel temuan | BR-43 |
| Pagination `DataTable` | Dipakai di daftar scan; tidak dipakai di tabel temuan (paling banyak lima baris) | Jumlah baris |
| Lencana tren dan teks "Trending up" di `SectionCards` | Diganti `Badge` status dan flag OOD; kaki kartu memuat interval dan kalimat kondisi | Tidak ada klaim tren di R1 (K-3); BR-06, BR-65 |
| `NavDocuments`, tombol kotak masuk, tautan GitHub | Dibuang | Tidak ada padanan fitur di R1 |
| Tombol masuk Apple/Google, `FieldSeparator`, tautan daftar, "Forgot password" di `login-03` | Dibuang | R1 hanya akun lokal buatan operator; OIDC di R2 (ADR 0016 K4) |
| Ikon `@tabler/icons-react` | **[T]** usulan: diganti `lucide-react` (pustaka ikon bawaan shadcn) | Menghindari dependensi ikon kedua |
| `Tabs` di atas tabel | Dipakai: "Temuan", "Peringatan input" (dengan lencana jumlah), "Keterangan model" | Pola block yang sama; lencana jumlah menjaga peringatan tetap terlihat |

Block untuk grafik (`chart-*`) tidak dipakai sama sekali (ADR 0003). Tidak ada block resmi untuk unggah berkas atau status proses; layar 01 dan 02 memakai kerangka `dashboard-01` dengan `Card` dan `FieldGroup` seperti pola formulir di `login-03`.

## 4. Layar

Setiap layar memuat daftar komponen shadcn/ui (dengan alasan) dan keadaannya. Wireframe: `exports/<nama>.png` dan `.svg`.

### 4.1 `00-masuk`

| Komponen shadcn/ui | Dipakai untuk | Alasan |
| --- | --- | --- |
| `Card` (`CardHeader` rata tengah, `CardContent`) | Wadah formulir di tengah layar berlatar `bg-muted` | Struktur block `login-03` |
| `Field`, `Input`, `Label` | Email dan kata sandi | Formulir standar dengan pesan galat per bidang |
| `Button` | Masuk | Aksi utama tunggal |
| `Alert` | Galat kredensial | Pesan harus terbaca pembaca layar (`role="alert"`) |

| Keadaan | Tampilan |
| --- | --- |
| Awal | Formulir kosong, fokus di email |
| Memuat | Tombol nonaktif dengan `Spinner` |
| Galat 401 | `Alert` "Email atau kata sandi salah"; tidak menyebut mana yang salah |
| Layanan tidak tersedia | `Alert` dengan saran memeriksa instans self-host |

### 4.2 `01-unggah`

| Komponen shadcn/ui | Dipakai untuk | Alasan |
| --- | --- | --- |
| `Card` | Wadah formulir unggah | Konsisten dengan layar masuk |
| `Input` (`type="file"`) di dalam area tarik-lepas | Memilih berkas | shadcn/ui tidak punya dropzone; area tarik-lepas hanya pembungkus bergaris putus-putus di sekitar `Input`, bukan komponen baru |
| `Field`, `Input`, `Label` | Nama dataset dan kolom target | Kolom target diketik karena API tidak membaca header berkas sebelum scan |
| `Alert` | Batas berkas, penolakan kontrak input, galat | Alasan penolakan wajib tampil, bukan galat generik (BR-10, BR-11) |
| `Progress` | Kemajuan unggah | Berkas bisa sampai 500 MB |
| `Button` | Mulai scan | Aksi utama |

| Keadaan | Tampilan |
| --- | --- |
| Kosong | Area tarik-lepas dengan teks "CSV atau Parquet, sampai 500 MB"; tombol nonaktif |
| Berkas dipilih | Nama dan ukuran berkas; bidang nama dataset terisi dari nama berkas |
| Berkas > 500 MB | `Alert`: berkas ditolak, dengan saran memakai SDK atau CLI (ADR 0016 K5). Pemeriksaan ukuran di klien hanya kemudahan; server tetap penentu (413) |
| Mengunggah | `Progress` dan tombol batal |
| Ditolak kontrak input | `Alert` berjudul "Data ditolak kontrak input" dengan daftar alasan dari `error.details`, satu baris per alasan (misalnya `too_many_rows`, `class_too_small`), beserta kode BR. Tidak ada estimasi parsial |
| Galat lain | `Alert` dengan `error.message` dan tombol coba lagi |

Teks alasan penolakan adalah terjemahan kode dari API; UI tidak menilai sendiri apakah data memenuhi kontrak.

### 4.3 `02-status-scan`

| Komponen shadcn/ui | Dipakai untuk | Alasan |
| --- | --- | --- |
| `Card` | Ringkasan scan (ID, waktu dibuat) | Wadah tunggal |
| `Badge` | Status `queued`, `running`, `done`, `failed` | Status singkat berupa ikon dan teks |
| `Spinner` | Menandai proses berjalan | API tidak memberi persentase; tidak ada `Progress` palsu |
| `Skeleton` | Bayangan tata letak laporan | Mengurangi lompatan saat laporan terbuka |
| `Alert` | Galat `failed` | Menampilkan `ScanOut.error` |

| Keadaan | Tampilan |
| --- | --- |
| `queued` | "Menunggu giliran" |
| `running` | "Sedang dipindai" dengan waktu berjalan sejak `started_at` |
| `done` | Beralih otomatis ke laporan di rute yang sama |
| `failed` | `Alert` dengan kode dan pesan galat; tautan "Scan baru". Versi profil tidak cocok (BR-23) tampil sebagai galat eksplisit |
| Scan tidak ditemukan (404) | `Empty` dengan tautan ke unggah |

Perubahan status diumumkan lewat `aria-live="polite"`.

### 4.4 `03-laporan`

Urutan blok mengikuti `dashboard-01`:

1. **Aksi di `SiteHeader`**: "Daftar scan" (`Button` ghost) dan "Ekspor HTML" (`Button` outline).
2. **Pita eksperimental** (`Alert`), tampil selama `model.experimental = true` (BR-35): "Eksperimental: interval dan status belum dibuka sebagai klaim" (KL-02, KL-04).
3. **`SectionCards`**, empat kartu:

   | Kartu | Judul kartu | Lencana | Kaki kartu | Field |
   | --- | --- | --- | --- | --- |
   | ΔAUC | Estimasi titik; untuk `tidak_yakin` rentang "lo s.d. hi" tanpa titik | `Badge` status | Interval 90% dan **kalimat kondisi** (BR-06) | `estimate.delta`, `estimate.interval_90`, `condition`, `status.value` |
   | Status | Label status | — | Alasan status | `status.value`, `status.reasons` |
   | Ambang T | Nilai ambang | — | Noise floor estimasi | `status.threshold`, `status.noise_floor_estimated` |
   | Distribusi korpus | "Di dalam" atau "Di luar" | `Badge` flag OOD | Berlaku tidaknya klaim interval 90% (BR-65) | `status.reasons` (`ood_high`) |

   ΔAUC relatif (`estimate.delta_relative`) tampil di kaki kartu ΔAUC bila tidak `null` dan status bukan `tidak_yakin`.
4. **Kartu grafik G1** (menggantikan `ChartAreaInteractive`; bagian 5).
5. **`Tabs` dan `DataTable`**: tab "Temuan" (tabel temuan), "Peringatan input" (satu `Alert` per butir `input_warnings`, dengan lencana jumlah di tab), dan "Keterangan model" (`model.version`, `model.profile_schema_version`, `schema_version`, `scan_id`).

Bila `status.reasons` memuat `target_leakage`, `Alert` kebocoran target tampil di bawah pita eksperimental, di luar tab, agar tidak terlewat.

| Komponen shadcn/ui | Dipakai untuk | Alasan |
| --- | --- | --- |
| `Sidebar`, `Separator`, `DropdownMenu`, `Avatar`, `Sheet` | Kerangka `dashboard-01` (semua layar 01–04) | Kerangka block dipakai utuh agar perilaku lipat dan seluler tidak dibuat sendiri |
| `Alert` | Pita eksperimental, peringatan input | Informasi yang tidak boleh terlewat |
| `Card` (`CardHeader`, `CardDescription`, `CardTitle`, `CardAction`, `CardFooter`) | `SectionCards` dan kartu grafik | Pola block; angka utama dan kalimat kondisi dalam satu kartu agar tidak terpisah |
| `Badge` | Status, flag OOD, "diamati" atau "diestimasi" | Label singkat berupa ikon dan teks |
| `Tabs` | Temuan, peringatan input, keterangan model | Pola block di atas `DataTable` |
| `Table` (+ TanStack Table) | Tabel temuan | ADR 0003: tabel adalah tampilan utama |
| `Tooltip` | Penjelasan istilah (ΔAUC, OOD, potensi pemulihan ideal) | Definisi dari glosarium tanpa memenuhi layar |
| `Button` | Ekspor HTML, daftar scan | Aksi sekunder di `SiteHeader` |
| `Empty` | Tidak ada temuan | Keadaan kosong yang jelas |
| `Skeleton` | Memuat laporan | Tata letak stabil |

Tabel temuan, satu baris per `Finding`:

| Kolom | Field `ScanReport` | Catatan |
| --- | --- | --- |
| Jenis temuan | `findings[].issue_type` | Label Indonesia untuk `missing`, `label_noise`, `duplicate_conflict`, `outlier`, `duplicate_exact` |
| Baris terdampak | `findings[].rows_affected_pct` | Persen satu desimal |
| Sumber | `findings[].observed_or_estimated` | `Badge` "Diamati" atau "Diestimasi" |
| Potensi pemulihan ideal | `findings[].recovery_potential` | Judul kolom persis demikian (BR-41). `null` tampil sebagai "—" dengan `Tooltip` "tidak ditampilkan (BR-45)" |

- Urutan baris mengikuti urutan array dari API. Tabel **tidak bisa diurutkan ulang** oleh pengguna dan UI tidak mengurutkan sendiri (BR-43).
- Tidak ada baris total dan tidak ada persentase terhadap ΔAUC (BR-42).
- Kalimat "naik X jika diperbaiki" tidak dipakai (BR-41).
- `findings[].column` selalu `null` di skema 1.0 **[F]** (`ceteris/scan.py`), sehingga kolom "Kolom" tidak ditampilkan.

| Keadaan | Tampilan |
| --- | --- |
| Memuat | `Skeleton` untuk ringkasan, grafik, dan tabel |
| `tidak_yakin` | Titik estimasi tidak digambar di G1; hanya rentang interval bergaris putus-putus. Judul kartu ΔAUC diganti rentang "lo s.d. hi" |
| OOD tinggi (`ood_high` di `status.reasons`) | Kartu "Distribusi korpus" menampilkan "Di luar" dengan `Badge` "OOD tinggi" (BR-65) dan penjelasan bahwa klaim interval 90% tidak berlaku |
| Kebocoran target (`target_leakage` di `status.reasons`) | `Alert` menyebut fitur dari `input_warnings` |
| Tanpa temuan | `Empty`: "Tidak ada temuan yang dilaporkan" |
| Galat memuat | `Alert` dengan tombol muat ulang |

Flag OOD dibaca dari `status.reasons`; UI tidak membandingkan `ood_score` dengan ambang apa pun.

### 4.5 `04-daftar-scan`

| Komponen shadcn/ui | Dipakai untuk | Alasan |
| --- | --- | --- |
| `Table` (+ TanStack Table) | Daftar scan | Pola yang sama dengan tabel temuan |
| `Badge` | Status eksekusi dan status scan | Konsisten dengan laporan |
| `Button` | Scan baru | Aksi utama |
| `Button` (ikon, outline) | Pagination `DataTable` seperti di `dashboard-01` | Daftar scan bisa panjang |
| `Empty` | Belum ada scan | Mengarahkan ke unggah |
| `Skeleton` | Memuat | Tata letak stabil |

Kolom, satu baris per `ScanSummary`: tanggal (`created_at`), status eksekusi (`status`), status scan (`status_value`), ΔAUC dan interval (`delta`, `interval_90`) dengan grafik G2 di baris, dan versi model (`model_version`). Baris yang `done` menaut ke laporannya.

- Versi model tampil di setiap baris, dan baris dengan versi berbeda tidak dibandingkan secara visual (BR-61, BR-62). Field `comparison` dari API tidak ditampilkan di R1 (K-3).
- Kalimat kondisi tampil sekali di atas tabel dan berlaku untuk semua angka ΔAUC di layar ini (BR-06). Pita eksperimental tampil bila ada baris dari model eksperimental; lihat hal terbuka T-4.

## 5. Spesifikasi grafik (ECharts lewat `<CeterisChart>`)

Hanya dua grafik di R1. Heatmap kolom × jenis temuan, histogram profil, reliability diagram, dan tren ΔAUC tidak dibuat karena datanya tidak ada di `ScanReport` 1.0 atau di luar K-3.

### G1 — Interval ΔAUC terhadap ambang (layar 03)

| Aspek | Spesifikasi |
| --- | --- |
| Tipe | `custom` series (titik dan whisker horizontal, satu baris), `markLine` vertikal untuk ambang |
| Sumbu x | ΔAUC; rentang mencakup `interval_90`, `threshold`, dan 0 |
| Whisker | `estimate.interval_90[0]` sampai `estimate.interval_90[1]` |
| Titik | `estimate.delta`; **tidak digambar** bila `status.value = tidak_yakin` |
| Garis ambang | `status.threshold`, berlabel "T" |
| Gaya `tidak_yakin` | Whisker putus-putus dengan `decal` |
| Aksesibilitas | `aria` aktif; deskripsi teks dibangun dari angka yang sama; nilai yang sama tersedia sebagai teks di kartu ringkasan |
| Kosong atau memuat | Ditangani `<CeterisChart>` |

### G2 — Interval mini per baris (layar 04)

Bentuk yang sama dengan G1 tanpa sumbu dan label, dari `ScanSummary.delta` dan `ScanSummary.interval_90`. Skala x sama untuk semua baris dalam satu tabel. Titik tidak digambar bila `status_value = tidak_yakin`. Garis ambang tidak digambar karena `ScanSummary` tidak memuat `threshold`. Baris tanpa hasil (`delta` kosong) tidak menampilkan grafik.

## 6. Aturan tampil angka dan ketidakpastian

| Hal | Aturan | Contoh (ilustrasi) |
| --- | --- | --- |
| ΔAUC | Tiga desimal, tanda eksplisit, koma desimal, tanda minus U+2212 | +0,023; −0,004 |
| Interval 90% | Kurung siku, pemisah titik koma | [+0,008; +0,041] |
| Ambang `T` | Tiga desimal | 0,010 |
| ΔAUC relatif | Persen satu desimal dengan tanda; disembunyikan bila `null` | +7,5% |
| Baris terdampak | Persen satu desimal | 12,4% |
| Tanggal dan waktu | DD/MM/YYYY HH.mm, zona waktu peramban | 15/11/2026 14.05 |

- **Tidak ada pembulatan status di UI.** Pembulatan tampilan tidak boleh membuat interval terlihat tidak memotong `T` padahal statusnya `tidak_yakin`: bila angka yang dibulatkan tampak bertentangan dengan status, nilai penuh tersedia di `Tooltip`, dan status dari API tetap yang ditampilkan (BR-33, BR-34).
- **Angka ΔAUC tidak pernah tampil tanpa interval dan kalimat kondisi** (BR-06), termasuk di ekspor HTML.
- **Interval selalu didampingi flag OOD** (BR-65).
- **Label eksperimental** mengikuti `model.experimental` (BR-35). Kata "akurat" dan "terbukti" tidak dipakai di teks UI (AGENTS.md butir 9).
- **UI tidak menghitung status, ambang, urutan temuan, atau flag OOD.** Semuanya dibaca dari `ScanReport`.

## 7. Aksesibilitas

- Semua alur dapat dijalankan dengan papan ketik; urutan fokus mengikuti urutan baca; fokus terlihat.
- Status berupa ikon dan teks; kontras teks minimal 4,5:1 di mode terang dan gelap.
- Grafik memakai modul `aria` dan `decal`; setiap grafik punya padanan teks di halaman.
- Perubahan status scan dan galat diumumkan lewat wilayah `aria-live`.
- Tabel memakai header kolom semantik; di bawah 768 px setiap baris menjadi kartu dengan label bidang.
- Target sentuh minimal 44 × 44 px pada lebar 390 px.

## 8. Rencana pengujian UI (dijalankan di Phase 10–11)

| Uji | Menjamin |
| --- | --- |
| Playwright: masuk → unggah → status → laporan | Alur utama US1.2 dan US1.3 |
| Playwright: berkas ditolak kontrak input | Alasan tampil, tanpa estimasi parsial (BR-10, BR-11) |
| Playwright pada lebar 390 px dan navigasi papan ketik | US1.3 butir 6 |
| Uji komponen dengan *fixture* Contoh 2 dan Contoh 5 `business-rules.md` | Label status sesuai `status.value`; `tidak_yakin` tanpa titik |
| Uji teks: setiap ΔAUC punya interval dan kalimat kondisi | BR-06 |
| Uji teks: pita eksperimental saat `model.experimental = true` | BR-35 |
| Uji tabel temuan: urutan sama dengan API, tanpa total, `null` tanpa angka | BR-42, BR-43, BR-45 |
| Uji statik: tidak ada perbandingan terhadap `threshold` atau `ood_score` di kode UI | UI tidak menghitung status |
| Uji `<CeterisChart>`: tema, resize, kosong | `execution-plan.md` Phase 10 |
| Pemeriksaan aksesibilitas otomatis (axe) per layar | Bagian 7 |

## 9. Hal terbuka **[T]** untuk G6

Kontrak OpenAPI `/v1` dibekukan di G5. Hal berikut adalah kebutuhan UI yang belum didukung kontrak; masing-masing perlu keputusan pemilik repo.

| # | Hal terbuka | Pilihan |
| --- | --- | --- |
| T-1 | Tidak ada endpoint daftar dataset. Layar 04 hanya bisa dicapai dari laporan atau tautan langsung, dan nama dataset tidak bisa ditampilkan di laporan (`ScanOut` hanya memuat `dataset_id`). | (a) Menambah `GET /v1/datasets` dan `GET /v1/datasets/{id}` sebagai penambahan non-merusak; (b) menerima batasan ini di R1 |
| T-2 | Pertanyaan satu klik "apakah laporan ini mengubah keputusan Anda?" (US1.3 butir 5) belum punya endpoint penyimpan jawaban. | (a) Menambah endpoint umpan balik; (b) menunda pertanyaan sampai uji pengguna R1 |
| T-3 | Ukuran sampel probe (BR-12, "dicatat di laporan") dan jumlah baris tidak ada di `ScanReport` 1.0, sehingga tidak bisa ditampilkan. | (a) Menambah field (menaikkan `schema_version`, BR-60); (b) tidak ditampilkan di R1 |
| T-4 | `ScanSummary` tidak memuat `model.experimental`, sehingga layar 04 tidak tahu baris mana yang eksperimental. | (a) Pita eksperimental selalu tampil di layar 04 selama KL-02 dan KL-04 belum dibuka; (b) menambah field |
| T-5 | Layar kelola token API (US8.1 butir 2) tidak termasuk F-L02 dan belum didesain. | (a) Tetap lewat API di R1; (b) menambah layar di Phase 9 |

## 10. Wireframe

Wireframe digambar pemilik repo secara manual di Figma ([ADR 0021](../decisions/0021-figma-manual-menggantikan-figcraft.md)); alur kerja, penamaan, dan daftar periksa ada di [README.md](README.md). Ekspor PNG dan SVG disimpan di `exports/` dan ditautkan di tabel ini setelah tersedia.

| Layar | Ekspor Figma | *Frame* yang perlu digambar | Sketsa acuan |
| --- | --- | --- | --- |
| 00 Masuk | belum ada **[T]** | Awal, memuat, galat kredensial, layanan tidak tersedia, 390 px | [referensi/00-masuk.png](referensi/00-masuk.png) |
| 01 Unggah | belum ada **[T]** | Kosong, berkas dipilih, mengunggah, berkas terlalu besar, ditolak kontrak input, galat lain, 390 px | [referensi/01-unggah.png](referensi/01-unggah.png) |
| 02 Status scan | belum ada **[T]** | `queued`, `running`, `failed`, tidak ditemukan, 390 px | [referensi/02-status-scan.png](referensi/02-status-scan.png) |
| 03 Laporan | belum ada **[T]** | `material`, `tidak_material`, `tidak_yakin` dengan OOD tinggi, kebocoran target, tab peringatan input, tab keterangan model, tanpa temuan, memuat, galat, 390 px | [referensi/03-laporan.png](referensi/03-laporan.png) |
| 04 Daftar scan | belum ada **[T]** | Terisi, kosong, memuat, 390 px | [referensi/04-daftar-scan.png](referensi/04-daftar-scan.png) |

- Sketsa acuan berasal dari uji coba perkakas sebelumnya. Sketsa itu hanya membantu tata letak, **bukan deliverable**, dan boleh dihapus setelah desain Figma ada.
- Semua angka, nama dataset, dan kode galat di wireframe adalah **ilustrasi**, bukan hasil eksperimen.
- Nama *layer* di Figma memakai nama komponen shadcn/ui (`Card / ...`, `Badge / ...`, `Alert / ...`) dan field `ScanReport` yang menjadi sumbernya.
- Struktur mengikuti block di bagian 3.1: `login-03` untuk layar 00 dan `dashboard-01` untuk layar 01–04.
