"""Uji run store, experiment registry, dan provenance (F-S07)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ceteris import store as store_mod
from ceteris.store import (
    RUN_LOG,
    ProvenanceError,
    RecordExistsError,
    RunStore,
    StoreError,
    provenance,
)
from tests.conftest import REPO_ROOT


def log_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {name: None for name in RUN_LOG.names}
    row.update(
        log_id="run_1__1",
        run_id="run_1",
        kind="corruption_run",
        dataset_id=1,
        config_id="cfg",
        seed_index=0,
        seed=42,
        git_commit="abc",
        git_dirty=False,
        status="ok",
    )
    row.update(overrides)
    return row


def test_empty_store_exposes_typed_tables(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    for table in store_mod.TABLES:
        assert store.read(table).empty
    assert list(store.read("run_log").columns) == RUN_LOG.names


def test_run_log_requires_commit_and_seed(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    with pytest.raises(StoreError, match="git_commit"):
        store.write_run_log(log_row(git_commit=None))
    with pytest.raises(StoreError, match="seed"):
        store.write_run_log(log_row(seed=None))
    store.write_run_log(log_row())
    frame = store.read("run_log")
    assert frame.loc[0, "git_commit"] == "abc" and frame.loc[0, "seed"] == 42


def test_records_are_not_overwritten(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    store.write_run_log(log_row())
    with pytest.raises(RecordExistsError):
        store.write_run_log(log_row())


def test_schema_mismatch_is_rejected(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    with pytest.raises(StoreError, match="kolom"):
        store.write_run_log({**log_row(), "unexpected": 1})
    with pytest.raises(StoreError, match="tidak sah"):
        store.write_run_log(log_row(log_id="../escape"))
    with pytest.raises(StoreError, match="tidak dikenal"):
        store.read("nope")


def test_registry_rejects_reused_config_id(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    row = {
        "config_id": "cfg_1",
        "kind": "corruption",
        "spec_json": "[1]",
        "learner_spec_version": "v",
        "learner_spec_sha256": "h",
        "registered_at": "t",
    }
    store.register_config(row)
    store.register_config(row)
    assert len(store.read("experiment_config")) == 1
    with pytest.raises(StoreError, match="isi berbeda"):
        store.register_config({**row, "spec_json": "[2]"})


def test_new_columns_are_read_by_name(tmp_path: Path) -> None:
    """Phase 2 akan menambah kolom profil; rekaman lama tetap terbaca (AC-11)."""
    store = RunStore(tmp_path)
    store.write_run_log(log_row())
    extended = RUN_LOG.append(pa.field("profile_x", pa.float64()))
    pq.write_table(
        pa.Table.from_pylist([{**log_row(log_id="run_2__1"), "profile_x": 1.5}], schema=extended),
        tmp_path / "run_log" / "run_2__1.parquet",
    )
    frame = store.read("run_log").sort_values("log_id").reset_index(drop=True)
    assert len(frame) == 2
    assert frame["profile_x"].isna().tolist() == [True, False]


def test_corpus_dataset_is_upserted(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    row: dict[str, Any] = {name: None for name in store_mod.CORPUS_DATASET.names}
    row.update(dataset_id=3, name="a", passed=True)
    store.write_corpus_dataset(row)
    store.write_corpus_dataset({**row, "name": "b"})
    frame = store.read("corpus_dataset")
    assert frame["name"].tolist() == ["b"]


def test_provenance_reads_git_and_lock() -> None:
    prov = provenance(REPO_ROOT)
    assert len(prov.git_commit) == 40
    assert prov.uv_lock_sha256 is not None and len(prov.uv_lock_sha256) == 64


def test_provenance_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CETERIS_GIT_COMMIT", "deadbeef")
    monkeypatch.setenv("CETERIS_GIT_DIRTY", "true")
    monkeypatch.setenv("CETERIS_IMAGE_DIGEST", "sha256:abc")
    prov = provenance(tmp_path)
    assert (prov.git_commit, prov.git_dirty, prov.image_digest) == ("deadbeef", True, "sha256:abc")
    assert prov.uv_lock_sha256 is None


def test_provenance_without_git_fails_loudly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("CETERIS_GIT_COMMIT", raising=False)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    with pytest.raises(ProvenanceError, match="CETERIS_GIT_COMMIT"):
        provenance(tmp_path)
