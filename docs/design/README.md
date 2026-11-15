# Desain UI (Phase 9)

Folder ini menampung desain Web UI R1 (F-L02). Phase 9 dimulai 15/11/2026 ([execution-plan.md](../execution-plan.md)); desain masih draf sampai G6. Perkakas dan aturan pakainya ada di [ADR 0020](../decisions/0020-figma-manual-menggantikan-figcraft.md), yang menggantikan ADR 0017 (FigCraft, dibatalkan).

## Struktur

```text
docs/design/
  README.md        berkas ini
  ui-design.md     dokumen desain UI, deliverable utama Phase 9 dan sumber kebenaran
  figma/           catatan berkas Figma (tautan; salinan .fig bila diputuskan disimpan)
  exports/         ekspor PNG dan SVG tiap layar dari Figma (salinan yang dirujuk dokumen)
  referensi/       sketsa acuan tata letak dari uji coba awal; bukan deliverable
```

## Berkas Figma

- **Tautan berkas:** belum ada **[T]**. Diisi pemilik repo setelah berkas dibuat.
- **Kit shadcn/ui untuk Figma:** belum dipilih **[T]** (ADR 0020, hal terbuka 1).

## Cara kerja

Desain digambar pemilik repo secara manual di Figma. Agent tidak menggambar; ia memelihara `ui-design.md` dan, bila diminta, memeriksa desain terhadap dokumen itu.

1. Satu *page* Figma per layar, bernama sama dengan layar di `ui-design.md` bagian 4: `00-masuk`, `01-unggah`, `02-status-scan`, `03-laporan`, `04-daftar-scan`.
2. Di tiap *page*: satu *frame* utama desktop selebar 1440 px, satu *frame* seluler selebar 390 px, dan satu *frame* per keadaan yang tercantum di tabel keadaan layar itu.
3. Struktur layar mengikuti block shadcn di `ui-design.md` bagian 3.1: `login-03` untuk layar 00 dan `dashboard-01` untuk layar 01–04.
4. Setiap elemen diberi nama komponen shadcn/ui yang direncanakan (`Card / ringkasan`, `Badge / status`, `Alert / pita eksperimental`). Elemen yang menampilkan data diberi nama field `ScanReport` sumbernya (`estimate.delta`, `status.value`).
5. Grafik digambar sebagai kotak penanda bernama `CeterisChart / G1` atau `CeterisChart / G2`; spesifikasinya ada di `ui-design.md` bagian 5, bukan di Figma.
6. Setelah sebuah layar selesai atau berubah, *frame* utamanya diekspor ke `exports/` sebagai PNG dan SVG dengan nama layar.

## Aturan

- **Sumber kebenaran adalah `ui-design.md`**, bukan berkas Figma. Bila desain di Figma menyimpang dari dokumen, dokumen diperbarui lebih dulu atau desain disesuaikan; keduanya tidak dibiarkan berbeda.
- **Implementasi tetap shadcn/ui secara penuh** (ADR 0003, AGENTS.md butir 12). Elemen tanpa padanan komponen shadcn/ui dicatat di `ui-design.md` beserta alasannya.
- **Tidak ada kode UI atau instalasi Next.js sebelum G6** (`execution-plan.md` prinsip 3).
- **Angka di layar adalah ilustrasi** dan diberi label demikian; desain tidak memuat data mentah pengguna.
- **Status tidak dibedakan hanya dengan warna**; ikon dan teks selalu menyertai (ADR 0003 pedoman 6).
- **Penamaan ekspor:** `<nomor-layar>-<nama-layar>`, huruf kecil dan tanda hubung, misalnya `03-laporan.png`.

## Daftar periksa per layar sebelum G6

- [ ] Setiap keadaan di tabel keadaan `ui-design.md` punya *frame*.
- [ ] Setiap ΔAUC tampil bersama interval dan kalimat kondisi (BR-06).
- [ ] Interval tampil bersama flag OOD (BR-65).
- [ ] Pita eksperimental ada di layar yang memuat angka mode learned (BR-35).
- [ ] `tidak_yakin` tampil tanpa titik estimasi (BR-33, BR-34).
- [ ] Tabel temuan tanpa total dan tanpa kendali urut; judul kolom "Potensi pemulihan ideal" (BR-41, BR-42, BR-43).
- [ ] Tidak ada elemen yang menuntut UI menghitung status, ambang, atau urutan.
- [ ] Varian 390 px ada dan dapat dibaca.
- [ ] Ekspor PNG dan SVG di `exports/` sesuai desain terakhir.
