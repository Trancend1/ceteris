# ADR 0003: Web UI memakai shadcn/ui secara penuh

- **Status:** Diterima **[K]** (arahan pemilik repo, 10/11/2026); butir grafik masih **[T]**
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

## Hal terbuka

- **[T]** Grafik: komponen `chart` shadcn/ui (berbasis Recharts) atau ECharts seperti di `architecture.md`. Sampai diputuskan, ECharts tetap tertulis di arsitektur.

## Konsekuensi

- Bahasa visual UI mengikuti shadcn/ui; token tema diubah lewat CSS variable, bukan menimpa komponen.
- Tambahan dependensi UI (Tailwind, Radix) mengikuti keputusan ini dan tidak perlu persetujuan terpisah; dependensi lain tetap perlu.

## Alternatif yang ditolak

- Sistem desain sendiri: biaya tidak sebanding untuk tim kecil.
- Pustaka komponen lain (MUI, Chakra): bertentangan dengan arahan pemilik repo.
