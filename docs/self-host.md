# Self-host Ceteris R1

Panduan menjalankan Ceteris R1 di satu mesin dengan Docker Compose (F-L05, US8.3). Keputusan di balik bentuk ini ada di [ADR 0016](decisions/0016-paket-keputusan-pra-r1.md) (tanpa hosted), [ADR 0018](decisions/0018-phase-7-api-worker-registry.md), [ADR 0019](decisions/0019-object-store-seaweedfs.md), dan [ADR 0020](decisions/0020-phase-8-histori-login-self-host.md).

Semua angka mode learned berlabel eksperimental (BR-35). Interval dan status belum boleh dipakai sebagai keputusan tanpa label itu (register klaim KL-02, KL-04).

## Isi paket

| Layanan | Peran |
| --- | --- |
| `caddy` | Reverse proxy TLS; satu-satunya layanan yang dibuka ke jaringan (port 443 dan 80) |
| `api` | REST API `/v1` |
| `worker` | Menjalankan scan dari antrian |
| `postgres` | Metadata store (tanpa data mentah, AC-6) |
| `redis` | Antrian scan |
| `objectstore` | Object store S3 (SeaweedFS): snapshot data yang dipindai dan registry artefak |

Data mentah yang Anda unggah tidak meninggalkan mesin ini (BR-71), dan scan tidak membutuhkan akses jaringan keluar.

## Langkah

### 1. Siapkan konfigurasi

Buat berkas `.env` di akar repository (berkas ini diabaikan git; jangan di-commit) dengan isi berikut, dan ganti setiap nilai rahasia dengan nilai acak:

```text
POSTGRES_USER=ceteris
POSTGRES_PASSWORD=<acak>
POSTGRES_DB=ceteris
S3_ACCESS_KEY=ceteris
S3_SECRET_KEY=<acak>
CETERIS_BUCKET=ceteris
CETERIS_DOMAIN=localhost
CETERIS_ARTIFACT_VERSION=
```

- `CETERIS_DOMAIN`: isi domain publik bila server punya domain; biarkan `localhost` untuk jaringan lokal.
- `CETERIS_ARTIFACT_VERSION`: kosong berarti rilis artefak terbaru di registry.
- Tanpa `.env`, compose memakai nilai pengembangan bawaan yang **tidak aman** untuk dipakai tim.

### 2. Jalankan

```bash
docker compose up -d --build
```

API dan worker menjalankan migrasi skema sendiri saat mulai.

### 3. Rilis artefak model ke registry

Folder artefak (misalnya `artifacts/metamodel-1.0.0`) dibangun di jalur riset dan tidak ada di repository. Salin folder itu ke `./artifacts` di mesin ini, lalu jalankan:

```bash
docker compose exec api python -m ceteris_server.registry publish --artifact /artifacts/metamodel-1.0.0 --accuracy /app/configs/registry/metamodel-1.0.0.accuracy.json
```

Registry menolak artefak yang lebih buruk dari rilis sebelumnya pada set regresi yang sama (BR-63).

### 4. Buat akun

R1 tidak punya pendaftaran publik. Admin membuat akun lewat CLI; kata sandi diminta secara interaktif dan minimal 12 karakter:

```bash
docker compose exec api python -m ceteris_server.auth create-user --email anda@contoh.id
```

### 5. Login, buat token API, dan scan

```bash
curl -s https://localhost/v1/auth/login -H 'content-type: application/json' -d '{"email":"anda@contoh.id","password":"..."}'
```

Respons berisi token sesi yang berlaku 12 jam. Untuk SDK atau CI, buat token API yang berlaku sampai dicabut. Teks token hanya ditampilkan sekali:

```bash
curl -s https://localhost/v1/tokens -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' -d '{"name":"ci"}'
```

Scan satu berkas (CSV atau Parquet, maksimal 500 MB):

```bash
curl -s https://localhost/v1/datasets -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' -d '{"name":"churn","target":"class"}'
```

```bash
curl -s https://localhost/v1/scans -H "Authorization: Bearer $TOKEN" -F dataset_id=$DATASET_ID -F file=@data.parquet
```

Status dan laporan: `GET /v1/scans/{id}` dan `GET /v1/scans/{id}/report`. Histori dan perbandingan: `GET /v1/datasets/{id}/scans`. Spesifikasi lengkapnya ada di `https://<host>/docs`.

## Keamanan (NFR-5)

- **TLS:** Caddy memakai TLS 1.2 sebagai versi minimum.
  - Dengan `CETERIS_DOMAIN=localhost`, sertifikat diterbitkan CA internal Caddy. Pasang sertifikat akar dari volume `caddy-data` (`/data/caddy/pki/authorities/local/root.crt`) di klien, atau pakai `curl --cacert`.
  - Dengan domain publik, sertifikat diterbitkan otomatis lewat ACME.
- **Enkripsi at-rest adalah tanggung jawab operator.** Simpan volume Docker (`postgres-data`, `objectstore-data`, `caddy-data`) di disk terenkripsi: LUKS di Linux, BitLocker di Windows, atau disk terenkripsi penyedia awan. Paket ini tidak mengenkripsi volume sendiri.
- **Rahasia:** hanya di `.env` atau secret manager, tidak pernah di repository. Kata sandi disimpan sebagai hash Argon2id; token hanya sebagai hash SHA-256. Keduanya tidak pernah ditulis ke log.

## Retensi dan cadangan

- **Retensi:** snapshot data yang dipindai disimpan di `objectstore-data` sampai operator menghapusnya. Aturan retensi 24 jam hanya berlaku untuk mode hosted (BR-72), yang tidak dibangun di R1.
- **Cadangan:** cadangkan volume `postgres-data` dan `objectstore-data` bersama-sama, karena metadata merujuk objek di object store.

## Pembaruan

```bash
git pull
```

```bash
docker compose up -d --build
```

Migrasi skema berjalan otomatis. Scan lama tidak dihitung ulang saat artefak naik versi (BR-61).

## Yang belum ada di R1

Helm chart dan Kubernetes (ADR 0020), OIDC dan RBAC (R2), mode hosted (ADR 0016 K2), dan Web UI (Phase 9–11).
