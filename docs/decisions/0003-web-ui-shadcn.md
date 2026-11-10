# ADR 0003: Web UI memakai shadcn/ui secara penuh

- **Status:** Diterima **[K]** (arahan pemilik repo, 10/11/2026); pembagian peran grafik diputuskan pada tanggal yang sama
- **Tanggal:** 10/11/2026
- **Rilis terdampak:** R1 ke atas. Belum ada kode UI; jangan membangun UI sebelum diminta (AGENTS.md bagian 1).
- **Rujukan:** `architecture.md` bagian 3 dan 10; F-L02

## Konteks

Web UI (laporan, dashboard, pengaturan kebijakan) memakai Next.js. Tim kecil perlu antarmuka konsisten tanpa membangun sistem desain sendiri. UI hanya menampilkan hasil; ia tidak menghitung status sendiri.

## Keputusan

1. Komponen UI memakai **shadcn/ui** secara penuh, ditambahkan lewat CLI (`npx shadcn@latest add <komponen>`) dan dirujuk dari `components.json`.
2. Tailwind CSS (dan Radix UI di bawah shadcn) menjadi bagian tumpukan UI sebagai konsekuensi langsung.
3. Komponen buatan sendiri hanya dibuat bila shadcn/ui tidak punya padanan; alasannya dicatat di PR.
4. Setiap kali agent menulis atau mengubah kode UI, ia menyebut komponen shadcn/ui yang dipakai beserta alasannya (rule di AGENTS.md bagian 3, butir 12).
5. MCP resmi shadcn dipasang di `.mcp.json` agar agent mencari dan memasang komponen dari registry, bukan menebaknya.

## Pembagian peran: shadcn/ui dan ECharts **[K]**

Diputuskan pemilik repo pada 10/11/2026: keduanya dipakai dengan peran berbeda.

| Peran | Pustaka | Cakupan |
| --- | --- | --- |
| Kerangka antarmuka | shadcn/ui | Tabel (TanStack Table), kartu, badge, dialog, dan komponen non-grafik lain |
| Semua grafik | ECharts | Interval plot, heatmap, reliability diagram, histogram profil, tren |

Komponen `chart` bawaan shadcn/ui (Recharts) **tidak dipakai**. Alasannya:

1. Grafik inti Ceteris bukan grafik umum: interval plot, heatmap kolom × jenis temuan, reliability diagram, dan histogram profil dalam jumlah banyak. Recharts tidak punya heatmap, dan histogram ratusan kolom berbasis SVG berat.
2. ECharts bisa dirender di server menjadi string SVG, berguna untuk laporan scan yang diekspor ke HTML atau PDF, atau dilampirkan ke komentar PR dari gate.

Aturan implementasi:

- Impor modular (`echarts/core` dan hanya tipe grafik yang dipakai); bundel penuh tidak dipakai.
- Komponen grafik berjalan di klien (client component atau `dynamic(..., { ssr: false })`) dengan `ResizeObserver` agar ikut menyesuaikan saat sidebar dilipat.
- Hanya ada satu pembungkus `<CeterisChart>` yang menangani tema, resize, status loading dan kosong, serta aksesibilitas. Konfigurasi `option` mentah tidak disebar di halaman.
- ECharts tidak membaca CSS variable shadcn secara otomatis: tema dibangun dari token lewat `getComputedStyle` dan diinisialisasi ulang saat mode gelap berganti.
- Modul `aria` dan `decal` diaktifkan.

## Pedoman tampilan (usulan, bukan aturan)

Pedoman ini turun dari prinsip "kejujuran sebagai fitur" dan baru mengikat setelah dipastikan terhadap `business-rules.md` saat fitur UI dikerjakan.

1. Taksiran tidak pernah tampil tanpa interval: dot + whisker (gaya forest plot, `custom` series), bukan bar chart. Selaras dengan BR-33 dan BR-34.
2. Status `tidak_yakin` terlihat beda secara visual: titik estimasi tidak digambar, hanya rentang interval dengan arsiran atau garis putus-putus, plus badge teks.
3. Tampilan utama adalah tabel temuan (shadcn + TanStack Table) berurutan menurut estimasi dampak, dengan mini interval plot inline per baris. Grafik melayani tabel, bukan sebaliknya.
4. Grafik yang direncanakan: interval plot temuan teratas dengan garis ambang `T` (`markLine`); tren ΔAUC antar-scan dengan pita interval; heatmap kolom × jenis temuan; reliability diagram meta-model.
5. Dihindari: gauge, pie, radar, dan animasi berlebihan.
6. Status tidak dibedakan hanya dengan warna merah/hijau; ikon dan teks wajib menyertai.
7. **[T]** Label status gate di UI (usulan: Lolos / Ditahan / Tidak yakin) harus dipetakan ke keputusan `allow`/`warn`/`block` di BR-50 dan BR-51 sebelum dipakai.
8. **[T]** Presisi ΔAUC di UI (usulan: tiga desimal, tanda +/− eksplisit, koma desimal pada antarmuka berbahasa Indonesia, tanggal DD/MM/YYYY) dipastikan bersama kalimat kondisi (BR-06) saat UI dibangun.

## Konsekuensi

- Bahasa visual UI mengikuti shadcn/ui; token tema diubah lewat CSS variable, bukan menimpa komponen.
- Tambahan dependensi UI (Tailwind, Radix, ECharts) mengikuti keputusan ini dan tidak perlu persetujuan terpisah; dependensi lain tetap perlu.
- Rule "sebut komponen shadcn/ui" berlaku untuk kerangka UI. Untuk grafik, agent menyebut tipe grafik ECharts dan memakainya lewat `<CeterisChart>`.

## Alternatif yang ditolak

- Sistem desain sendiri: biaya tidak sebanding untuk tim kecil.
- Pustaka komponen lain (MUI, Chakra): bertentangan dengan arahan pemilik repo.
- Komponen `chart` shadcn/ui (Recharts) untuk grafik: tidak punya heatmap, berat untuk histogram besar, dan tidak bisa dirender di server ke SVG sesederhana ECharts.
