# Laporan penutupan epoch 0

- **Status:** ditutup 14/11/2026, **kecuali satu butir**: salinan arsip di awan belum diunggah pemilik repo ([ADR 0014](../../decisions/0014-phase-5-e4-dan-holdout.md) butir 4). Sampai butir itu tercatat di [MANIFEST.md](MANIFEST.md), epoch 0 berstatus "ditutup, menunggu salinan kedua".
- **Rujukan:** [ADR 0013](../../decisions/0013-epoch-eksperimen-dan-pelestarian.md) butir 6 (kriteria tutup), [MANIFEST.md](MANIFEST.md), [insights.md](insights.md), [holdout.json](holdout.json).

Setelah ditutup, arsip epoch 0 hanya boleh dibaca. Epoch berikutnya boleh membaca arsip ini, tetapi tidak menulis ke sana dan tidak mengubah verdict-nya.

## Daftar periksa kriteria tutup

| # | Kriteria (ADR 0013 butir 6) | Status | Bukti |
| --- | --- | --- | --- |
| 1 | Semua butir batas epoch dilaporkan apa adanya, termasuk hasil negatif | **Terpenuhi** | E0: ADR 0011. E1 dan H1–H5: ADR 0012 (H2 dan H3 gagal). E4: gagal kriteria, `insights.md` I-13 sampai I-15. BR-16: lolos, I-16 |
| 2 | Arsip lengkap dan hash setiap berkas cocok dengan manifest | **Terpenuhi untuk salinan lokal** | `sha256sum -c SHA256SUMS.txt` di arsip lokal: semua berkas cocok (14/11/2026). Salinan awan belum ada |
| 3 | `report.json` yang dibangkitkan ulang dari arsip dengan commit tercatat identik dengan aslinya (AC-12) | **Terpenuhi** | E0 pada `5144b84` dan E1 pada `10ce452`, dari salinan arsip: identik byte demi byte (`cmp`); log di `runs/e0_regen.log` dan `runs/e1_regen.log`. E4 dijalankan ulang di `0b269b1`: semua nilai identik dengan run `eaeb979` kecuali kolom deskriptif yang diperbaiki (I-18) |
| 4 | Log insight dan laporan penutupan di-commit | **Terpenuhi** | Commit yang memuat berkas ini |
| 5 | Dataset holdout epoch 1 disegel | **Terpenuhi** | `holdout.json` di-commit di `0b269b1`, sebelum rencana analisis epoch 1 ditulis; 15 dataset tanpa kekurangan |

## Ringkasan verdict epoch 0

Verdict ini tidak diubah oleh epoch berikutnya.

| Butir | Verdict |
| --- | --- |
| H1a akurasi | Lolos |
| H1b non-inferiority | Lolos |
| H2 dampak per jenis | Tidak lolos |
| H2b urutan temuan (eksploratif) | Lolos |
| H3 coverage per dataset | Tidak lolos |
| H4 OOD | Lolos (lemah) |
| H5 noise floor estimasi | Lolos |
| RQ4 / E4 data kotor asli (eksploratif) | Tidak lolos kriteria galat; tanpa pasangan ground truth |
| BR-16 konsistensi jalur akhir | Lolos |

## Yang tersisa untuk pemilik repo

- Unggah salinan arsip ke awan, lalu catat lokasinya di `MANIFEST.md`. Setelah itu, verifikasi `SHA256SUMS.txt` pada salinan tersebut.
- Keputusan G4 dan tinjauan H1 (`execution-plan.md` Phase 5).
