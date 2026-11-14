"""Histori dan perbandingan antar-scan (F-L03, US2.1).

Aturan:
- BR-61: laporan scan lama tidak pernah dihitung ulang atau ditimpa. Perbandingan dihitung saat
  diminta dan tidak disimpan.
- BR-62: perbandingan hanya antar-scan dengan versi model yang sama. Bila versinya berbeda, profil
  lama yang tersimpan diestimasi ulang dengan model scan terbaru (fungsi estimasi yang sama dengan
  scan, `ceteris.scan.estimate_from_profile`), dan perbedaan versinya disebutkan.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ceteris.artifact import ArtifactError
from ceteris.scan import estimate_from_profile
from ceteris_server.db import Scan, ScanProfileRow
from ceteris_server.registry import Registry, RegistryError


class ScanSummary(BaseModel):
    id: str
    status: Literal["queued", "running", "done", "failed"]
    model_version: str | None
    created_at: datetime
    finished_at: datetime | None
    delta: float | None
    interval_90: tuple[float, float] | None
    status_value: Literal["material", "tidak_material", "tidak_yakin"] | None


class ScanPoint(BaseModel):
    scan_id: str
    model_version: str
    delta: float
    interval_90: tuple[float, float]
    status_value: Literal["material", "tidak_material", "tidak_yakin"]


class Comparison(BaseModel):
    """Scan selesai terbaru dibandingkan scan selesai sebelumnya."""

    basis: Literal["same_model", "reestimated", "unavailable"]
    latest: ScanPoint
    previous: ScanPoint | None
    previous_model_version: str | None
    delta_change: float | None
    status_changed: bool | None
    note: str


class DatasetHistory(BaseModel):
    dataset_id: str
    scans: list[ScanSummary]
    comparison: Comparison | None


def _point(scan: Scan) -> ScanPoint:
    report: dict[str, Any] = scan.report or {}
    lo, hi = report["estimate"]["interval_90"]
    return ScanPoint(
        scan_id=scan.id,
        model_version=str(scan.model_version),
        delta=float(report["estimate"]["delta"]),
        interval_90=(float(lo), float(hi)),
        status_value=report["status"]["value"],
    )


def _summary(scan: Scan) -> ScanSummary:
    point = _point(scan) if scan.status == "done" and scan.report else None
    return ScanSummary(
        id=scan.id,
        status=scan.status,  # type: ignore[arg-type]
        model_version=scan.model_version,
        created_at=scan.created_at,
        finished_at=scan.finished_at,
        delta=point.delta if point else None,
        interval_90=point.interval_90 if point else None,
        status_value=point.status_value if point else None,
    )


def compare(session: Session, registry: Registry, latest: Scan, previous: Scan) -> Comparison:
    now_point = _point(latest)
    if latest.model_version == previous.model_version:
        prev_point = _point(previous)
        return Comparison(
            basis="same_model",
            latest=now_point,
            previous=prev_point,
            previous_model_version=previous.model_version,
            delta_change=now_point.delta - prev_point.delta,
            status_changed=now_point.status_value != prev_point.status_value,
            note=f"kedua scan memakai model {latest.model_version}",
        )
    profile = session.get(ScanProfileRow, previous.id)
    if profile is None:
        return _unavailable(now_point, previous, "profil scan sebelumnya tidak tersimpan")
    try:
        artifact = registry.load(latest.model_version)
        artifact.check_profile(profile.profile_schema_version)
    except (ArtifactError, RegistryError) as err:
        return _unavailable(now_point, previous, f"estimasi ulang tidak bisa dilakukan: {err}")
    threshold = float((previous.report or {})["status"]["threshold"])
    est = estimate_from_profile(
        profile.features, artifact, threshold, leakage_flagged=profile.leakage_flagged
    )
    prev_point = ScanPoint(
        scan_id=previous.id,
        model_version=str(latest.model_version),
        delta=est.delta,
        interval_90=est.interval,
        status_value=est.status,
    )
    return Comparison(
        basis="reestimated",
        latest=now_point,
        previous=prev_point,
        previous_model_version=previous.model_version,
        delta_change=now_point.delta - prev_point.delta,
        status_changed=now_point.status_value != prev_point.status_value,
        note=(
            f"versi model berbeda: scan sebelumnya dibuat dengan {previous.model_version}, "
            f"diestimasi ulang dengan {latest.model_version} dari profil tersimpan (BR-62); "
            "laporan aslinya tidak diubah (BR-61)"
        ),
    )


def _unavailable(now_point: ScanPoint, previous: Scan, reason: str) -> Comparison:
    return Comparison(
        basis="unavailable",
        latest=now_point,
        previous=None,
        previous_model_version=previous.model_version,
        delta_change=None,
        status_changed=None,
        note=reason,
    )


def dataset_history(session: Session, registry: Registry, dataset_id: str) -> DatasetHistory:
    scans = list(
        session.scalars(
            select(Scan)
            .where(Scan.dataset_id == dataset_id, Scan.deleted_at.is_(None))
            .order_by(Scan.created_at.desc(), Scan.id.desc())
        )
    )
    done = [s for s in scans if s.status == "done" and s.report]
    comparison = compare(session, registry, done[0], done[1]) if len(done) >= 2 else None
    return DatasetHistory(
        dataset_id=dataset_id, scans=[_summary(s) for s in scans], comparison=comparison
    )
