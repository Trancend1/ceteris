# ADR 0005: Ambang kolom ID dan kebocoran target pada kontrak input

- **Status:** Diterima **[K]** (keputusan pemilik repo, 11/11/2026); angka adalah usulan awal yang dikalibrasi di Phase 2
- **Tanggal:** 11/11/2026
- **Rilis terdampak:** R0, Phase 2 (G1)
- **Rujukan:** BR-13, BR-15, BR-16, BR-20, BR-33; AC-1; `execution-plan.md` Phase 2

## Konteks

`ceteris.dqprofile` mengeluarkan kolom ID sebelum probe (BR-13) dan menandai kebocoran target (BR-15), tetapi "hampir per baris" dan "hampir sempurna" belum punya definisi operasional. Tanpa angka, kontrak input tidak bisa diuji dan korpus riset serta scan pengguna bisa diproses berbeda (BR-16).

## Keputusan

1. **Kolom ID (BR-13).** Kolom non-float (integer, string, kategorikal) dengan rasio nilai unik ≥ **0,95** terhadap jumlah baris dikeluarkan sebelum probe. Kolom float tidak diperiksa, karena kolom kontinu wajar hampir unik. Akibatnya peringatan, bukan penolakan.
2. **Kebocoran target (BR-15).** Fitur tunggal dengan AUC macro one-vs-rest ≥ **0,99** (validasi silang pada sampel BR-12, seed tetap) ditandai sebagai kebocoran target dan status scan menjadi `tidak_yakin`. Dihitung hanya dari data kotor.
3. Kedua ambang adalah usulan awal. Keduanya dikalibrasi pada prototipe Phase 2 terhadap korpus, lalu dibekukan di G1 bersama skema `dqprofile` v1. Perubahan sesudahnya berarti versi profil baru.

## Hal terbuka

- **[T]** Mekanik probe kebocoran: jumlah lipatan validasi silang dan model satu fitur. Ditetapkan di prototipe, dibekukan di G1.

## Konsekuensi

- Uji: kolom ID sintetis (unik, integer, string) dikeluarkan dan kolom float kontinu tidak; fitur yang bocor memaksa `tidak_yakin`; keduanya diuji pada jalur riset dan jalur scan dengan hasil identik (BR-16).
- Kalibrasi diukur pada korpus: proporsi kolom yang dikeluarkan dan proporsi dataset yang ditandai bocor dicatat di laporan prototipe. Bila angka usulan jelas keliru, ganti lewat ADR baru sebelum G1.
- Ambang BR-15 yang rendah membuat lebih banyak scan berstatus `tidak yakin` (BR-33); karena itu ambang yang dipilih konservatif.

## Alternatif yang ditolak

- ID: rasio ≥ 0,99 (ID yang tidak sempurna lolos ke probe) dan rasio = 1,0 (hanya ID sempurna).
- Kebocoran: AUC ≥ 0,95 (fitur kuat yang sah ikut ditandai) dan AUC ≥ 0,999 (kebocoran parsial lolos tanpa peringatan).
