"""Model registry: artefak meta-model berversi di object store, dengan manifest (F-L04).

Aturan: BR-23 dan AC-9 (versi profil cocok; dicek `ceteris.artifact.load_artifact`), BR-63 dan
NFR-8 (artefak baru tidak lebih buruk dari laporan akurasi artefak sebelumnya), AC-4 (worker hanya
membaca registry). `Registry` hanya membaca; penulisan lewat `RegistryPublisher`, yang dipakai
peneliti saat merilis artefak, bukan oleh API atau worker.

Tata letak di object store:
- `registry/manifest.json`: daftar rilis berurutan;
- `registry/<versi>/<berkas>`: berkas artefak apa adanya.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ceteris.artifact import Artifact, ArtifactError, load_artifact
from ceteris_server.objects import ObjectStore, object_store
from ceteris_server.settings import Settings

MANIFEST_KEY = "registry/manifest.json"


class RegistryError(RuntimeError):
    """Rilis ditolak, versi tidak ada, atau berkas tidak cocok dengan manifest."""


class AccuracyReport(BaseModel):
    """Ringkasan akurasi artefak pada satu set uji regresi (BR-63).

    `regression_set` menamai set data uji regresi; dua laporan hanya sebanding bila namanya sama.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    regression_set: str = Field(min_length=1)
    mae: float = Field(ge=0.0)
    coverage_in_range_share: float = Field(ge=0.0, le=1.0)
    n_datasets: int = Field(ge=1)
    source: str = Field(min_length=1)


class Release(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str
    profile_schema_version: str
    experimental: bool
    released_at: str
    files: dict[str, str]
    accuracy: AccuracyReport
    regression_override: str | None = None


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    releases: list[Release] = Field(default_factory=list)


def check_not_worse(
    new: AccuracyReport, previous: AccuracyReport | None, override: str | None
) -> None:
    """BR-63: tolak artefak yang lebih buruk dari rilis sebelumnya pada set regresi yang sama.

    Set regresi yang berbeda tidak sebanding; rilis hanya boleh dengan alasan tertulis
    (`override`) yang ikut tercatat di manifest.
    """
    if previous is None:
        return
    if new.regression_set != previous.regression_set:
        if not override:
            raise RegistryError(
                f"set regresi berbeda ({previous.regression_set!r} -> {new.regression_set!r}); "
                "rilis butuh alasan tertulis (BR-63)"
            )
        return
    if new.mae > previous.mae:
        raise RegistryError(f"MAE naik {previous.mae:.6f} -> {new.mae:.6f} (BR-63, NFR-8)")
    if new.coverage_in_range_share < previous.coverage_in_range_share:
        raise RegistryError(
            "proporsi dataset dengan coverage dalam rentang turun "
            f"{previous.coverage_in_range_share:.4f} -> {new.coverage_in_range_share:.4f} (BR-63)"
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Registry:
    """Registry hanya-baca (AC-4): daftar rilis dan pengambilan artefak terverifikasi."""

    def __init__(self, store: ObjectStore, cache_dir: Path) -> None:
        self.store = store
        self.cache_dir = Path(cache_dir)

    def manifest(self) -> Manifest:
        if not self.store.exists(MANIFEST_KEY):
            return Manifest()
        return Manifest.model_validate_json(self.store.get_bytes(MANIFEST_KEY))

    def release(self, version: str | None = None) -> Release:
        releases = self.manifest().releases
        if not releases:
            raise RegistryError("registry kosong: belum ada artefak yang dirilis")
        if not version:
            return releases[-1]
        for item in releases:
            if item.version == version:
                return item
        raise RegistryError(f"versi artefak {version!r} tidak ada di registry")

    def fetch(self, version: str | None = None) -> Path:
        """Unduh (sekali) dan verifikasi berkas rilis; kembalikan folder artefak lokal."""
        release = self.release(version)
        folder = self.cache_dir / release.version
        for name, digest in release.files.items():
            target = folder / name
            if not target.exists() or _sha256(target) != digest:
                self.store.download(f"registry/{release.version}/{name}", target)
                if _sha256(target) != digest:
                    raise RegistryError(f"berkas {name} versi {release.version} tidak cocok")
        return folder

    def load(self, version: str | None = None) -> Artifact:
        return load_artifact(self.fetch(version))


class RegistryPublisher(Registry):
    """Penulis registry untuk peneliti; tidak dipakai API atau worker (AC-4)."""

    def publish(
        self, artifact_dir: Path, accuracy: AccuracyReport, override: str | None = None
    ) -> Release:
        folder = Path(artifact_dir)
        try:
            artifact = load_artifact(folder)  # metadata wajib dan konsistensi (BR-23)
        except ArtifactError as err:
            raise RegistryError(f"artefak ditolak: {err}") from err
        manifest = self.manifest()
        version = artifact.metadata.version
        if any(item.version == version for item in manifest.releases):
            raise RegistryError(f"versi {version} sudah dirilis; naikkan versi")
        previous = manifest.releases[-1].accuracy if manifest.releases else None
        check_not_worse(accuracy, previous, override)
        files = {
            path.relative_to(folder).as_posix(): _sha256(path)
            for path in sorted(folder.rglob("*"))
            if path.is_file()
        }
        for name in files:
            self.store.put_file(f"registry/{version}/{name}", folder / name)
        release = Release(
            version=version,
            profile_schema_version=artifact.metadata.profile_schema_version,
            experimental=artifact.metadata.experimental,
            released_at=datetime.now(UTC).isoformat(),
            files=files,
            accuracy=accuracy,
            regression_override=override,
        )
        manifest.releases.append(release)
        self.store.put_bytes(MANIFEST_KEY, manifest.model_dump_json(indent=2).encode("utf-8"))
        return release


def registry(settings: Settings) -> Registry:
    return Registry(object_store(settings), settings.artifact_cache)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ceteris_server.registry")
    sub = parser.add_subparsers(dest="command", required=True)
    pub = sub.add_parser("publish", help="rilis artefak ke registry (BR-63)")
    pub.add_argument("--artifact", type=Path, required=True)
    pub.add_argument("--accuracy", type=Path, required=True, help="JSON AccuracyReport")
    pub.add_argument("--override", help="alasan tertulis bila set regresi berbeda")
    sub.add_parser("list", help="daftar rilis")
    args = parser.parse_args(argv)
    settings = Settings()
    if args.command == "publish":
        accuracy = AccuracyReport.model_validate_json(args.accuracy.read_text(encoding="utf-8"))
        cache = Path(tempfile.mkdtemp(prefix="ceteris-registry-"))
        release = RegistryPublisher(object_store(settings), cache).publish(
            args.artifact, accuracy, args.override
        )
        payload: Any = release.model_dump()
    else:
        payload = registry(settings).manifest().model_dump()
    print(json.dumps(payload, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
