# ADR 0019: Object store self-host memakai SeaweedFS

- **Status:** Diterima **[K]** oleh pemilik repo 14/11/2026.
- **Tanggal:** 14/11/2026
- **Rilis terdampak:** R1 (Phase 7–8), self-host
- **Rujukan:** `architecture.md` 3 dan 10 (stack terkunci "S3-compatible, MinIO untuk self-host"); [ADR 0016](0016-paket-keputusan-pra-r1.md) K2; [ADR 0018](0018-phase-7-api-worker-registry.md)

## Konteks

- **[F]** Per 14/11/2026, image `minio/minio` dan `minio/mc` tidak lagi tersedia di Docker Hub (API Docker Hub mengembalikan 404), dan repositori yang sama di quay.io butuh login. Akibatnya, `docker compose up` Phase 7 gagal saat menarik `minio/mc`.
- Stack terkunci hanya mewajibkan object store **S3-compatible**. MinIO disebut sebagai pilihan self-host, bukan sebagai kontrak.
- Pemilik repo menargetkan Cloudflare R2 untuk mode hosted setelah R1, sehingga kode server tidak boleh bergantung pada fitur khusus satu vendor.

## Keputusan **[K]**

1. **Docker Compose memakai SeaweedFS** sebagai object store S3-compatible.
   - Image `chrislusf/seaweedfs:4.53`, tag rilis bernomor 08/11/2026, bukan `latest` atau `dev`.
   - Lisensi Apache-2.0 (dicek di repositori `seaweedfs/seaweedfs`, 14/11/2026).
   - Berjalan satu node dengan gateway S3 di port 8333. Identitas S3 dibuat dari variabel lingkungan `S3_ACCESS_KEY` dan `S3_SECRET_KEY` oleh `docker/objectstore/entrypoint.sh`, sehingga kredensial tidak tertulis di repository.
2. **Nama layanan, variabel, dan volume dibuat netral:** `objectstore`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, dan `objectstore-data`. Mengganti layanan S3 nanti tidak perlu mengganti nama.
3. **Kode server tetap memakai pustaka `minio` (Apache-2.0) sebagai klien S3 generik.**
   - Pemakaiannya dibatasi ke API S3 dasar: bucket ada atau dibuat, put, get, unduh, dan stat.
   - Fitur khusus MinIO tidak dipakai, agar layanan lain seperti Cloudflare R2 bisa dipakai tanpa perubahan kode.
4. **Bucket dibuat oleh API dan worker lewat klien S3** saat konteks proses dibangun (`S3ObjectStore.ensure_bucket`). Ini menggantikan layanan `minio-init` (`mc`) yang ikut hilang.
5. **Backend `local:<folder>` tetap didukung** sebagai alternatif tanpa S3 untuk self-host satu mesin. Compose bawaan memakai SeaweedFS agar jalur S3 benar-benar teruji.

## Validasi **[F]** (14/11/2026)

- `docker compose up --build` dengan `chrislusf/seaweedfs:4.53`: layanan `objectstore` sehat.
- Registry dan snapshot tersimpan di bucket `ceteris`.
- Scan lewat API container dan worker selesai `done`.
- Uji `integration` lulus, termasuk pembuatan bucket `ceteris-it` lewat `S3ObjectStore.ensure_bucket`.

## Konsekuensi

- `architecture.md` (tabel kontainer dan stack), ADR 0018, backlog R1 US8.3, dan `compose.yaml` diselaraskan.
- Uji `integration` memakai port S3 8333 lewat `compose.test.yaml`, termasuk pembuatan bucket lewat klien.

## Alternatif yang ditolak

- **RustFS (Apache-2.0).** Kompatibel MinIO dan konfigurasinya paling mirip, tetapi baru versi 1.0.x sehingga kurang teruji.
- **Hanya volume lokal tanpa S3.** Paling sederhana, tetapi jalur S3 tidak teruji di compose, padahal mode hosted nanti memakai S3 (R2).
- **Image MinIO dari registry yang butuh login atau build sendiri.** Menambah langkah dan ketergantungan pada distribusi yang tidak lagi tersedia publik.
