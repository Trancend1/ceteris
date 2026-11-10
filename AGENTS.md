# AGENTS.md — Panduan untuk AI agent di repository Ceteris

Ceteris adalah platform *data quality intelligence*: ia menaksir **seberapa besar kekotoran data merugikan hasil** (mulai dari ΔAUC model), dengan interval dan status yang jujur, lalu memakai taksiran itu untuk prioritas, gate, dan sinyal kepercayaan.

## 1. Status proyek

- Tahap konsep per 10/11/2026: dokumen di `docs/` menggambarkan **rencana**, bukan kode yang sudah ada.
- Sebelum mengandaikan sebuah modul, perintah, atau endpoint ada, periksa isi repository. Jika belum ada, katakan demikian; jangan menulis seolah-olah sudah ada.
- Rilis yang sedang dikerjakan: **R0** (bukti mode *learned*, fitur F-S01–F-S14). Jangan membangun fitur R1+ (API, web UI, gate) kecuali diminta.

## 2. Peta dokumen

Setiap dokumen punya satu tanggung jawab. Baca yang relevan sebelum bekerja; jangan menyalin isinya ke tempat lain.

| Pertanyaan | Dokumen |
| --- | --- |
| Apa yang dibangun, untuk siapa, urutan prioritas, ID fitur | `docs/product.md` |
| Komponen, alur data, batasan arsitektur (AC), NFR, integrasi | `docs/architecture.md` |
| Rumus, ambang, status, gate, contoh perhitungan (BR) | `docs/business-rules.md` |
| Arti sebuah istilah | `docs/domain/glossary.md` |
| Diagram dan sumbernya | `docs/diagrams/` (`src/*.html` adalah sumber) |
| Alasan keputusan desain (ADR 0001–) | `docs/decisions/` |

Urutan otoritas bila ada pertentangan: `business-rules.md` (angka dan keputusan) → `architecture.md` (struktur) → `product.md` (scope) → kode. Jika kode bertentangan dengan dokumen, laporkan; jangan diam-diam memilih salah satu.

## 3. Aturan yang tidak boleh dilanggar

1. **Profil hanya dari data kotor.** `ceteris.dqprofile` tidak boleh menerima versi bersih atau level korupsi (BR-20, AC-2).
2. **Satu implementasi profil** untuk riset dan scan (AC-1). Jangan membuat salinan logika profil di tempat lain.
3. **Jalur scan tidak mengimpor kode eksperimen** (`corpus`, `corrupt`, `evaluate`) dan tidak melatih meta-model (AC-3, AC-4).
4. **Definisi ΔAUC dan ambang `T = max(0,01; noise floor)` tidak diubah** tanpa mengubah `business-rules.md` lebih dulu (BR-01, BR-05).
5. **Status tidak pernah dibulatkan.** Interval yang memotong ambang, atau skor OOD tinggi, selalu `tidak_yakin` (BR-33, BR-34).
6. **Korupsi hanya pada partisi latih; test set tidak pernah diubah** (BR-80). Dataset uji LODO tidak dipakai untuk melatih, men-tuning, atau mengkalibrasi (BR-81).
7. **Tidak ada penulisan ke data sumber.** Tidak ada imputasi atau perbaikan diam-diam (BR-70, AC-7).
8. **`ScanReport` adalah kontrak.** Perubahan field menaikkan `schema_version`; perubahan yang merusak hanya di versi mayor (BR-60, AC-10).
9. **Klaim mengikuti bukti.** Sebelum G3, semua angka mode learned berlabel eksperimental. Jangan menulis "akurat" atau "terbukti" di kode, laporan, atau dokumen (BR-35, BR-64).
10. **Kalimat kondisi wajib** menyertai setiap ΔAUC yang ditampilkan (BR-06).
11. **No AI trailer pada push/PR.** Pesan commit dan deskripsi PR tidak boleh memuat trailer atau atribusi AI (`Co-Authored-By: Claude`, "Generated with Claude Code", dan sejenisnya). Identitas author dan committer adalah pemilik repo (manusia). Bila pengungkapan bantuan AI diperlukan, tulis dalam prosa biasa di deskripsi PR, bukan di metadata git.
12. **Web UI memakai shadcn/ui secara penuh** (ADR 0003). Setiap kali menulis atau mengubah kode UI, agent wajib menyebut komponen shadcn/ui yang akan dipakai beserta alasannya, sebelum atau bersama kodenya. Cari dan pasang komponen lewat MCP shadcn atau CLI (`npx shadcn@latest add <komponen>`); jangan membuat komponen sendiri bila ada padanannya. Semua grafik memakai ECharts lewat satu pembungkus `<CeterisChart>`; komponen `chart` bawaan shadcn/ui tidak dipakai. UI hanya menampilkan hasil dan tidak menghitung status sendiri.

## 4. Bahasa dan penulisan

- Dokumentasi: Bahasa Indonesia baku; istilah teknis tetap bahasa Inggris (*gate*, *scan*, *meta-model*). Kode, nama identifier, dan pesan commit: bahasa Inggris.
- Satuan metrik. Tanggal DD/MM/YYYY. Desimal di dokumen memakai koma (0,01); di kode dan JSON memakai titik (0.01).
- Pakai istilah persis seperti di glosarium. Lihat daftar "istilah yang dihindari" di sana; nama lama `dqimpact` tidak dipakai lagi.
- Tandai pernyataan baru: **[F]** fakta terverifikasi, **[K]** keputusan desain, **[T]** terbuka. Jangan menulis asumsi sebagai fakta. Jangan mengarang angka hasil eksperimen; angka ilustrasi harus diberi label ilustrasi.
- Roadmap tidak memakai tanggal atau durasi. Pakai rilis (R0–R5), gerbang (G1–G4), dan kriteria keluar.

## 5. Cara bekerja pada kode

Struktur yang direncanakan (lihat `docs/architecture.md` bagian 10):

```text
ceteris/     corpus, corrupt, train, dqprofile, store, metamodel,
             uncertainty, evaluate, recovery, scan
configs/     experiment.yaml, learner.yaml, corruption.yaml
notebooks/   NB00–NB10 (papermill)
tests/       unit, properti, determinisme, kontrak, konsistensi jalur
```

- Python 3.11, dikelola `uv`. Dependensi baru: periksa lisensinya dan sebutkan di PR (cleanlab berlisensi AGPL-3.0 dan masih menjadi hal terbuka).
- Setiap fitur merujuk ID di `docs/product.md` (F-S.. atau F-L..). Kode tanpa ID fitur berarti di luar scope: tanyakan dulu.
- Setiap aturan `BR-xx` punya kolom Verifikasi. Saat mengimplementasikan aturan, tulis uji yang disebut di sana dan sebut ID aturan di nama atau docstring uji.
- Keacakan selalu memakai seed eksplisit yang diturunkan dari (`dataset_id`, `config_id`, indeks seed) (BR-84). LightGBM dijalankan deterministik.
- Notebook untuk hasil final hanya dijalankan lewat papermill; bersihkan output dengan nbstripout sebelum commit.
- Angka di naskah dan laporan dibaca dari run store, bukan diketik manual.
- Jangan mengubah `configs/learner.yaml` atau skema profil setelah G1; perubahan berarti versi baru.

## 6. Uji yang wajib lulus

| Uji | Menjamin |
| --- | --- |
| Properti corruption engine | `affected_row_frac` sesuai level yang diminta (BR-82) |
| Isolasi profil | `dqprofile` hanya menerima data kotor (BR-20) |
| Determinisme | Run dan scan yang sama memberi hasil identik (BR-03, AC-12) |
| Kontrak `ScanReport` | Skema tervalidasi; versi naik bila berubah (BR-60) |
| Tabel status | Contoh 2 dan contoh 5 di `business-rules.md` lulus persis |
| Konsistensi jalur | Jalur riset dan jalur scan memberi profil dan prediksi yang sama (BR-16) |
| Uji impor | Jalur scan tidak mengimpor kode eksperimen (AC-3) |

Contoh perhitungan di `docs/business-rules.md` bagian 10 dipakai sebagai *fixture* uji. Jika implementasi memberi angka berbeda, salah satunya keliru: periksa, jangan sesuaikan diam-diam.

## 7. Saat mengubah dokumen

- Ubah di satu tempat yang bertanggung jawab, lalu perbaiki rujukan. Jangan menggandakan tabel atau definisi.
- Menambah fitur: tambahkan baris di feature index `product.md` dengan komponen dan aturan terkait. Fitur harus memenuhi aturan scope (menghasilkan atau mengonsumsi estimasi dampak).
- Menambah aturan: beri ID `BR-xx` berikutnya di kelompoknya, isi kolom Verifikasi, dan tambahkan contoh bila aturan menghasilkan angka.
- Memutuskan hal **[T]**: pindahkan dari daftar hal terbuka ke aturan atau batasan terkait, dan ubah penandanya menjadi **[K]**.
- Mengubah isi diagram: ubah `docs/diagrams/src/<nama>.html`, lalu ekspor ulang PNG dan SVG dengan nama yang sama.

## 8. Kapan berhenti dan bertanya

- Permintaan memerlukan keputusan atas hal yang masih **[T]** (misalnya statistik noise floor, ambang OOD, `fail_mode` gate).
- Perubahan menyentuh definisi ΔAUC, ambang `T`, status, atau kontrak `ScanReport`.
- Diminta menampilkan klaim yang belum ada di register klaim, atau menghapus label eksperimental.
- Diminta menulis ke data sumber, menerapkan fix otomatis, atau mengirim data mentah keluar lingkungan pengguna.
- Hasil eksperimen bertentangan dengan hipotesis: laporkan apa adanya. Hasil negatif diterima; jangan mengubah analisis agar hasilnya cocok.
