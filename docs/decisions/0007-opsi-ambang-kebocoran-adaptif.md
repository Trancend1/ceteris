# ADR 0007: Opsi ambang kebocoran target yang adaptif terhadap label noise

- **Status:** Diusulkan **[K]** sebagai opsi yang disiapkan; pilihan akhir (tetap atau adaptif) diputuskan setelah kalibrasi Phase 2 dan dibekukan di G1
- **Tanggal:** 11/11/2026
- **Rilis terdampak:** R0, Phase 2 (G1)
- **Rujukan:** [ADR 0005](0005-ambang-kolom-id-dan-kebocoran-target.md); BR-15, BR-33; F-S05

## Konteks

Probe kebocoran (BR-15) berjalan pada data **kotor** (BR-20). Label noise menurunkan AUC fitur yang sebenarnya bocor. Untuk kasus biner seimbang dengan label yang tertukar acak simetris pada laju ε, fitur yang menyalin label bersih secara sempurna mencapai AUC = 1 − ε terhadap label kotor (turunan analitis; belum diverifikasi secara empiris). Dengan ambang tetap 0,99, kebocoran lolos begitu ε melewati sekitar 1%.

## Opsi

**Opsi A, ambang tetap (default).** AUC ≥ 0,99 seperti di ADR 0005. Sederhana, tanpa kopling dengan komponen lain.

**Opsi B, ambang adaptif.** `τ(ε̂) = max(τ_min; 0,99 · (1 − ε̂))`, dengan ε̂ dari estimator label noise (F-S05) pada sampel yang sama dengan probe.

- Bila ε̂ = 0, hasilnya sama dengan Opsi A.
- `τ_min` mencegah ambang turun sampai fitur yang sah ikut ditandai; nilainya **[T]**, ditetapkan saat kalibrasi.
- Untuk lebih dari dua kelas, bentuk koreksi tidak otomatis mengikuti rumus biner; bentuknya dikalibrasi secara empiris.

| | Opsi A | Opsi B |
| --- | --- | --- |
| Daya deteksi pada data berderau tinggi | Turun tajam | Terjaga |
| False flag pada dataset berderau tinggi | Rendah | Lebih tinggi (fitur sah yang kuat ikut ditandai), sehingga lebih banyak `tidak_yakin` (BR-33) |
| Kopling | Tidak ada | Bergantung pada ε̂ dari F-S05, sehingga ikut terpengaruh pilihan estimator label noise (cleanlab ≥ 2.8.0 berlisensi Apache-2.0 atau implementasi sendiri, masih **[T]**) dan akurasi estimatornya |
| Perubahan aturan | Tidak ada | BR-15 berubah |

## Cara memilih

Kalibrasi Phase 2 mengukur dua hal untuk kedua opsi pada level label noise yang bertingkat: daya deteksi pada kebocoran sintetis (salinan target berderau) dan proporsi false flag pada korpus. Opsi B dipilih hanya bila daya deteksinya pada label noise tinggi naik jelas tanpa false flag yang lebih buruk dari yang disepakati; bila tidak, Opsi A berlaku. Keputusan akhir dicatat sebagai pembaruan ADR ini, lalu `business-rules.md` diubah bila Opsi B terpilih.

## Konsekuensi bila Opsi B dipilih

- Uji properti: ε̂ = 0 menghasilkan ambang yang sama dengan Opsi A; ambang turun monoton terhadap ε̂ sampai `τ_min`; hasil deterministik (AC-12).
- Estimator label noise dihitung lebih dulu dalam `dqprofile` dan hasilnya dipakai probe kebocoran pada jalur riset dan scan yang sama (BR-16).
- `ScanReport` mencatat ambang yang dipakai agar status bisa diaudit.
