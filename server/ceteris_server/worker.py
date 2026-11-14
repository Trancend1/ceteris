"""Worker scan: membungkus `ceteris.scan.scan_file` tanpa logika tambahan (F-L01, AC-5).

Worker membaca snapshot dari object store, mengambil artefak dari registry hanya-baca (AC-4),
menjalankan scan, lalu menulis hasil agregat ke metadata store. Data sumber tidak pernah ditulis
(AC-7, BR-70). Antrian: Redis Queue di Docker Compose; antrian sinkron dalam proses untuk
pengembangan dan uji (ADR 0018).
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from ceteris.artifact import ArtifactError
from ceteris.dqprofile import InputContractError
from ceteris.scan import ScanProfile, ScanReport, scan_file_with_profile
from ceteris_server.db import (
    Database,
    Finding,
    ImpactEstimate,
    ModelVersion,
    Scan,
    ScanProfileRow,
    new_id,
    now,
)
from ceteris_server.logs import configure_logging
from ceteris_server.objects import ObjectStore, ObjectStoreError, object_store
from ceteris_server.registry import Registry, RegistryError
from ceteris_server.settings import Settings

log = logging.getLogger("ceteris_server.worker")


class JobQueue(Protocol):
    def enqueue(self, scan_id: str, trace_id: str) -> None: ...


@dataclass
class ServerContext:
    """Dependensi satu proses (API atau worker)."""

    settings: Settings
    db: Database
    store: ObjectStore
    registry: Registry
    queue: JobQueue = field(init=False)


_CONTEXT: ServerContext | None = None


def build_context(settings: Settings | None = None, queue: JobQueue | None = None) -> ServerContext:
    """Buat konteks proses; antrian bawaan dipilih dari `CETERIS_REDIS_URL`."""
    global _CONTEXT
    configure_logging()
    cfg = settings or Settings()
    store = object_store(cfg)
    db = Database(cfg.database_url)
    db.migrate()
    context = ServerContext(cfg, db, store, Registry(store, cfg.artifact_cache))
    context.queue = queue or (RQQueue(cfg.redis_url) if cfg.redis_url else SyncQueue())
    _CONTEXT = context
    return context


def get_context() -> ServerContext:
    return _CONTEXT if _CONTEXT is not None else build_context()


class SyncQueue:
    """Menjalankan job langsung di dalam proses (pengembangan dan uji)."""

    def enqueue(self, scan_id: str, trace_id: str) -> None:
        run_scan(scan_id, trace_id)


class RecordingQueue:
    """Hanya mencatat job, tanpa menjalankannya (uji API yang tidak butuh hasil scan)."""

    def __init__(self) -> None:
        self.jobs: list[tuple[str, str]] = []

    def enqueue(self, scan_id: str, trace_id: str) -> None:
        self.jobs.append((scan_id, trace_id))


class RQQueue:
    """Redis Queue: job `run_scan` dijalankan proses `rq worker scans`."""

    def __init__(self, redis_url: str, name: str = "scans", connection: Any = None) -> None:
        from redis import Redis
        from rq import Queue

        self.queue = Queue(name, connection=connection or Redis.from_url(redis_url))

    def enqueue(self, scan_id: str, trace_id: str) -> None:
        self.queue.enqueue(
            "ceteris_server.worker.run_scan",
            scan_id,
            trace_id,
            job_id=scan_id,
            job_timeout=3600,
            meta={"trace_id": trace_id},
        )


def run_scan(scan_id: str, trace_id: str = "") -> str:
    """Job antrian: jalankan satu scan dan simpan hasilnya. Mengembalikan status akhir."""
    context = get_context()
    extra = {"scan_id": scan_id, "trace_id": trace_id}
    with context.db.session() as session:
        scan = session.get(Scan, scan_id)
        if scan is None:
            log.error("scan tidak ada", extra=extra)
            return "missing"
        scan.status, scan.started_at = "running", now()
        snapshot_key, target = scan.snapshot_key, _target(session, scan)
    log.info("scan mulai", extra=extra)
    try:
        report, profile = _scan(context, snapshot_key, target, scan_id)
    except InputContractError as err:
        return _fail(context, scan_id, "input_contract", str(err), list(err.reasons), extra)
    except (ArtifactError, RegistryError) as err:
        return _fail(context, scan_id, "artifact", str(err), [], extra)
    except ObjectStoreError as err:
        return _fail(context, scan_id, "snapshot", str(err), [], extra)
    except Exception as err:  # galat tak terduga tetap tercatat, bukan hilang diam-diam
        log.exception("scan gagal", extra=extra)
        return _fail(context, scan_id, "internal", type(err).__name__, [], extra)
    _store_report(context, scan_id, report, profile)
    log.info("scan selesai", extra={**extra, "status": report.status.value})
    return "done"


def _target(session: Any, scan: Scan) -> str:
    from ceteris_server.db import Dataset

    dataset = session.get(Dataset, scan.dataset_id)
    return str(dataset.target)


def _scan(
    context: ServerContext, snapshot_key: str, target: str, scan_id: str
) -> tuple[ScanReport, ScanProfile]:
    artifact_dir = context.registry.fetch(context.settings.artifact_version or None)
    suffix = PurePosixPath(snapshot_key).suffix
    with tempfile.TemporaryDirectory(prefix="ceteris-scan-") as tmp:
        local = Path(tmp) / f"snapshot{suffix}"
        context.store.download(snapshot_key, local)
        return scan_file_with_profile(local, target, artifact_dir, scan_id)


def _fail(
    context: ServerContext,
    scan_id: str,
    code: str,
    message: str,
    details: list[str],
    extra: dict[str, str],
) -> str:
    with context.db.session() as session:
        scan = session.get(Scan, scan_id)
        if scan is not None:
            scan.status, scan.finished_at = "failed", now()
            scan.error = {"code": code, "message": message, "details": details}
    log.warning("scan ditolak atau gagal", extra={**extra, "code": code})
    return "failed"


def _store_report(
    context: ServerContext, scan_id: str, report: ScanReport, profile: ScanProfile
) -> None:
    payload = report.model_dump(mode="json")
    model = report.model
    with context.db.session() as session:
        if session.get(ModelVersion, model.version) is None:
            session.add(
                ModelVersion(
                    version=model.version,
                    profile_schema_version=model.profile_schema_version,
                    experimental=model.experimental,
                )
            )
            session.flush()
        scan = session.get(Scan, scan_id)
        if scan is None:
            return
        scan.status, scan.finished_at = "done", now()
        scan.model_version, scan.report = model.version, payload
        session.add(
            ScanProfileRow(
                scan_id=scan_id,
                profile_schema_version=profile.profile_schema_version,
                features=profile.features,
                leakage_flagged=profile.leakage_flagged,
            )
        )
        for rank, item in enumerate(report.findings):
            session.add(
                Finding(
                    id=new_id("fnd"),
                    scan_id=scan_id,
                    issue_type=item.issue_type,
                    column=item.column,
                    rows_affected_pct=item.rows_affected_pct,
                    observed_or_estimated=item.observed_or_estimated,
                    recovery_potential=item.recovery_potential,
                    rank=rank,
                )
            )
        lo, hi = report.estimate.interval_90
        session.add(
            ImpactEstimate(
                id=new_id("est"),
                scan_id=scan_id,
                finding_id=None,
                metric=report.estimate.metric,
                delta=report.estimate.delta,
                lo=lo,
                hi=hi,
                ood_score=report.estimate.ood_score,
                status=report.status.value,
                threshold=report.status.threshold,
                model_version=model.version,
            )
        )
