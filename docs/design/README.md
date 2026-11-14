# Desain UI (Phase 9)

Folder ini menampung desain Web UI R1 (F-L02). Isinya baru dikerjakan di Phase 9 ([execution-plan.md](../execution-plan.md)); per 14/11/2026 folder ini baru disiapkan. Rencana perkakas dan aturan pakainya ada di [ADR 0017](../decisions/0017-rencana-mcp-figcraft-untuk-wireframe.md).

## Struktur

```text
docs/design/
  README.md        berkas ini
  ui-design.md     dokumen desain UI, deliverable utama Phase 9 (dibuat di Phase 9)
  figcraft/        berkas kerja FigCraft: wireframe low-fidelity (sumber kerja)
  exports/         ekspor PNG dan SVG tiap wireframe (salinan yang dirujuk dokumen)
```

## Aturan

- **Sumber kebenaran adalah `ui-design.md`**, bukan berkas FigCraft. Wireframe hanya lampiran yang dirujuk dokumen.
- **Hanya low-fidelity sampai G6.** Tidak ada mockup hi-fi, kode UI, atau instalasi Next.js sebelum dokumen desain disetujui pemilik repo (`execution-plan.md` prinsip 3).
- **Setiap wireframe diekspor** ke `exports/` sebagai PNG dan SVG dengan nama yang sama dengan berkas sumbernya. Ekspor diperbarui setiap kali sumbernya berubah, mengikuti pola `docs/diagrams/`.
- **Penamaan:** `<nomor-layar>-<nama-layar>`, huruf kecil dan tanda hubung, misalnya `01-unggah`, `02-status-scan`, `03-laporan`.
- **Agent MCP hanya boleh menulis di folder ini** (`--automation-read-root` dan `--automation-write-root`, ADR 0017).
- **Komponen di wireframe diberi nama komponen shadcn/ui** yang direncanakan (ADR 0003, AGENTS.md butir 12), agar inventaris komponen di `ui-design.md` bisa ditelusuri ke layar.
