# ADR 0006: Kerangka pengujian RQ2b (H2b) dan H5

- **Status:** Diterima **[K]** (keputusan pemilik repo, 11/11/2026). Bila pembimbing meminta perubahan, ADR ini diganti, bukan diubah diam-diam.
- **Tanggal:** 11/11/2026
- **Rilis terdampak:** R0, rencana analisis G2 (BR-86)
- **Rujukan:** BR-04, BR-05, BR-40–BR-43; `product.md` bagian 6.1; Contoh 2 di `business-rules.md`

## Konteks

RQ2b menanyakan apakah urutan temuan menurut potensi pemulihan lebih berguna daripada urutan volume (H2b). H5 menyatakan noise floor estimasi (scan, dari variasi probe pada data kotor) cukup dekat dengan noise floor terukur (riset, dari dua model bersih berseed berbeda). Kedua hipotesis belum punya ukuran yang bisa dibekukan, dan H5 punya dua kelemahan: ambang `T = max(0,01; nf)` membuat status hanya bergantung pada nf bila nf > 0,01 sehingga kappa bisa terlihat tinggi dari kasus mudah, dan variasi probe pada data kotor bisa secara sistematis lebih besar.

## Keputusan

1. **RQ2b bersifat eksploratif.** Hasilnya tidak memengaruhi klaim utama H1; bila H2b gagal, urutan jatuh ke volume dan klaim urutan tidak ditampilkan.
2. **Ukuran H2b.** Kendall τ antara urutan temuan dan keuntungan AUC nyata dari memulihkan tiap jenis korupsi satu per satu di korpus (versi bersih tersedia), dibandingkan antara urutan potensi pemulihan dan urutan volume dengan uji Wilcoxon berpasangan antar dataset. Ukuran dibekukan di rencana analisis G2.
3. **Nilai "tanpa temuan" bersifat struktural**, tidak bergantung data (misalnya fraksi missing, duplikat, dan label noise estimasi = 0). Fitur profil tanpa nilai ideal struktural tidak ikut dinormalkan; daftar akhirnya dibekukan di G1 bersama skema profil.
4. **H5 dengan tiga tambahan** di rencana analisis G2:
   - kappa status dilaporkan untuk seluruh dataset dan untuk subset dengan noise floor dekat 0,01 (batas subset ditetapkan di pilot E0);
   - bias (nf estimasi dikurangi nf terukur) dilaporkan, bukan hanya selisih median;
   - **fallback:** bila H5 gagal, `T` tetap 0,01 dan noise floor estimasi hanya informatif.
5. **Fallback H5 tidak mengubah BR-05 sekarang.** Perubahan dilakukan lewat revisi `business-rules.md` pada saat H5 dinyatakan gagal (AGENTS.md butir 4).

## Konsekuensi

- Rencana analisis G2 (Phase 3) memuat butir 2–4 dan dibekukan sebelum data dianalisis, sehingga analisis tidak bisa disesuaikan dengan hasil (BR-86).
- F-S12 menyimpan daftar fitur beserta nilai ideal strukturalnya.
- Hasil H2b dan H5 dilaporkan apa adanya, termasuk bila negatif.

## Alternatif yang ditolak

- RQ2b konfirmatori: menjadikan fitur R2 sebagai syarat bukti R0 tanpa alasan kuat.
- Kappa tunggal untuk H5: dapat menutupi kegagalan pada dataset yang justru bergantung pada noise floor.
- Nilai "tanpa temuan" dari profil dataset dasar: bergantung data dan menambah risiko kebocoran antara jalur riset dan scan.
