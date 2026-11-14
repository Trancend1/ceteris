# ADR 0017: Rencana MCP FigCraft untuk wireframe Phase 9

- **Status:** Rencana diterima **[K]** oleh pemilik repo 14/11/2026. Pemasangan ditunda sampai awal Phase 9 dan bergantung pada verifikasi di bagian "Syarat sebelum dipasang" **[T]**.
- **Tanggal:** 14/11/2026
- **Rilis terdampak:** R1, Sprint D (Phase 9)
- **Rujukan:** `execution-plan.md` prinsip 3 dan Phase 9; [ADR 0003](0003-web-ui-shadcn.md); AGENTS.md butir 12; [docs/design/README.md](../design/README.md)

## Konteks

- Phase 9 menghasilkan dokumen desain UI dengan wireframe **low-fidelity**, tanpa kode, instalasi, atau visual hi-fi. Desain disetujui di G6 sebelum Phase 10 dimulai (`execution-plan.md`).
- Pemilik repo ingin wireframe dibuat dengan bantuan agent lewat MCP, memakai **FigCraft** (`storytold/figcraft`): editor desain lokal berbasis Rust, alternatif Figma, dengan server MCP.
- Hal berikut berasal dari artikel pihak ketiga dan dokumentasi yang dirujuknya, dan **belum diverifikasi langsung** di repositori **[T]**:
  - semua perintah aplikasi (lebih dari 400) ada di satu registry yang dipakai bersama oleh UI, CLI, kanal kontrol JSON, dan server MCP;
  - server MCP punya mode *headless* (dokumen di memori, tanpa jendela) dan mode *attached* (mengendalikan aplikasi yang terbuka, perubahan terlihat langsung);
  - opsi `--automation-read-root` dan `--automation-write-root` membatasi folder baca dan tulis; sejak 0.13.1 agent yang dibatasi tidak bisa memublikasikan atau membagikan berkas ke server;
  - CLI siap pakai hanya tersedia untuk macOS; di Windows harus di-build dari source dengan cargo;
  - format berkas pernah tidak cocok antara server dari branch `main` dan aplikasi 0.5.1 (issue 219); sejak 0.6.0 keduanya memakai versi format yang sama.

## Keputusan **[K]**

### 1. Peran FigCraft

- FigCraft dipakai **hanya untuk wireframe low-fidelity Phase 9**.
- Alat untuk desain hi-fi setelah G6 (FigCraft, Figma dengan Code Connect, atau langsung di kode dengan shadcn/ui) diputuskan terpisah di G6.
- FigCraft bukan dependensi kode dan tidak masuk `pyproject.toml` atau aplikasi web.

### 2. Struktur folder dan sumber kebenaran

- Folder `docs/design/` (lihat README-nya): `ui-design.md` (deliverable), `figcraft/` (berkas kerja), dan `exports/` (PNG dan SVG).
- **Sumber kebenaran adalah `ui-design.md`.** Berkas FigCraft adalah sumber kerja, dan ekspor PNG/SVG adalah salinan yang dirujuk dokumen.
- Setiap wireframe diekspor ulang saat sumbernya berubah, mengikuti pola `docs/diagrams/`. Alasannya: proyek ini masih 0.x, sehingga berkas sumber mungkin tidak bisa dibuka lagi di versi mendatang, padahal desain menjadi bagian artefak historis.

### 3. Batas akses agent

Server MCP selalu dijalankan dengan batas folder ke `docs/design/`, sehingga agent tidak bisa membaca atau menulis run store, kode, arsip epoch, atau folder lain:

```bash
claude mcp add figcraft -- <path>/figcraft-cli mcp --automation-read-root D:/DevSpace/Projects/ceteris/docs/design --automation-write-root D:/DevSpace/Projects/ceteris/docs/design
```

Mode *attached* (mengendalikan aplikasi yang terbuka, misalnya `figcraft --control 7979` lalu `mcp --attach 7979`) boleh dipakai agar pemilik repo melihat setiap perubahan dan melanjutkan dengan tangan. Batas folder yang sama tetap berlaku.

### 4. Versi

- Build dari **tag rilis tertentu**, bukan branch `main`.
- Aplikasi dan server MCP selalu memakai **rilis yang sama**.
- Versi yang dipakai dicatat di `docs/design/README.md` dan di dokumen desain saat Phase 9 dimulai.

### 5. Kaitan dengan shadcn/ui

- FigCraft tidak punya kit shadcn/ui atau Code Connect. Pemetaan wireframe ke komponen dilakukan di `ui-design.md` sebagai inventaris komponen shadcn/ui per layar (deliverable Phase 9, ADR 0003).
- Elemen wireframe diberi nama komponen shadcn/ui yang direncanakan agar inventaris itu bisa ditelusuri ke layar.

## Syarat sebelum dipasang **[T]**

Diperiksa di awal Phase 9. Bila salah satu tidak terpenuhi, FigCraft tidak dipakai dan wireframe dibuat dengan alat lain atau dengan tangan.

| # | Syarat | Cara memeriksa |
| --- | --- | --- |
| 1 | Lisensi mengizinkan pemakaian untuk proyek ini | Berkas lisensi di repositori `storytold/figcraft` |
| 2 | Klaim di bagian Konteks benar untuk rilis yang akan dipakai, terutama batas folder | Dokumentasi MCP repositori dan uji coba: agent yang dibatasi gagal menulis di luar `docs/design/` |
| 3 | Build Windows dengan cargo berhasil dari tag rilis | Build lokal; catat versi Rust dan tag |
| 4 | Ekspor PNG dan SVG tersedia | Uji ekspor satu wireframe |
| 5 | Tidak ada pengiriman berkas ke server luar saat dibatasi | Dokumentasi rilis dan uji coba tanpa jaringan |

## Konsekuensi

- Folder `docs/design/` sudah ada sejak 14/11/2026, tetapi isinya baru dikerjakan di Phase 9. Tidak ada pekerjaan desain sebelum Sprint D (`execution-plan.md`).
- Bila FigCraft gagal memenuhi syarat, struktur folder dan aturan sumber kebenaran tetap berlaku untuk alat apa pun.

## Alternatif yang ditimbang

- **Figma dengan MCP resmi.** Punya Code Connect ke komponen shadcn/ui, tetapi berbasis cloud dan berbayar untuk sebagian fitur. Tetap menjadi kandidat untuk desain hi-fi di G6.
- **FigCraft plugin Figma (DivikWu).** Proyek berbeda dengan nama sama: plugin audit dan sinkronisasi token untuk Figma. Tidak dipilih karena tetap bergantung pada Figma dan belum terbit di npm.
- **Alat desain generatif berbasis cloud** (misalnya Claude Design, Google Stitch). Menghasilkan layar dari deskripsi, tetapi tidak memberi berkas lokal berlapis yang bisa diedit dan diarsipkan bersama repo.
