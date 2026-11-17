# ADR 0021: Figma manual menggantikan FigCraft untuk desain Phase 9

- **Status:** Diterima **[K]** (arahan pemilik repo, 15/11/2026). Menggantikan [ADR 0017](0017-rencana-mcp-figcraft-untuk-wireframe.md).
- **Tanggal:** 15/11/2026
- **Rilis terdampak:** R1, Sprint D (Phase 9)
- **Rujukan:** `execution-plan.md` prinsip 3 dan Phase 9; [ADR 0003](0003-web-ui-shadcn.md); AGENTS.md butir 12; [docs/design/README.md](../design/README.md); [docs/design/ui-design.md](../design/ui-design.md)

## Konteks

- ADR 0017 merencanakan wireframe Phase 9 dibuat agent lewat server MCP FigCraft. FigCraft 0.18.1 dipasang dan dicoba pada 15/11/2026.
- Pemilik repo menilai MCP FigCraft **tidak stabil** dalam pemakaian dan membatalkannya pada hari yang sama **[K]**.
- Syarat ADR 0017 (lisensi, batas folder, build Windows, ekspor) sempat terpenuhi dalam uji coba **[F]**; pembatalan ini bukan karena syarat itu gagal.

## Keputusan **[K]**

1. **FigCraft tidak dipakai.** Pendaftaran MCP `figcraft` dicabut, dan berkas `.figcraft` tidak disimpan di repository.
2. **Desain dikerjakan pemilik repo secara manual di Figma** (aplikasi Figma biasa). Agent tidak menggambar di Figma.
3. **Implementasi tetap shadcn/ui secara penuh** (ADR 0003, AGENTS.md butir 12). Desain Figma mengikuti struktur block shadcn yang dipetakan di `ui-design.md` bagian 3.1, dan setiap elemen diberi nama komponen shadcn/ui yang direncanakan.
4. **Sumber kebenaran tetap `ui-design.md`.** Berkas Figma adalah sumber kerja; ekspor PNG dan SVG di `docs/design/exports/` adalah salinan yang dirujuk dokumen dan diperbarui setiap kali desain berubah.
5. **Peran agent** terbatas pada: menyusun dan memelihara `ui-design.md`; mencari komponen dan block lewat MCP shadcn; dan, bila pemilik repo memintanya, membaca berkas Figma (hanya baca) untuk memeriksa kesesuaian desain dengan `ui-design.md`.
6. **Batas Phase 9 tidak berubah.** Sebelum G6 tidak ada kode UI, instalasi Next.js, atau visual hi-fi (`execution-plan.md` prinsip 3 dan Phase 9). Desain Figma di Phase 9 berupa wireframe; yang diperiksa di G6 adalah isi `ui-design.md`.
7. **Sketsa acuan.** Lima PNG hasil uji coba FigCraft disimpan di `docs/design/referensi/` hanya sebagai acuan tata letak saat menggambar di Figma. Sketsa itu bukan deliverable dan boleh dihapus setelah desain Figma ada.

## Konsekuensi

- Folder `docs/design/figcraft/` diganti `docs/design/figma/`.
- Aturan batas folder untuk agent MCP (ADR 0017 butir 3) tidak berlaku lagi karena tidak ada agent yang menulis berkas desain.
- Figma berbasis cloud: berkas desain berada di luar repository. Tautan berkas dicatat di `docs/design/README.md`; ekspor di `exports/` menjadi arsip yang ikut repository.
- Desain tidak boleh memuat data mentah pengguna; angka di layar adalah ilustrasi dan diberi label demikian (AGENTS.md bagian 4).

## Hal terbuka **[T]**

| # | Hal | Diputuskan oleh |
| --- | --- | --- |
| 1 | Kit komponen shadcn/ui untuk Figma yang dipakai (kit komunitas atau komponen buatan sendiri) dan lisensinya | Pemilik repo, sebelum mulai menggambar |
| 2 | Apakah salinan lokal `.fig` disimpan di `docs/design/figma/` sebagai arsip | Pemilik repo |
| 3 | Apakah Code Connect Figma dipakai setelah G6 | G6 |
| 4 | Apakah desain Figma boleh lebih dari wireframe sebelum G6 (mengubah `execution-plan.md` prinsip 3) | Pemilik repo |

## Alternatif yang ditimbang

- **Tetap memakai FigCraft.** Ditolak pemilik repo karena MCP-nya tidak stabil.
- **Agent menggambar di Figma lewat MCP.** Tidak dipilih: pemilik repo memilih mendesain sendiri.
- **Langsung di kode tanpa desain.** Bertentangan dengan gerbang G6.
