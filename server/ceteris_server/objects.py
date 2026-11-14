"""Object store: snapshot data yang dipindai dan berkas registry (architecture.md 6.3).

Dua implementasi dengan antarmuka yang sama: folder lokal (pengembangan, uji, self-host satu
mesin) dan S3-compatible lewat klien MinIO (Docker Compose, produksi).
"""

from __future__ import annotations

import io
import shutil
from pathlib import Path, PurePosixPath
from typing import Protocol

from ceteris_server.settings import Settings


class ObjectStoreError(RuntimeError):
    """Objek tidak ada atau kunci tidak sah."""


class ObjectStore(Protocol):
    def put_file(self, key: str, path: Path) -> None: ...

    def put_bytes(self, key: str, data: bytes) -> None: ...

    def get_bytes(self, key: str) -> bytes: ...

    def download(self, key: str, path: Path) -> None: ...

    def exists(self, key: str) -> bool: ...

    def uri(self, key: str) -> str: ...


def _check_key(key: str) -> str:
    parts = PurePosixPath(key).parts
    if not key or key.startswith("/") or ".." in parts or "\\" in key:
        raise ObjectStoreError(f"kunci objek tidak sah: {key!r}")
    return key


class LocalObjectStore:
    """Object store di folder lokal; kunci memakai garis miring ala S3."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        return self.root.joinpath(*PurePosixPath(_check_key(key)).parts)

    def put_file(self, key: str, path: Path) -> None:
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)

    def put_bytes(self, key: str, data: bytes) -> None:
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def get_bytes(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise ObjectStoreError(f"objek tidak ada: {key}")
        return path.read_bytes()

    def download(self, key: str, path: Path) -> None:
        source = self._path(key)
        if not source.is_file():
            raise ObjectStoreError(f"objek tidak ada: {key}")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, path)

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def uri(self, key: str) -> str:
        return f"local://{_check_key(key)}"


class S3ObjectStore:
    """Object store S3-compatible (MinIO untuk self-host)."""

    def __init__(self, bucket: str, settings: Settings) -> None:
        from minio import Minio

        self.bucket = bucket
        self.client = Minio(
            settings.s3_endpoint,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            secure=settings.s3_secure,
        )

    def put_file(self, key: str, path: Path) -> None:
        self.client.fput_object(self.bucket, _check_key(key), str(path))

    def put_bytes(self, key: str, data: bytes) -> None:
        self.client.put_object(self.bucket, _check_key(key), io.BytesIO(data), len(data))

    def get_bytes(self, key: str) -> bytes:
        from minio.error import S3Error

        try:
            response = self.client.get_object(self.bucket, _check_key(key))
        except S3Error as err:
            raise ObjectStoreError(f"objek tidak ada: {key}") from err
        try:
            return bytes(response.read())
        finally:
            response.close()
            response.release_conn()

    def download(self, key: str, path: Path) -> None:
        from minio.error import S3Error

        try:
            self.client.fget_object(self.bucket, _check_key(key), str(path))
        except S3Error as err:
            raise ObjectStoreError(f"objek tidak ada: {key}") from err

    def exists(self, key: str) -> bool:
        from minio.error import S3Error

        try:
            self.client.stat_object(self.bucket, _check_key(key))
        except S3Error:
            return False
        return True

    def uri(self, key: str) -> str:
        return f"s3://{self.bucket}/{_check_key(key)}"


def object_store(settings: Settings) -> ObjectStore:
    spec = settings.object_store
    if spec.startswith("local:"):
        return LocalObjectStore(Path(spec.removeprefix("local:")))
    if spec.startswith("s3://"):
        return S3ObjectStore(spec.removeprefix("s3://").strip("/"), settings)
    raise ObjectStoreError(f"CETERIS_OBJECT_STORE tidak dikenal: {spec!r}")
