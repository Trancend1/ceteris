"""Uji integrasi dengan Postgres, Redis, dan object store S3 sungguhan (marker `integration`).

Jalankan setelah `docker compose -f compose.yaml -f compose.test.yaml up -d`, dengan variabel
`CETERIS_*` menunjuk ke layanan itu dari host, misalnya:

    CETERIS_DATABASE_URL=postgresql+pg8000://ceteris:ceteris-dev@localhost:5432/ceteris
    CETERIS_REDIS_URL=redis://localhost:6379/0
    CETERIS_OBJECT_STORE=s3://ceteris-it  CETERIS_S3_ENDPOINT=localhost:8333
    CETERIS_S3_ACCESS_KEY=ceteris  CETERIS_S3_SECRET_KEY=ceteris-dev-secret
    uv run pytest -m integration tests/test_server_integration.py

`compose.test.yaml` membuka port layanan ke host. Bucket `ceteris-it` dibuat lewat klien S3 saat
konteks dibangun (ADR 0019), sehingga uji ini juga menguji pembuatan bucket.
"""

from __future__ import annotations

import io
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ceteris.scan import ScanReport
from ceteris_server.api import create_app
from ceteris_server.objects import object_store
from ceteris_server.registry import RegistryPublisher
from ceteris_server.settings import Settings
from ceteris_server.worker import RQQueue, build_context
from tests.conftest import SmallPilot
from tests.test_scan import _dirty_frame
from tests.test_server import ACCURACY

pytestmark = pytest.mark.integration


def test_full_scan_through_postgres_redis_and_s3(small_pilot: SmallPilot) -> None:
    from rq import SimpleWorker

    settings = Settings()
    assert settings.redis_url and settings.object_store.startswith("s3://")
    publisher = RegistryPublisher(object_store(settings), Path(tempfile.mkdtemp()))
    versions = {r.version for r in publisher.manifest().releases}
    if "0.0.1-test" not in versions:
        publisher.publish(
            small_pilot.artifact_dir, ACCURACY, override="uji integrasi" if versions else None
        )
    queue = RQQueue(settings.redis_url, name="scans-it")
    context = build_context(
        Settings(**{**settings.__dict__, "artifact_version": "0.0.1-test"}), queue
    )
    client = TestClient(create_app(context))
    frame, _ = _dirty_frame(small_pilot, 0)
    buffer = io.BytesIO()
    frame.to_parquet(buffer, index=False)
    dataset = client.post("/v1/datasets", json={"name": "it", "target": "class"}).json()
    scan = client.post(
        "/v1/scans",
        data={"dataset_id": dataset["id"]},
        files={"file": ("d.parquet", buffer.getvalue())},
    ).json()
    assert scan["status"] == "queued"
    SimpleWorker([queue.queue], connection=queue.queue.connection).work(burst=True)
    assert client.get(f"/v1/scans/{scan['id']}").json()["status"] == "done"
    ScanReport.model_validate(client.get(f"/v1/scans/{scan['id']}/report").json())
