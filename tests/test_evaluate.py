"""Uji ringkasan pilot E0 (F-S06, F-S11 versi pilot; BR-04, BR-05, BR-85)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from ceteris.corrupt import parse_spec
from ceteris.dqprofile import noise_floor_value
from ceteris.evaluate import (
    corruption_family,
    e0_report,
    noise_floor_summary,
    project_compute,
    share_above_threshold,
)
from ceteris.experiment import (
    corpus_row,
    estimate_run_noise_floor,
    measure_dataset_noise_floor,
)
from ceteris.store import RunStore
from tests.conftest import SmallPilot, fake_provenance


def test_br04_noise_floor_statistics_on_known_values() -> None:
    aucs = [0.80, 0.81, 0.83]
    assert noise_floor_value(aucs, "range") == pytest.approx(0.03)
    assert noise_floor_value(aucs, "std") == pytest.approx(0.015275, abs=1e-6)
    assert noise_floor_value(aucs, "pairwise_mean") == pytest.approx((0.01 + 0.03 + 0.02) / 3)
    assert noise_floor_value([0.8, 0.8], "pairwise_p95") == 0.0
    with pytest.raises(ValueError, match="dua seed"):
        noise_floor_value([0.8], "range")


def test_summary_uses_seed_prefixes() -> None:
    nf = pd.DataFrame(
        {
            "dataset_id": 1,
            "kind": "measured",
            "source_run_id": None,
            "seed_index": range(10),
            "auc": [0.80, 0.82, 0.81, 0.85, 0.80, 0.80, 0.80, 0.80, 0.80, 0.90],
        }
    )
    summary = noise_floor_summary(nf).set_index(["statistic", "n_seeds"])["value"]
    assert summary[("range", 2)] == pytest.approx(0.02)
    assert summary[("range", 5)] == pytest.approx(0.05)
    assert summary[("range", 10)] == pytest.approx(0.10)


def test_corruption_family_and_share_above_threshold() -> None:
    assert corruption_family("label_uniform") == "label_uniform"
    assert corruption_family("duplicate_exact,label_uniform") == "mixture"
    runs = pd.DataFrame(
        {
            "dataset_id": [1, 1, 2, 2],
            "kinds": ["label_uniform"] * 4,
            "delta_auc": [0.02, 0.005, 0.03, 0.012],
        }
    )
    # dataset 1: T = 0,01; dataset 2: noise floor 0,015 → T = 0,015
    share = share_above_threshold(runs, {1: 0.004, 2: 0.015}).iloc[0]
    assert share["share_median"] == pytest.approx(0.5)
    assert share["share_all_runs"] == pytest.approx(0.5)


def test_projection_scales_with_cost_proxy() -> None:
    pilot = pd.DataFrame(
        {"proxy": [1e4, 1e5, 1e6], "run_seconds": [1.0, 10.0, 100.0], "nf_seconds": [2.0, 20, 200]}
    )
    corpus = pd.DataFrame({"n_rows": [1000], "n_features": [10], "n_classes": [2]})
    out = project_compute(pilot, corpus, runs_per_dataset=3600, nf_per_dataset=1800)
    assert out["run_seconds_slope"] == pytest.approx(1.0)
    assert out["run_seconds_cpu_hours"] == pytest.approx(1.0)
    assert out["nf_seconds_cpu_hours"] == pytest.approx(1.0)


def test_e0_report_reads_everything_from_the_run_store(
    small_pilot: SmallPilot, tmp_path: Path
) -> None:
    root = tmp_path / "runs"
    shutil.copytree(small_pilot.store.root, root)
    store = RunStore(root)
    for dataset in small_pilot.prepared.values():
        measure_dataset_noise_floor(dataset, small_pilot.learner, store, 3, fake_provenance)
    first = small_pilot.runs.iloc[0]
    specs = [parse_spec(item) for item in json.loads(first["spec_json"])]
    estimate_run_noise_floor(
        small_pilot.prepared[int(first["dataset_id"])],
        specs,
        int(first["seed_index"]),
        small_pilot.learner,
        store,
        3,
        fake_provenance,
    )
    for prepared in small_pilot.prepared.values():
        store.write_corpus_dataset(corpus_row(prepared))
    report = e0_report(root)
    assert report["n_runs"] == len(small_pilot.runs)
    assert report["n_failed"] == 0
    assert len(report["noise_floor_measured"]) == 2 * 2 * 4  # 2 dataset × k∈{2,3} × 4 statistik
    assert "range@3" in report["share_above_threshold"]
    methods = {row["method"] for row in report["lodo_pilot"]}
    assert methods == {
        "metamodel",
        "baseline_a_mean",
        "baseline_b_composite",
        "baseline_c_metafeatures",
    }
    json.dumps(report)  # dapat ditulis sebagai JSON
