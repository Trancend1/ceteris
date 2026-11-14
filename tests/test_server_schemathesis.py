"""Uji properti API `/v1` dengan schemathesis (execution-plan Phase 7).

Setiap respons harus sesuai skema OpenAPI-nya dan tidak boleh berstatus 5xx, kecuali 501 untuk
laporan HTML yang memang menyusul di Phase 11. Antrian hanya mencatat job, sehingga uji ini tidak
menjalankan scan.
"""

from __future__ import annotations

import pytest
import schemathesis
from hypothesis import HealthCheck, settings
from schemathesis.specs.openapi.checks import positive_data_acceptance

from ceteris_server.api import create_app
from ceteris_server.settings import Settings
from ceteris_server.worker import RecordingQueue, build_context


@pytest.fixture(scope="module")
def api_schema(tmp_path_factory: pytest.TempPathFactory) -> schemathesis.Schema:
    root = tmp_path_factory.mktemp("st")
    context = build_context(
        Settings(
            database_url=f"sqlite:///{(root / 'meta.db').as_posix()}",
            redis_url="",
            object_store=f"local:{(root / 'objects').as_posix()}",
            artifact_version="",
            artifact_cache=root / "cache",
        ),
        RecordingQueue(),
    )
    from ceteris_server.auth import create_user, issue_token

    with context.db.session() as session:
        user = create_user(session, "st@example.com", "kata-sandi-uji-12")
        TOKEN["value"] = issue_token(session, user, "api", "schemathesis").token
    return schemathesis.openapi.from_asgi("/openapi.json", create_app(context))


TOKEN: dict[str, str] = {}
schema = schemathesis.pytest.from_fixture("api_schema")


@schema.parametrize()
@settings(max_examples=25, deadline=None, suppress_health_check=list(HealthCheck))
def test_api_conforms_to_its_openapi(case: schemathesis.Case) -> None:
    response = case.call(headers={"Authorization": f"Bearer {TOKEN['value']}"})
    if case.path.endswith("/report") and response.status_code == 501:
        return
    # Penolakan kontrak input (BR-10, ADR 0016 K5) tidak bisa dinyatakan di skema multipart:
    # format berkas dari ekstensi nama berkas dan batas ukuran unggahan.
    contract_rejection = case.path == "/v1/scans" and response.status_code in (413, 415)
    excluded = [positive_data_acceptance] if contract_rejection else []
    case.validate_response(response, excluded_checks=excluded)
