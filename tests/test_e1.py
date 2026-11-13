"""Uji protokol korpus penuh E1 dan ablation H2b (Phase 4; ADR 0006, ADR 0011)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ceteris.corpus import CorpusFilter, PreparedDataset, prepare_dataset
from ceteris.corrupt import DuplicateExact, LabelUniform, MissingMCAR, load_corruption_grid
from ceteris.experiment import (
    E0Protocol,
    e0_tasks,
    load_e0_protocol,
    run_ablation,
    run_corruption,
)
from ceteris.recovery import KIND_TO_FINDING
from ceteris.store import RecordExistsError, RunStore
from ceteris.train import LearnerSpec
from tests.conftest import FakeFetcher, fake_provenance, make_frame

SMALL = CorpusFilter(min_rows=100, max_rows=5000, min_class_count=5)
ROOT = Path(__file__).resolve().parents[1]
CONFIGS = ROOT / "configs"


@pytest.fixture
def prepared(tmp_path: Path) -> PreparedDataset:
    return prepare_dataset(42, FakeFetcher({42: make_frame(n=500)}), tmp_path / "corpus", SMALL)


def _passed_corpus_ids() -> set[int]:
    ids: set[int] = set()
    for meta in (ROOT / "data" / "corpus").glob("*/meta.json"):
        payload = json.loads(meta.read_text(encoding="utf-8"))
        if payload["passed"]:
            ids.add(int(payload["dataset_id"]))
    return ids


def test_e1_protocol_follows_the_frozen_analysis_plan() -> None:
    """Rencana analisis bagian 1, 5, 6, dan 7 (P1, P2, P7): 31 dataset, 5 seed, nf 10 vs 5."""
    protocol = load_e1()
    assert len(protocol.datasets) == len(set(protocol.datasets)) == 31
    assert protocol.seeds_per_config == 5
    assert protocol.measured_seeds == 10
    assert protocol.estimated_seeds == 5
    assert protocol.baseline_d_seed_indices == [0]
    assert protocol.ablation_seed_indices == [0, 1, 2, 3, 4]
    assert protocol.mixture_candidates == []  # campuran final dari corruption.yaml (G2-3)
    local = _passed_corpus_ids()
    if local:  # korpus lokal tersedia: protokol = semua dataset yang lolos saringan
        assert set(protocol.datasets) == local


def load_e1() -> E0Protocol:
    return load_e0_protocol(CONFIGS / "e1.yaml")


def test_e1_tasks_use_the_final_grid_and_ablate_only_mixtures() -> None:
    protocol = load_e1()
    grid = load_corruption_grid(CONFIGS / "corruption.yaml")
    tasks = e0_tasks(protocol, grid.singles, grid.mixtures)
    n_configs = len(grid.singles) + len(grid.mixtures)
    assert n_configs == 55
    runs = [t for t in tasks if t.kind == "run"]
    assert len(runs) == 31 * 55 * 5
    ablations = [t for t in tasks if t.kind == "ablation"]
    assert len(ablations) == 31 * 10 * 5
    assert all(len(json.loads(t.specs_json or "[]")) > 1 for t in ablations)
    assert sum(t.kind == "nf_estimated" for t in tasks) == 31 * 55
    assert sum(t.kind == "baseline_d" for t in tasks) == 31 * 55


def test_every_mixture_component_maps_to_a_distinct_finding() -> None:
    """H2b butuh satu temuan per komponen campuran agar urutan temuan bisa dibandingkan."""
    grid = load_corruption_grid(CONFIGS / "corruption.yaml")
    for mix in grid.mixtures:
        findings = [KIND_TO_FINDING[spec.kind] for spec in mix]
        assert len(findings) == len(set(findings))


def test_h2b_ablation_removes_one_component_and_keeps_the_rest(
    prepared: PreparedDataset, fast_learner: LearnerSpec, tmp_path: Path
) -> None:
    """auc_full sama dengan auc_dirty run; menghapus komponen memberi baris per komponen (BR-80)."""
    store = RunStore(tmp_path / "runs")
    specs = [LabelUniform(level=0.2), MissingMCAR(level=0.2), DuplicateExact(level=0.2)]
    run = run_corruption(prepared, specs, 0, fast_learner, store, fake_provenance)
    rows = run_ablation(prepared, specs, 0, fast_learner, store, fake_provenance)
    assert len(rows) == 3
    assert {r["removed_kind"] for r in rows} == {s.kind for s in specs}
    for row in rows:
        assert row["run_id"] == run["run_id"]
        assert row["auc_full"] == pytest.approx(run["auc_dirty"], abs=1e-12)
        assert row["gain"] == pytest.approx(row["auc_ablated"] - row["auc_full"])
        assert row["affected_row_frac_ablated"] <= run["affected_row_frac"] + 1e-12
    assert 0.0 < rows[0]["missing_row_frac_full"] <= 1.0
    stored = store.read("ablation_run")
    assert len(stored) == 3
    with pytest.raises(RecordExistsError):
        run_ablation(prepared, specs, 0, fast_learner, store, fake_provenance)


def test_h2b_ablation_is_deterministic(
    prepared: PreparedDataset, fast_learner: LearnerSpec, tmp_path: Path
) -> None:
    """BR-84: ablation yang sama dua kali memberi AUC identik."""
    specs = [LabelUniform(level=0.2), MissingMCAR(level=0.2)]
    first = run_ablation(
        prepared, specs, 1, fast_learner, RunStore(tmp_path / "a"), fake_provenance
    )
    second = run_ablation(
        prepared, specs, 1, fast_learner, RunStore(tmp_path / "b"), fake_provenance
    )
    assert [r["auc_ablated"] for r in first] == [r["auc_ablated"] for r in second]


def test_ablation_rejects_single_configs(
    prepared: PreparedDataset, fast_learner: LearnerSpec, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="campuran"):
        run_ablation(
            prepared,
            [LabelUniform(level=0.1)],
            0,
            fast_learner,
            RunStore(tmp_path),
            fake_provenance,
        )
