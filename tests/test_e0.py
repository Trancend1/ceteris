"""Uji noise floor tersimpan (BR-04, F-S06) dan perencana pilot E0 (Phase 3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ceteris.corpus import CorpusFilter, PreparedDataset, prepare_dataset
from ceteris.corrupt import LabelUniform, load_corruption_grid
from ceteris.dqprofile import estimate_noise_floor, noise_floor_seeds
from ceteris.experiment import (
    config_id_for,
    dirty_train,
    e0_tasks,
    estimate_run_noise_floor,
    load_e0_protocol,
    measure_dataset_noise_floor,
    run_corruption,
)
from ceteris.seeding import run_seed
from ceteris.store import RecordExistsError, RunStore, StoreError
from ceteris.train import LearnerSpec
from tests.conftest import FakeFetcher, fake_provenance, make_frame

SMALL = CorpusFilter(min_rows=100, max_rows=5000, min_class_count=5)
CONFIGS = Path(__file__).resolve().parents[1] / "configs"


@pytest.fixture
def prepared(tmp_path: Path) -> PreparedDataset:
    return prepare_dataset(42, FakeFetcher({42: make_frame(n=500)}), tmp_path / "corpus", SMALL)


def test_f_s06_noise_floor_seeds_are_fixed_distinct_and_prefix_stable() -> None:
    """AC-12: seed probe tetap; jumlah seed lebih kecil adalah awalan dari yang lebih besar."""
    ten = noise_floor_seeds(10)
    assert ten == noise_floor_seeds(10)
    assert len(set(ten)) == 10
    assert noise_floor_seeds(3) == ten[:3]
    with pytest.raises(ValueError, match="dua seed"):
        noise_floor_seeds(1)


def test_br04_measured_noise_floor_is_stored_per_seed(
    prepared: PreparedDataset, fast_learner: LearnerSpec, tmp_path: Path
) -> None:
    store = RunStore(tmp_path / "runs")
    aucs = measure_dataset_noise_floor(prepared, fast_learner, store, 3, fake_provenance)
    rows = store.read("noise_floor").sort_values("seed_index")
    assert rows["kind"].tolist() == ["measured"] * 3
    assert rows["auc"].tolist() == pytest.approx(aucs)
    assert rows["source_run_id"].isna().all()
    assert rows["git_commit"].eq(fake_provenance().git_commit).all()
    assert len(set(aucs)) > 1  # bagging: seed berbeda memberi AUC berbeda (ADR 0009 K1)
    with pytest.raises(RecordExistsError):
        measure_dataset_noise_floor(prepared, fast_learner, store, 3, fake_provenance)


def test_br04_estimated_noise_floor_uses_the_runs_dirty_data(
    prepared: PreparedDataset, fast_learner: LearnerSpec, tmp_path: Path
) -> None:
    """Noise floor estimasi dihitung pada data kotor yang sama persis dengan run-nya."""
    store = RunStore(tmp_path / "runs")
    specs = [LabelUniform(level=0.2)]
    row = run_corruption(prepared, specs, 0, fast_learner, store, fake_provenance)
    aucs = estimate_run_noise_floor(prepared, specs, 0, fast_learner, store, 3, fake_provenance)
    seed = run_seed(42, config_id_for(specs, fast_learner), 0)
    _, result = dirty_train(prepared, specs, seed, fast_learner)
    assert len(result.frame) == row["n_train_dirty"]
    direct = estimate_noise_floor(
        result.frame, prepared.target, learner=fast_learner, seeds=noise_floor_seeds(3)
    )
    assert aucs == direct
    stored = store.read("noise_floor")
    assert stored["kind"].eq("estimated").all()
    assert stored["source_run_id"].eq(row["run_id"]).all()
    with pytest.raises(RecordExistsError):
        estimate_run_noise_floor(prepared, specs, 0, fast_learner, store, 3, fake_provenance)


def test_noise_floor_row_requires_commit(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    with pytest.raises(StoreError, match="git_commit"):
        store.write_noise_floor({"nf_id": "x", "git_commit": ""})


def test_e0_protocol_matches_owner_decision() -> None:
    """Keputusan 12/11/2026: 5 dataset, 5 seed, noise floor 10 seed, 10 kandidat campuran."""
    protocol = load_e0_protocol(CONFIGS / "e0.yaml")
    assert sorted(protocol.datasets) == [3, 1489, 1590, 40701, 40984]
    assert protocol.seeds_per_config == 5
    assert protocol.measured_seeds == protocol.estimated_seeds == 10
    mixtures = protocol.mixtures()
    assert len(mixtures) == 10
    assert all(2 <= len(mix) <= 3 for mix in mixtures)


def test_e0_tasks_cover_every_config_seed_and_dataset() -> None:
    protocol = load_e0_protocol(CONFIGS / "e0.yaml")
    singles = load_corruption_grid(CONFIGS / "corruption.yaml").singles
    tasks = e0_tasks(protocol, singles)
    configs = len(singles) + len(protocol.mixtures())
    per_config = (
        protocol.seeds_per_config
        + len(protocol.estimated_seed_indices)
        + len(protocol.baseline_d_seed_indices)
    )
    per_dataset = 1 + configs * per_config
    assert protocol.baseline_d_seed_indices == [0]  # G2-7: 1 seed × semua konfigurasi
    assert len(singles) == 45
    assert len(tasks) == per_dataset * len(protocol.datasets)
    runs = [t for t in tasks if t.kind == "run"]
    assert len(runs) == len({(t.dataset_id, t.specs_json, t.seed_index) for t in runs})
    assert sum(t.kind == "nf_measured" for t in tasks) == len(protocol.datasets)


def test_g2_7_baseline_d_is_stored_once_per_run(
    prepared: PreparedDataset, fast_learner: LearnerSpec, tmp_path: Path
) -> None:
    from ceteris.experiment import run_baseline_d

    store = RunStore(tmp_path / "runs")
    specs = [LabelUniform(level=0.2)]
    run = run_corruption(prepared, specs, 0, fast_learner, store, fake_provenance)
    row = run_baseline_d(prepared, specs, 0, fast_learner, store, fake_provenance)
    assert row["run_id"] == run["run_id"]
    stored = store.read("baseline_d_run")
    assert len(stored) == 1 and stored.loc[0, "git_commit"] == fake_provenance().git_commit
    with pytest.raises(RecordExistsError):
        run_baseline_d(prepared, specs, 0, fast_learner, store, fake_provenance)
