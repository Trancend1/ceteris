"""Uji platform R1 Phase 7: registry (F-L04), API dan worker (F-L01).

Aturan dan batasan: BR-23, BR-63 (registry), AC-4 (worker hanya membaca registry), AC-5
(`ScanReport` identik di CLI, Python API, dan REST), AC-6 (tanpa data mentah di metadata store),
NFR-2 (p95 endpoint sinkron ≤ 300 ms), NFR-9 (trace berkorelasi), ADR 0016 K5 (batas unggahan) dan
K6 (tanpa alias draf awal).
"""

from __future__ import annotations

import io
import json
import shutil
import statistics
import time
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from ceteris.scan import ScanReport, scan_file
from ceteris_server.api import create_app
from ceteris_server.db import Base, Finding, ImpactEstimate, Scan
from ceteris_server.objects import LocalObjectStore, ObjectStoreError
from ceteris_server.registry import (
    AccuracyReport,
    Registry,
    RegistryError,
    RegistryPublisher,
    check_not_worse,
)
from ceteris_server.settings import Settings
from ceteris_server.worker import RecordingQueue, ServerContext, SyncQueue, build_context
from tests.conftest import SmallPilot
from tests.test_scan import _dirty_frame

ACCURACY = AccuracyReport(
    regression_set="test:2",
    mae=0.004,
    coverage_in_range_share=0.5,
    n_datasets=2,
    source="uji",
)


def _settings(root: Path, **overrides: object) -> Settings:
    base = Settings(
        database_url=f"sqlite:///{(root / 'meta.db').as_posix()}",
        redis_url="",
        object_store=f"local:{(root / 'objects').as_posix()}",
        artifact_version="",
        artifact_cache=root / "cache",
    )
    return Settings(**{**base.__dict__, **overrides})  # type: ignore[arg-type]


def _context(
    root: Path, pilot: SmallPilot, queue: object | None = None, **overrides: object
) -> ServerContext:
    settings = _settings(root, **overrides)
    publisher = RegistryPublisher(LocalObjectStore(root / "objects"), root / "publish-cache")
    if not publisher.manifest().releases:
        publisher.publish(pilot.artifact_dir, ACCURACY)
    return build_context(settings, queue or SyncQueue())  # type: ignore[arg-type]


PASSWORD = "kata-sandi-uji-12"


def authed_client(context: ServerContext, email: str = "uji@example.com") -> TestClient:
    """Klien API yang sudah membawa token API pengguna uji (US8.1)."""
    from ceteris_server.auth import create_user, issue_token
    from ceteris_server.db import User

    with context.db.session() as session:
        user = session.query(User).filter_by(email=email).one_or_none()
        if user is None:
            user = create_user(session, email, PASSWORD)
        token = issue_token(session, user, "api", "uji").token
    client = TestClient(create_app(context))
    client.headers["Authorization"] = f"Bearer {token}"
    return client


def _upload(client: TestClient, frame: pd.DataFrame, name: str = "data.parquet") -> dict:
    dataset = client.post("/v1/datasets", json={"name": "churn", "target": "class"}).json()
    buffer = io.BytesIO()
    if name.endswith(".csv"):
        frame.to_csv(buffer, index=False)
    else:
        frame.to_parquet(buffer, index=False)
    response = client.post(
        "/v1/scans",
        data={"dataset_id": dataset["id"]},
        files={"file": (name, buffer.getvalue(), "application/octet-stream")},
        headers={"x-request-id": "trace-abc"},
    )
    assert response.status_code == 202, response.text
    return response.json()


# --- registry (F-L04, BR-63, AC-4) ---


def test_br63_release_is_rejected_when_worse_on_the_same_regression_set() -> None:
    better = ACCURACY.model_copy(update={"mae": 0.003})
    check_not_worse(better, ACCURACY, None)
    with pytest.raises(RegistryError, match="MAE naik"):
        check_not_worse(ACCURACY.model_copy(update={"mae": 0.005}), ACCURACY, None)
    with pytest.raises(RegistryError, match="coverage"):
        check_not_worse(
            ACCURACY.model_copy(update={"coverage_in_range_share": 0.4}), ACCURACY, None
        )


def test_br63_new_regression_set_needs_a_written_reason() -> None:
    other = ACCURACY.model_copy(update={"regression_set": "holdout:15", "mae": 0.02})
    with pytest.raises(RegistryError, match="alasan tertulis"):
        check_not_worse(other, ACCURACY, None)
    check_not_worse(other, ACCURACY, "epoch 1 memakai holdout baru")


def test_registry_publish_fetch_and_verify(small_pilot: SmallPilot, tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "objects")
    publisher = RegistryPublisher(store, tmp_path / "pc")
    release = publisher.publish(small_pilot.artifact_dir, ACCURACY)
    assert release.version == "0.0.1-test"
    with pytest.raises(RegistryError, match="sudah dirilis"):
        publisher.publish(small_pilot.artifact_dir, ACCURACY)
    reader = Registry(store, tmp_path / "cache")
    assert not hasattr(reader, "publish")  # AC-4: pembaca registry tidak bisa menulis
    artifact = reader.load()
    assert artifact.metadata.version == release.version
    # Berkas yang rusak di object store terdeteksi lewat SHA-256 manifest.
    (tmp_path / "objects" / "registry" / release.version / "model.txt").write_text("rusak")
    shutil.rmtree(tmp_path / "cache")
    with pytest.raises(RegistryError, match="tidak cocok"):
        reader.fetch()


def test_br23_registry_rejects_an_incomplete_artifact(
    tmp_path: Path, small_pilot: SmallPilot
) -> None:
    broken = tmp_path / "broken"
    shutil.copytree(small_pilot.artifact_dir, broken)
    (broken / "calibration.parquet").unlink()
    publisher = RegistryPublisher(LocalObjectStore(tmp_path / "objects"), tmp_path / "pc")
    with pytest.raises(RegistryError, match="artefak ditolak"):
        publisher.publish(broken, ACCURACY)


def test_object_store_rejects_path_traversal(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path)
    for key in ("../x", "/abs", "a/../../b", "a\\b"):
        with pytest.raises(ObjectStoreError):
            store.put_bytes(key, b"x")


# --- API dan worker (F-L01) ---


def test_ac5_rest_report_is_identical_to_cli(small_pilot: SmallPilot, tmp_path: Path) -> None:
    """AC-5: `ScanReport` dari REST sama dengan dari `scan_file` (CLI dan Python API)."""
    context = _context(tmp_path, small_pilot)
    client = authed_client(context)
    frame, _ = _dirty_frame(small_pilot, 0)
    created = _upload(client, frame)
    scan_id = created["id"]
    status = client.get(f"/v1/scans/{scan_id}").json()
    assert status["status"] == "done", status
    assert status["model_version"] == "0.0.1-test"
    rest = ScanReport.model_validate(client.get(f"/v1/scans/{scan_id}/report").json())
    local = tmp_path / "local.parquet"
    frame.to_parquet(local, index=False)
    cli = scan_file(local, "class", small_pilot.artifact_dir, scan_id)
    assert rest.model_dump() == cli.model_dump()
    assert any(w.startswith("outside_corpus_range:") for w in rest.input_warnings)  # K5


def test_ac6_metadata_store_holds_no_raw_rows(small_pilot: SmallPilot, tmp_path: Path) -> None:
    """AC-6: metadata store hanya berisi hasil agregat; snapshot ada di object store."""
    context = _context(tmp_path, small_pilot)
    client = authed_client(context)
    frame, _ = _dirty_frame(small_pilot, 0)
    scan_id = _upload(client, frame)["id"]
    with context.db.session() as session:
        scan = session.get(Scan, scan_id)
        assert scan is not None and scan.snapshot_uri.startswith("local://snapshots/")
        assert context.store.exists(scan.snapshot_key)
        n_findings = session.query(Finding).filter_by(scan_id=scan_id).count()
        estimate = session.query(ImpactEstimate).filter_by(scan_id=scan_id, finding_id=None).one()
        assert n_findings == len(scan.report["findings"])
        assert estimate.delta == scan.report["estimate"]["delta"]
    columns = {c.name for table in Base.metadata.tables.values() for c in table.columns}
    sample_values = {str(v) for v in frame["c0"].unique()}
    assert not sample_values & columns
    dumped = json.dumps(scan.report)
    assert not any(f'"{v}"' in dumped for v in sample_values)


def test_input_contract_failure_is_reported_not_raised(
    small_pilot: SmallPilot, tmp_path: Path
) -> None:
    context = _context(tmp_path, small_pilot)
    client = authed_client(context)
    frame = pd.DataFrame({"x": range(50), "class": ["a"] * 50})  # satu kelas: BR-11
    scan = _upload(client, frame)
    status = client.get(f"/v1/scans/{scan['id']}").json()
    assert status["status"] == "failed"
    assert status["error"]["code"] == "input_contract"
    assert any("BR-11" in d for d in status["error"]["details"])
    report = client.get(f"/v1/scans/{scan['id']}/report")
    assert report.status_code == 409 and report.json()["error"]["code"] == "not_ready"


def test_api_errors_use_the_error_envelope(small_pilot: SmallPilot, tmp_path: Path) -> None:
    context = _context(tmp_path, small_pilot, queue=RecordingQueue())
    client = authed_client(context)
    missing = client.get("/v1/scans/scn_nope")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"
    bad = client.post("/v1/datasets", json={"name": ""})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "validation"
    dataset = client.post("/v1/datasets", json={"name": "d", "target": "class"}).json()
    xlsx = client.post(
        "/v1/scans", data={"dataset_id": dataset["id"]}, files={"file": ("a.xlsx", b"x")}
    )
    assert xlsx.status_code == 415 and xlsx.json()["error"]["code"] == "input_contract"
    nods = client.post("/v1/scans", data={"dataset_id": "ds_x"}, files={"file": ("a.csv", b"x")})
    assert nods.status_code == 404
    html = client.get("/v1/scans/scn_nope/report", params={"format": "html"})
    assert html.status_code == 501
    # ADR 0016 K6: alias draf awal tidak ada.
    assert client.post("/v1/scan").status_code == 404
    assert client.get("/v1/report/x").status_code == 404


def test_k5_upload_above_the_limit_is_rejected(small_pilot: SmallPilot, tmp_path: Path) -> None:
    queue = RecordingQueue()
    context = _context(tmp_path, small_pilot, queue=queue, max_upload_bytes=1000)
    client = authed_client(context)
    dataset = client.post("/v1/datasets", json={"name": "d", "target": "class"}).json()
    big = client.post(
        "/v1/scans", data={"dataset_id": dataset["id"]}, files={"file": ("a.csv", b"x" * 1001)}
    )
    assert big.status_code == 413 and big.json()["error"]["code"] == "upload_too_large"
    assert queue.jobs == []


def test_nfr9_trace_id_reaches_the_job(small_pilot: SmallPilot, tmp_path: Path) -> None:
    queue = RecordingQueue()
    context = _context(tmp_path, small_pilot, queue=queue)
    client = authed_client(context)
    frame, _ = _dirty_frame(small_pilot, 0)
    scan = _upload(client, frame)
    assert scan["status"] == "queued"
    assert queue.jobs == [(scan["id"], "trace-abc")]
    assert client.get("/v1/health").headers["x-request-id"]


def test_nfr2_sync_endpoints_p95_under_300ms(small_pilot: SmallPilot, tmp_path: Path) -> None:
    """NFR-2 (indikatif, in-process): p95 endpoint sinkron ≤ 300 ms."""
    context = _context(tmp_path, small_pilot, queue=RecordingQueue())
    client = authed_client(context)
    dataset = client.post("/v1/datasets", json={"name": "d", "target": "class"}).json()
    scan = client.post(
        "/v1/scans",
        data={"dataset_id": dataset["id"]},
        files={"file": ("a.csv", b"x,class\n1,a\n")},
    ).json()
    timings = []
    for _ in range(100):
        start = time.perf_counter()
        assert client.get(f"/v1/scans/{scan['id']}").status_code == 200
        timings.append(time.perf_counter() - start)
    assert statistics.quantiles(timings, n=20)[-1] < 0.300


def test_report_contract_matches_the_frozen_schema(small_pilot: SmallPilot, tmp_path: Path) -> None:
    """BR-60, AC-10: OpenAPI `/v1` memakai `ScanReport` yang sama dengan snapshot kontrak 1.0."""
    context = _context(tmp_path, small_pilot, queue=RecordingQueue())
    spec = authed_client(context).get("/openapi.json").json()
    route = spec["paths"]["/v1/scans/{scan_id}/report"]["get"]["responses"]["200"]
    assert route["content"]["application/json"]["schema"]["$ref"].endswith("/ScanReport")
    stored = json.loads(
        (Path(__file__).parent / "contracts" / "scan_report_1.0.schema.json").read_text("utf-8")
    )
    served = spec["components"]["schemas"]["ScanReport"]
    assert served["required"] == stored["required"]
    assert set(served["properties"]) == set(stored["properties"])
    assert set(spec["paths"]) == {
        "/v1/health",
        "/v1/auth/login",
        "/v1/auth/logout",
        "/v1/me",
        "/v1/tokens",
        "/v1/tokens/{token_id}",
        "/v1/datasets",
        "/v1/datasets/{dataset_id}/scans",
        "/v1/scans",
        "/v1/scans/{scan_id}",
        "/v1/scans/{scan_id}/report",
    }


def test_rq_queue_runs_the_scan_job(small_pilot: SmallPilot, tmp_path: Path) -> None:
    """Jalur Redis Queue: job `run_scan` dijalankan worker RQ (fakeredis, tanpa Docker)."""
    fakeredis = pytest.importorskip("fakeredis")
    from rq import SimpleWorker

    from ceteris_server.worker import RQQueue

    queue = RQQueue("redis://unused", name="scans-test", connection=fakeredis.FakeRedis())
    context = _context(tmp_path, small_pilot, queue=queue)
    client = authed_client(context)
    frame, _ = _dirty_frame(small_pilot, 0)
    scan = _upload(client, frame)
    assert scan["status"] == "queued"
    job = queue.queue.fetch_job(scan["id"])
    assert job is not None and job.meta["trace_id"] == "trace-abc"
    SimpleWorker([queue.queue], connection=queue.queue.connection).work(burst=True)
    assert client.get(f"/v1/scans/{scan['id']}").json()["status"] == "done"
