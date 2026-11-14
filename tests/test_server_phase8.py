"""Uji Phase 8: login dan token (US8.1), histori dan perbandingan (US2.1), migrasi (ADR 0020).

Aturan: BR-61 (scan lama tidak dihitung ulang), BR-62 (perbandingan hanya pada versi model yang
sama; bila berbeda, profil lama diestimasi ulang dan perbedaan versinya disebutkan), NFR-5 dan
NFR-9 (kata sandi dan token tidak ditulis ke log), AC-6 (profil tersimpan tanpa data mentah).
"""

from __future__ import annotations

import logging
import shutil
from datetime import UTC, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect

from ceteris.artifact import load_artifact
from ceteris_server.api import create_app
from ceteris_server.auth import (
    SESSION_TTL,
    AuthError,
    create_user,
    hash_password,
    issue_token,
    resolve_token,
)
from ceteris_server.db import ApiToken, Base, Database, Scan, ScanProfileRow, now
from ceteris_server.objects import LocalObjectStore
from ceteris_server.registry import RegistryPublisher
from ceteris_server.worker import RecordingQueue
from tests.conftest import SmallPilot
from tests.test_scan import _dirty_frame
from tests.test_server import ACCURACY, PASSWORD, _context, _upload, authed_client

# --- login dan token (US8.1) ---


def test_us81_endpoints_require_a_valid_bearer_token(
    small_pilot: SmallPilot, tmp_path: Path
) -> None:
    context = _context(tmp_path, small_pilot, queue=RecordingQueue())
    anon = TestClient(create_app(context))
    assert anon.get("/v1/health").status_code == 200  # kesehatan layanan tanpa kredensial
    for method, path in [
        ("get", "/v1/me"),
        ("post", "/v1/datasets"),
        ("get", "/v1/scans/scn_x"),
        ("get", "/v1/datasets/ds_x/scans"),
        ("get", "/v1/tokens"),
    ]:
        response = getattr(anon, method)(path)
        assert response.status_code == 401, path
        assert response.json()["error"]["code"] == "unauthorized"
    bad = anon.get("/v1/me", headers={"Authorization": "Bearer ctr_bukan-token"})
    assert bad.status_code == 401


def test_us81_login_issues_a_12_hour_session_and_logout_revokes_it(
    small_pilot: SmallPilot, tmp_path: Path
) -> None:
    context = _context(tmp_path, small_pilot, queue=RecordingQueue())
    authed_client(context)  # membuat pengguna uji
    client = TestClient(create_app(context))
    wrong = client.post("/v1/auth/login", json={"email": "uji@example.com", "password": "salah"})
    nobody = client.post("/v1/auth/login", json={"email": "x@example.com", "password": PASSWORD})
    assert wrong.status_code == nobody.status_code == 401
    assert wrong.json()["error"]["message"] == nobody.json()["error"]["message"]  # tanpa enumerasi
    login = client.post("/v1/auth/login", json={"email": "UJI@example.com", "password": PASSWORD})
    assert login.status_code == 201
    body = login.json()
    assert body["kind"] == "session" and body["token"].startswith("ctr_")
    headers = {"Authorization": f"Bearer {body['token']}"}
    assert client.get("/v1/me", headers=headers).json()["email"] == "uji@example.com"
    assert client.post("/v1/auth/logout", headers=headers).status_code == 204
    assert client.get("/v1/me", headers=headers).status_code == 401


def test_us81_api_tokens_are_shown_once_listed_by_prefix_and_revocable(
    small_pilot: SmallPilot, tmp_path: Path
) -> None:
    context = _context(tmp_path, small_pilot, queue=RecordingQueue())
    client = authed_client(context)
    created = client.post("/v1/tokens", json={"name": "ci"}).json()
    assert created["kind"] == "api" and created["expires_at"] is None
    listed = client.get("/v1/tokens").json()
    assert all("token" not in item for item in listed)
    assert created["prefix"] in {item["prefix"] for item in listed}
    ci = TestClient(create_app(context))
    ci.headers["Authorization"] = f"Bearer {created['token']}"
    assert ci.get("/v1/me").status_code == 200
    assert client.delete(f"/v1/tokens/{created['id']}").status_code == 204
    assert ci.get("/v1/me").status_code == 401  # dicabut langsung ditolak
    assert client.delete(f"/v1/tokens/{created['id']}").status_code == 404


def test_us81_tokens_are_stored_hashed_and_sessions_expire(
    small_pilot: SmallPilot, tmp_path: Path
) -> None:
    context = _context(tmp_path, small_pilot, queue=RecordingQueue())
    with context.db.session() as session:
        user = create_user(session, "kedaluwarsa@example.com", PASSWORD)
        issued = issue_token(session, user, "session", "login")
        row = session.get(ApiToken, issued.id)
        assert row is not None and issued.token not in (row.token_hash, row.prefix)
        assert row.expires_at is not None
        expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=UTC)
        assert abs(expires - (now() + SESSION_TTL)) < timedelta(minutes=1)
        assert user.password_hash.startswith("$argon2id$") and PASSWORD not in user.password_hash
        row.expires_at = now() - timedelta(seconds=1)
    with context.db.session() as session, pytest.raises(AuthError, match="kedaluwarsa"):
        resolve_token(session, issued.token)


def test_us81_password_policy_and_unique_email(small_pilot: SmallPilot, tmp_path: Path) -> None:
    context = _context(tmp_path, small_pilot, queue=RecordingQueue())
    with pytest.raises(AuthError, match="minimal"):
        hash_password("pendek")
    with context.db.session() as session:
        create_user(session, "sama@example.com", PASSWORD)
        with pytest.raises(AuthError, match="sudah terdaftar"):
            create_user(session, "SAMA@example.com", PASSWORD)


def test_nfr9_secrets_never_reach_the_logs(
    small_pilot: SmallPilot, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    context = _context(tmp_path, small_pilot)
    caplog.set_level(logging.DEBUG)
    client = authed_client(context)
    token = client.headers["Authorization"].removeprefix("Bearer ")
    login = TestClient(create_app(context)).post(
        "/v1/auth/login", json={"email": "uji@example.com", "password": PASSWORD}
    )
    frame, _ = _dirty_frame(small_pilot, 0)
    _upload(client, frame)
    logged = caplog.text
    assert PASSWORD not in logged
    assert token not in logged and login.json()["token"] not in logged


# --- histori dan perbandingan (US2.1, BR-61, BR-62) ---


def test_br62_same_model_comparison_and_profile_without_raw_data(
    small_pilot: SmallPilot, tmp_path: Path
) -> None:
    context = _context(tmp_path, small_pilot)
    client = authed_client(context)
    dataset = client.post("/v1/datasets", json={"name": "churn", "target": "class"}).json()
    frame_a, _ = _dirty_frame(small_pilot, 0)
    frame_b, _ = _dirty_frame(small_pilot, 1)
    first = _upload_to(client, dataset["id"], frame_a)
    second = _upload_to(client, dataset["id"], frame_b)
    history = client.get(f"/v1/datasets/{dataset['id']}/scans").json()
    assert [s["id"] for s in history["scans"]] == [second, first]  # terbaru di atas
    comparison = history["comparison"]
    assert comparison["basis"] == "same_model"
    assert comparison["latest"]["scan_id"] == second
    assert comparison["previous"]["scan_id"] == first
    expected = comparison["latest"]["delta"] - comparison["previous"]["delta"]
    assert comparison["delta_change"] == pytest.approx(expected)
    with context.db.session() as session:
        profile = session.get(ScanProfileRow, first)
        assert profile is not None and set(profile.features) >= {"n_rows", "missing_rate"}
        assert all(isinstance(v, float | int) for v in profile.features.values())  # AC-6


def test_br61_br62_new_model_reestimates_old_profile_without_touching_the_old_report(
    small_pilot: SmallPilot, tmp_path: Path
) -> None:
    context = _context(tmp_path, small_pilot)
    client = authed_client(context)
    dataset = client.post("/v1/datasets", json={"name": "churn", "target": "class"}).json()
    frame, _ = _dirty_frame(small_pilot, 0)
    old_scan = _upload_to(client, dataset["id"], frame)
    with context.db.session() as session:
        before = dict(session.get(Scan, old_scan).report)  # type: ignore[union-attr]
    # Rilis artefak versi baru (salinan dengan versi berbeda) lalu scan ulang.
    newer = _copy_artifact_with_version(small_pilot.artifact_dir, tmp_path / "v2", "0.0.2-test")
    RegistryPublisher(LocalObjectStore(tmp_path / "objects"), tmp_path / "pc2").publish(
        newer, ACCURACY
    )
    new_scan = _upload_to(client, dataset["id"], frame)
    history = client.get(f"/v1/datasets/{dataset['id']}/scans").json()
    comparison = history["comparison"]
    assert comparison["basis"] == "reestimated"
    assert comparison["latest"]["model_version"] == "0.0.2-test"
    assert comparison["previous_model_version"] == "0.0.1-test"
    assert "0.0.1-test" in comparison["note"] and "0.0.2-test" in comparison["note"]
    # Estimasi ulang memakai fungsi estimasi yang sama dengan scan.
    artifact = load_artifact(newer)
    with context.db.session() as session:
        profile = session.get(ScanProfileRow, old_scan)
        assert profile is not None
        assert comparison["previous"]["delta"] == pytest.approx(artifact.predict(profile.features))
        after = dict(session.get(Scan, old_scan).report)  # type: ignore[union-attr]
    assert after == before  # BR-61: laporan lama tidak diubah
    assert history["scans"][0]["id"] == new_scan


def _upload_to(client: TestClient, dataset_id: str, frame: object) -> str:
    import io

    buffer = io.BytesIO()
    frame.to_parquet(buffer, index=False)  # type: ignore[attr-defined]
    response = client.post(
        "/v1/scans",
        data={"dataset_id": dataset_id},
        files={"file": ("d.parquet", buffer.getvalue())},
    )
    assert response.status_code == 202, response.text
    return str(response.json()["id"])


def _copy_artifact_with_version(source: Path, target: Path, version: str) -> Path:
    import json

    shutil.copytree(source, target)
    meta = json.loads((target / "metadata.json").read_text(encoding="utf-8"))
    meta["version"] = version
    (target / "metadata.json").write_text(json.dumps(meta, indent=2, sort_keys=True), "utf-8")
    return target


# --- migrasi (ADR 0020) ---


def test_migrations_create_the_schema_and_upgrade_a_phase7_database(tmp_path: Path) -> None:
    fresh = Database(f"sqlite:///{(tmp_path / 'fresh.db').as_posix()}")
    fresh.migrate()
    fresh.migrate()  # idempoten
    tables = set(inspect(fresh.engine).get_table_names())
    assert {"scan", "scan_profile", "app_user", "api_token", "alembic_version"} <= tables
    # Basis data Phase 7: dibuat create_all tanpa alembic_version dan tanpa tabel Phase 8.
    url = f"sqlite:///{(tmp_path / 'phase7.db').as_posix()}"
    phase7 = [
        Base.metadata.tables[n]
        for n in ("dataset", "model_version", "scan", "finding", "impact_estimate")
    ]
    Base.metadata.create_all(create_engine(url), tables=phase7)
    old = Database(url)
    old.migrate()
    upgraded = set(inspect(old.engine).get_table_names())
    assert {"scan_profile", "app_user", "api_token", "alembic_version"} <= upgraded


# --- kontrak OpenAPI /v1 (G5, NFR-10, AC-10) ---


def test_g5_openapi_v1_matches_the_frozen_snapshot(small_pilot: SmallPilot, tmp_path: Path) -> None:
    """OpenAPI `/v1` dibekukan di G5. Perubahan kontrak harus disengaja: perbarui snapshot,
    catat di ADR, dan perubahan yang merusak hanya di versi mayor (AC-10)."""
    import json

    context = _context(tmp_path, small_pilot, queue=RecordingQueue())
    served = TestClient(create_app(context)).get("/openapi.json").json()
    stored = json.loads(
        (Path(__file__).parent / "contracts" / "openapi_v1.json").read_text(encoding="utf-8")
    )
    assert served == stored
