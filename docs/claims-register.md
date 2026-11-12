# Register klaim

Daftar klaim yang boleh ditampilkan produk, buktinya, dan gerbang setelah klaim itu boleh tampil (BR-64). Klaim yang tidak tercatat di sini tidak boleh tampil di laporan, CLI, API, atau UI. Istilah: [domain/glossary.md](domain/glossary.md).

- **Status:** draf Phase 4 per 13/11/2026. Kolom "Status" diperbarui saat gerbang disetujui pemilik repo.
- **Penanda:** **[F]** fakta terverifikasi · **[K]** keputusan desain · **[T]** terbuka.
- **Aturan pakai:**
  - Satu baris per klaim.
  - Bukti merujuk ke laporan yang dihasilkan dari run store, bukan ke angka yang diketik.
  - Klaim yang hipotesisnya gagal tetap dicatat dengan status "ditolak" beserta penggantinya.

## 1. Klaim mode learned (R0)

| ID | Klaim yang boleh tampil | Bukti yang dibutuhkan | Gerbang | Status per 13/11/2026 |
| --- | --- | --- | --- | --- |
| KL-01 | "ΔAUC diperkirakan X" (estimasi titik), selalu dengan kalimat kondisi BR-06 | H1a lolos di laporan E1 (`runs/e1/report.json`, `h1a`) | G3 | Belum boleh tampil. Sebelum G3, angka hanya tampil dengan label eksperimental (BR-35) |
| KL-02 | "Interval 90% [lo; hi]", selalu bersama flag OOD (BR-65) | H3 lolos (`h3`) | G3 | Belum boleh tampil |
| KL-03 | "Estimasi ini setara dengan melatih ulang bertingkat, dengan biaya jauh lebih murah" | H1b lolos (`h1b`) | G3 | Belum boleh tampil |
| KL-04 | Status `material`, `tidak_material`, atau `tidak_yakin` dari interval dan `T` | H1a dan H3 lolos; G3-1 diputuskan (`T` dari noise floor estimasi atau lantai 0,01) | G3 | Tampil dengan label eksperimental |
| KL-05 | "Skor OOD tinggi: estimasi kurang andal" | H4 lolos (`h4`); ambang G3-2 diputuskan | G3 | Tampil dengan label eksperimental, memakai ambang sementara pilot |
| KL-06 | Urutan temuan menurut "potensi pemulihan ideal" | H2b lolos (`h2b`, eksploratif). Bila gagal, urutan memakai volume dan klaim ini ditolak (ADR 0006) | G3 | Belum boleh tampil |
| KL-07 | Angka "potensi pemulihan ideal hingga X" per temuan, tanpa total (BR-41, BR-42) | KL-01 boleh tampil; keputusan G3-6 (potensi negatif) | G3 | Belum boleh tampil |
| KL-08 | "ΔAUC relatif Y" (BR-02) | Keputusan G3-4; MAE dan coverage meta-model relatif di laporan E1 | G3 | Belum boleh tampil (null di `ScanReport` pilot) |
| KL-09 | Pernyataan tentang dampak per jenis korupsi (misalnya "label noise paling merusak pada proporsi baris yang sama") | H2 lolos (`h2`) | G3 | Belum boleh tampil |
| KL-10 | Klaim akurasi pada data kotor asli | Galat ≤ 2× MAE LODO pada pasangan nyata (E4) | G4 | Belum boleh tampil |

## 2. Kalimat yang tidak pernah boleh tampil

Kalimat di bawah dilarang apa pun hasil eksperimennya. Daftar lengkap istilah yang dihindari ada di glosarium.

- "Naik X jika diperbaiki" (BR-41).
- "Akurat" atau "terbukti" sebelum G3 (BR-35, AGENTS.md butir 9).
- Jumlah potensi pemulihan antar-temuan, atau potensi sebagai persentase ΔAUC total (BR-42).

## 3. Riwayat

| Tanggal | Perubahan |
| --- | --- |
| 13/11/2026 | Draf pertama Phase 4; semua klaim belum boleh tampil sampai G3 |
