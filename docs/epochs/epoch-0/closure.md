# Laporan penutupan epoch 0

- **Status:** **ditutup 14/11/2026.** Arsip tersimpan di dua salinan: lokal, dan Google Drive sebagai lima zip ([MANIFEST.md](MANIFEST.md)).
- **Rujukan:** [ADR 0013](../../decisions/0013-epoch-eksperimen-dan-pelestarian.md) butir 6 (kriteria tutup), [MANIFEST.md](MANIFEST.md), [insights.md](insights.md), [holdout.json](holdout.json).

Setelah ditutup, arsip epoch 0 hanya boleh dibaca. Epoch berikutnya boleh membaca arsip ini, tetapi tidak menulis ke sana dan tidak mengubah verdict-nya.

## Daftar periksa kriteria tutup

| # | Kriteria (ADR 0013 butir 6) | Status | Bukti |
| --- | --- | --- | --- |
| 1 | Semua butir batas epoch dilaporkan apa adanya, termasuk hasil negatif | **Terpenuhi** | E0: ADR 0011. E1 dan H1–H5: ADR 0012 (H2 dan H3 gagal). E4: gagal kriteria, `insights.md` I-13 sampai I-15. BR-16: lolos, I-16 |
| 2 | Arsip lengkap dan hash setiap berkas cocok dengan manifest | **Terpenuhi** | Salinan lokal: `sha256sum -c SHA256SUMS.txt`, semua berkas cocok. Salinan awan: ukuran kelima zip sama persis dengan zip lokal; hash per berkas diperiksa saat pemulihan (`MANIFEST.md`) |
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

- ~~Salinan awan~~: terunggah dan dicatat 14/11/2026.
- ~~Keputusan G4~~: disetujui 14/11/2026, KL-10 tetap ditolak. Tinjauan H1: H1 lolos, tanpa fallback.
