"""Konfigurasi server dari variabel lingkungan `CETERIS_*`.

Nilai bawaan cocok untuk pengembangan lokal (SQLite, object store folder lokal, antrian sinkron).
Docker Compose menimpanya dengan Postgres, Redis, dan MinIO (ADR 0018).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # ADR 0016 K5: unggahan ≤ 500 MB per berkas


def _env(name: str, default: str) -> str:
    return os.environ.get(f"CETERIS_{name}", default)


@dataclass(frozen=True)
class Settings:
    """Konfigurasi satu proses API atau worker."""

    database_url: str = field(
        default_factory=lambda: _env("DATABASE_URL", "sqlite:///runs/server/ceteris.db")
    )
    # Kosong berarti antrian sinkron di dalam proses (pengembangan dan uji).
    redis_url: str = field(default_factory=lambda: _env("REDIS_URL", ""))
    # `local:<folder>` atau `s3://<bucket>`; kredensial S3 lewat variabel CETERIS_S3_*.
    object_store: str = field(
        default_factory=lambda: _env("OBJECT_STORE", "local:runs/server/objects")
    )
    s3_endpoint: str = field(default_factory=lambda: _env("S3_ENDPOINT", "localhost:9000"))
    s3_access_key: str = field(default_factory=lambda: _env("S3_ACCESS_KEY", ""))
    s3_secret_key: str = field(default_factory=lambda: _env("S3_SECRET_KEY", ""))
    s3_secure: bool = field(default_factory=lambda: _env("S3_SECURE", "false") == "true")
    # Versi artefak aktif; kosong berarti rilis terbaru di registry.
    artifact_version: str = field(default_factory=lambda: _env("ARTIFACT_VERSION", ""))
    artifact_cache: Path = field(
        default_factory=lambda: Path(_env("ARTIFACT_CACHE", "runs/server/artifact-cache"))
    )
    max_upload_bytes: int = field(
        default_factory=lambda: int(_env("MAX_UPLOAD_BYTES", str(MAX_UPLOAD_BYTES)))
    )
