# ADR 0002: Satu implementasi profil dan artefak berversi sebagai satu-satunya sambungan riset ke produk

- **Status:** Diterima **[K]**
- **Tanggal:** 10/11/2026
- **Rilis terdampak:** R0 dan seterusnya
- **Rujukan:** AC-1, AC-2, AC-3, AC-4, AC-9; BR-16, BR-20, BR-21, BR-23

## Konteks

Meta-model dilatih dari profil yang dihitung pada data kotor. Jika profil saat scan dihitung dengan kode berbeda, estimasi menjadi tidak valid tanpa terlihat. Produk juga harus bisa diaudit ke satu versi artefak.

## Keputusan

1. Hanya ada satu implementasi profil, `ceteris.dqprofile`, dipakai oleh riset dan scan. Ia hanya menerima data kotor dan nama kolom target.
2. Jalur scan tidak mengimpor `corpus`, `corrupt`, atau `evaluate`, tidak melatih meta-model, dan tidak menulis ke model registry.
3. Satu-satunya sambungan riset ke produk adalah artefak berversi (meta-model, kalibrator, referensi OOD, laporan akurasi) dengan metadata wajib. Versi profil dan versi artefak harus cocok; ketidakcocokan menghasilkan galat.

## Konsekuensi

- Uji wajib: konsistensi jalur (BR-16), isolasi profil (BR-20), uji impor di CI (AC-3), dan uji kecocokan versi (AC-9).
- Perubahan skema profil setelah G1 berarti versi baru, bukan perubahan di tempat.
- Eksperimen baru tidak memengaruhi produk sampai artefak berikutnya dirilis.

## Alternatif yang ditolak

- Menyalin logika profil ke worker: dua sumber kebenaran, rawan drift.
- Produk menjalankan kode eksperimen saat scan: tidak bisa diaudit dan tidak deterministik.
