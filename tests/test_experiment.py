"""Uji orkestrasi run: run_log, determinisme, BR-80, dan registry (F-S01–F-S03, F-S07)."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from ceteris.corpus import CorpusError, CorpusFilter, PreparedDataset, prepare_dataset
from ceteris.corrupt import DuplicateExact, LabelUniform, MissingMCAR, Outlier
from ceteris.experiment import (
    PartitionChangedError,
    config_id_for,
    corpus_row,
    run_corruption,
)
from ceteris.seeding import run_seed
from ceteris.store import RecordExistsError, RunStore
from ceteris.train import LearnerSpec
from tests.conftest import FakeFetcher, fake_provenance, make_frame

SMALL = CorpusFilter(min_rows=100, max_rows=5000, min_class_count=5)


@pytest.fixture
def prepared(tmp_path: Path) -> PreparedDataset:
    return prepare_dataset(42, FakeFetcher({42: make_frame(n=500)}), tmp_path / "corpus", SMALL)


def test_run_writes_run_and_log_with_commit_and_seed(
    prepared: PreparedDataset, fast_learner: LearnerSpec, tmp_path: Path
) -> None:
    store = RunStore(tmp_path / "runs")
    specs = [LabelUniform(level=0.2)]
    row = run_corruption(prepared, specs, 0, fast_learner, store, fake_provenance)
    config_id = config_id_for(specs, fast_learner)
    assert row["seed"] == run_seed(42, config_id, 0)
    assert row["nominal_level"] == 0.2
    assert row["affected_row_frac"] == pytest.approx(0.2, abs=0.005)
    assert row["test_sha256"] == prepared.meta["test_sha256"]
    log = store.read("run_log")
    assert len(log) == 1
    assert log.loc[0, "git_commit"] == fake_provenance().git_commit
    assert log.loc[0, "seed"] == row["seed"]
    assert log.loc[0, "status"] == "ok"
    runs = store.read("corruption_run")
    assert runs.loc[0, "delta_auc"] == pytest.approx(row["delta_auc"])
    assert store.read("experiment_config").loc[0, "config_id"] == config_id


def test_ac12_same_run_in_two_stores_is_identical(
    prepared: PreparedDataset, fast_learner: LearnerSpec, tmp_path: Path
) -> None:
    specs = [DuplicateExact(level=0.1), LabelUniform(level=0.1), MissingMCAR(level=0.2)]
    first = run_corruption(
        prepared, specs, 1, fast_learner, RunStore(tmp_path / "a"), fake_provenance
    )
    second = run_corruption(
        prepared, specs, 1, fast_learner, RunStore(tmp_path / "b"), fake_provenance
    )
    stable = [
        "seed",
        "affected_row_frac",
        "auc_clean",
        "auc_dirty",
        "delta_auc",
        "steps_json",
        "kinds",
    ]
    assert {k: first[k] for k in stable} == {k: second[k] for k in stable}
    assert first["nominal_level"] is None
    assert first["kinds"] == "duplicate_exact,label_uniform,missing_mcar"


def test_config_id_ignores_spec_order(fast_learner: LearnerSpec) -> None:
    a = [Outlier(level=0.1), LabelUniform(level=0.1)]
    assert config_id_for(a, fast_learner) == config_id_for(list(reversed(a)), fast_learner)
    other = fast_learner.model_copy(update={"version": "other"})
    assert config_id_for(a, fast_learner) != config_id_for(a, other)


def test_existing_run_is_not_repeated(
    prepared: PreparedDataset, fast_learner: LearnerSpec, tmp_path: Path
) -> None:
    store = RunStore(tmp_path / "runs")
    run_corruption(prepared, [LabelUniform(level=0.1)], 0, fast_learner, store, fake_provenance)
    with pytest.raises(RecordExistsError):
        run_corruption(prepared, [LabelUniform(level=0.1)], 0, fast_learner, store, fake_provenance)


def test_br80_changed_test_partition_aborts_and_is_logged(
    prepared: PreparedDataset, fast_learner: LearnerSpec, tmp_path: Path
) -> None:
    tampered_meta = {**prepared.meta, "test_sha256": "0" * 64}
    tampered = PreparedDataset(
        prepared.dataset_id, tampered_meta, prepared.frame, prepared.partition
    )
    store = RunStore(tmp_path / "runs")
    with pytest.raises(PartitionChangedError, match="BR-80"):
        run_corruption(tampered, [LabelUniform(level=0.1)], 0, fast_learner, store, fake_provenance)
    log = store.read("run_log")
    assert log.loc[0, "status"] == "failed"
    assert "BR-80" in log.loc[0, "error"]
    assert log.loc[0, "git_commit"] and log.loc[0, "seed"] is not None
    assert store.read("corruption_run").empty


def test_failed_dataset_cannot_be_run(fast_learner: LearnerSpec, tmp_path: Path) -> None:
    failed = prepare_dataset(1, FakeFetcher({1: make_frame(n=40)}), tmp_path / "c", SMALL)
    with pytest.raises(CorpusError, match="tidak lolos"):
        run_corruption(
            failed,
            [LabelUniform(level=0.1)],
            0,
            fast_learner,
            RunStore(tmp_path / "r"),
            fake_provenance,
        )


def test_corpus_row_round_trips_into_store(prepared: PreparedDataset, tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    store.write_corpus_dataset(corpus_row(prepared))
    frame = store.read("corpus_dataset")
    assert frame.loc[0, "licence"] == "Public"
    assert json.loads(frame.loc[0, "reasons"]) == []
    assert frame.loc[0, "test_sha256"] == prepared.meta["test_sha256"]
    assert isinstance(frame, pd.DataFrame)


def test_learner_parameter_change_gives_new_config_id(fast_learner: LearnerSpec) -> None:
    specs = [LabelUniform(level=0.1)]
    tweaked = fast_learner.model_copy(update={"params": {**fast_learner.params, "num_leaves": 15}})
    assert tweaked.version == fast_learner.version
    assert config_id_for(specs, fast_learner) != config_id_for(specs, tweaked)


def test_fast_repeated_failures_are_all_logged(
    prepared: PreparedDataset, fast_learner: LearnerSpec, tmp_path: Path
) -> None:
    tampered = PreparedDataset(
        prepared.dataset_id,
        {**prepared.meta, "test_sha256": "0" * 64},
        prepared.frame,
        prepared.partition,
    )
    store = RunStore(tmp_path / "runs")
    for _ in range(3):
        with pytest.raises(PartitionChangedError):
            run_corruption(
                tampered, [LabelUniform(level=0.1)], 0, fast_learner, store, fake_provenance
            )
    log = store.read("run_log")
    assert len(log) == 3 and log["log_id"].is_unique
    assert set(log["status"]) == {"failed"}


def test_br80_test_partition_mutated_during_run_is_caught(
    prepared: PreparedDataset,
    fast_learner: LearnerSpec,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ceteris import experiment

    original = experiment.measure_delta_auc

    def mutating(spec, train_clean, train_dirty, test, target, seed):  # type: ignore[no-untyped-def]
        result = original(spec, train_clean, train_dirty, test, target, seed)
        test.loc[0, "x0"] = 1e9
        return result

    monkeypatch.setattr(experiment, "measure_delta_auc", mutating)
    store = RunStore(tmp_path / "runs")
    with pytest.raises(PartitionChangedError, match="selama run"):
        run_corruption(prepared, [LabelUniform(level=0.1)], 0, fast_learner, store, fake_provenance)
    assert store.read("corruption_run").empty
    assert store.read("run_log").loc[0, "status"] == "failed"


def test_run_records_full_learner_hash(
    prepared: PreparedDataset, fast_learner: LearnerSpec, tmp_path: Path
) -> None:
    from ceteris.experiment import learner_spec_sha256

    store = RunStore(tmp_path / "runs")
    row = run_corruption(
        prepared, [LabelUniform(level=0.1)], 0, fast_learner, store, fake_provenance
    )
    assert row["learner_spec_sha256"] == learner_spec_sha256(fast_learner)
    assert (
        store.read("experiment_config").loc[0, "learner_spec_sha256"] == row["learner_spec_sha256"]
    )
