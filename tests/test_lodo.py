"""Uji LODO bersarang (F-S11), artefak v1 (F-S08, F-S10), dan analisis H1–H5 (Phase 4).

Run di sini sintetis (fitur profil acak, ΔAUC fungsi fitur + derau) agar uji cepat; isi ΔAUC
bukan hasil eksperimen. Aturan: BR-22, BR-23/AC-9, BR-81, BR-85, AC-4, AC-8.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ceteris.artifact import ArtifactError, load_artifact
from ceteris.dqprofile import FEATURES, NO_FINDING, PROFILE_SCHEMA_VERSION
from ceteris.evaluate import (
    bootstrap_ci,
    dose_response_at,
    h1a,
    h3,
    h4,
    inner_split,
    nested_lodo_fold,
    per_dataset_metrics,
    run_nested_lodo,
)
from ceteris.metamodel import TUNING_GRID, build_artifact_v1, corpus_snapshot_tag, tune
from ceteris.store import LODO_RESULT, RunStore
from ceteris.train import LearnerSpec

N_DATASETS = 6
SMALL_GRID = TUNING_GRID[:2]


def synthetic_runs(n_datasets: int = N_DATASETS, per_dataset: int = 40) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    rows = []
    for d in range(n_datasets):
        shift = rng.normal(0, 0.2)
        for i in range(per_dataset):
            profile = {name: float(rng.uniform(0, 1)) for name in FEATURES}
            for name in NO_FINDING:
                profile[name] = float(rng.uniform(0, 0.3)) if rng.random() < 0.7 else 0.0
            delta = 0.1 * profile["label_noise_rate"] + 0.02 * shift + rng.normal(0, 0.005)
            mixture = i % 4 == 0
            kinds = "label_uniform,missing_mcar" if mixture else "label_uniform"
            level = None if mixture else [0.02, 0.05, 0.10, 0.20, 0.30][i % 5]
            spec = [{"kind": "label_uniform", "level": level or 0.1}]
            rows.append(
                {
                    "run_id": f"run_{100 + d}_{i:03d}",
                    "dataset_id": 100 + d,
                    "kinds": kinds,
                    "spec_json": json.dumps(spec),
                    "nominal_level": level,
                    "affected_row_frac": level or 0.2,
                    "delta_auc": delta,
                    "delta_auc_relative": delta / 0.4,
                    "auc_dirty": 0.9 - delta,
                    "profile_schema_version": PROFILE_SCHEMA_VERSION,
                    **{f"p_{name}": value for name, value in profile.items()},
                }
            )
    return pd.DataFrame(rows)


@pytest.fixture(autouse=True)
def small_grid(monkeypatch: pytest.MonkeyPatch) -> None:
    """Grid tuning dipersempit agar uji cepat; logika tuning tetap sama."""
    import ceteris.metamodel as metamodel

    monkeypatch.setattr(metamodel, "TUNING_GRID", SMALL_GRID)
    original = metamodel.tune

    def fast_tune(runs: pd.DataFrame, features, target="delta_auc", grid=SMALL_GRID, n_folds=3):  # type: ignore[no-untyped-def]
        return original(runs, features, target, grid, n_folds)

    monkeypatch.setattr(metamodel, "tune", fast_tune)
    import ceteris.evaluate as evaluate

    monkeypatch.setattr(evaluate, "tune", fast_tune)


def test_br81_inner_split_excludes_the_test_dataset_and_is_fixed() -> None:
    ids = list(range(31))
    proper, calib = inner_split(ids, 7)
    assert 7 not in proper and 7 not in calib
    assert not set(proper) & set(calib)
    assert len(calib) == 6 and len(proper) == 24  # ≈ 20% / 80% dari 30 dataset latih
    assert (proper, calib) == inner_split(ids, 7)
    assert inner_split(ids, 8) != (proper, calib)
    with pytest.raises(ValueError):
        inner_split([1, 2], 1)


def test_g2_9_tuning_grid_matches_the_frozen_plan() -> None:
    assert len(TUNING_GRID) == 12
    assert {p["num_leaves"] for p in TUNING_GRID} == {7, 15, 31}
    assert {p["learning_rate"] for p in TUNING_GRID} == {0.03, 0.1}
    assert {p["min_data_in_leaf"] for p in TUNING_GRID} == {10, 40}


def test_tune_is_deterministic_and_picks_from_the_grid() -> None:
    runs = synthetic_runs()
    first = tune(runs, FEATURES, grid=SMALL_GRID)
    assert first in [dict(p) for p in SMALL_GRID]
    assert tune(runs, FEATURES, grid=SMALL_GRID) == first


def test_br81_nested_fold_never_sees_the_test_dataset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dataset uji tidak dipakai melatih, men-tuning, atau mengkalibrasi (BR-81)."""
    import ceteris.evaluate as evaluate

    seen: list[set[int]] = []
    runs = synthetic_runs()
    real_tune = evaluate.tune

    def spy_tune(subset: pd.DataFrame, *args, **kwargs):  # type: ignore[no-untyped-def]
        seen.append(set(subset["dataset_id"]))
        return real_tune(subset, *args, **kwargs)

    monkeypatch.setattr(evaluate, "tune", spy_tune)
    result = nested_lodo_fold(runs, 100)
    assert seen and all(100 not in s for s in seen)
    pred = result.predictions
    assert set(pred["dataset_id"]) == {100}
    calib = json.loads(pred["calibration_datasets_json"].iloc[0])
    assert 100 not in calib
    assert set(pred["method"]) == {
        "metamodel",
        "baseline_a_mean",
        "baseline_b_composite",
        "baseline_c_metafeatures",
        "sanity_linear",
        "metamodel_relative",
    }
    assert (pred["lo"] <= pred["hi"]).all()
    assert list(pred.columns) == LODO_RESULT.names
    assert result.predict_seconds_per_estimate > 0
    # Potensi pemulihan hanya untuk run campuran dataset uji (H2b).
    assert set(result.recovery["run_id"]) <= set(
        runs.loc[runs["kinds"].str.contains(","), "run_id"]
    )


def test_nested_lodo_writes_lodo_result_and_builds_a_v1_artifact(
    tmp_path: Path, fast_learner: LearnerSpec
) -> None:
    """Artefak v1: kalibrasi = residu LODO bersarang (BR-22); profil beda versi ditolak (AC-9)."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    from ceteris.store import CORRUPTION_RUN

    runs = synthetic_runs(n_datasets=4, per_dataset=30)
    store = RunStore(tmp_path / "store")
    full = runs.reindex(columns=CORRUPTION_RUN.names)
    full = full.astype(object).where(full.notna(), None)
    for row in full.to_dict("records"):
        pq.write_table(
            pa.Table.from_pylist([row], schema=CORRUPTION_RUN),
            tmp_path / "store" / "corruption_run" / f"{row['run_id']}.parquet",
        )
    run_nested_lodo(tmp_path / "store", workers=1)
    lodo = store.read("lodo_result")
    meta = lodo[lodo["method"] == "metamodel"]
    assert set(meta["run_id"]) == set(runs["run_id"])
    out = tmp_path / "artifact"
    metadata = build_artifact_v1(
        store.read("corruption_run").sort_values("run_id").reset_index(drop=True),
        lodo,
        fast_learner,
        out,
        version="1.0.0-test",
        corpus_snapshot="openml-cc18:4:test",
        ood_percentile=95.0,
        finding_order="potential",
        relative=True,
        experimental=True,
    )
    artifact = load_artifact(out)
    assert artifact.metadata == metadata
    assert metadata.experimental is True  # BR-35: label eksperimental sampai G3
    assert metadata.meta_params in [dict(p) for p in SMALL_GRID]
    assert 0 < metadata.coverage_summary["n_datasets"] == 4
    assert metadata.relative_quantile is not None
    features = {name: float(runs.iloc[0][f"p_{name}"]) for name in FEATURES}
    assert artifact.predict_relative(features) is not None
    assert not any("ood" in name for name in metadata.features)  # AC-8
    with pytest.raises(ArtifactError, match="tidak cocok"):
        artifact.check_profile("0.0-other")  # BR-23, AC-9
    # Kalibrasi diubah → kuantil tidak cocok saat dimuat.
    cal = pd.read_parquet(out / "calibration_relative.parquet")
    cal["score"] = cal["score"] * 3 + 1
    cal.to_parquet(out / "calibration_relative.parquet", index=False)
    with pytest.raises(ArtifactError, match="relatif"):
        load_artifact(out)


def test_corpus_snapshot_tag_changes_with_partition_hashes() -> None:
    corpus = pd.DataFrame(
        {
            "dataset_id": [1, 2],
            "d0_sha256": ["a", "b"],
            "train_sha256": ["c", "d"],
            "test_sha256": ["e", "f"],
        }
    )
    tag = corpus_snapshot_tag(corpus)
    assert tag.startswith("openml-cc18:2:")
    changed = corpus.assign(test_sha256=["e", "x"])
    assert corpus_snapshot_tag(changed) != tag


def _pred(n_datasets: int = 8, better: bool = True) -> pd.DataFrame:
    rng = np.random.default_rng(1)
    rows = []
    for d in range(n_datasets):
        actual = rng.uniform(0, 0.1, 30)
        ood = rng.uniform(0, 5, 30)
        for method, noise in (
            ("metamodel", 0.005),
            ("baseline_a_mean", 0.03),
            ("baseline_b_composite", 0.03),
            ("baseline_c_metafeatures", 0.02),
        ):
            scale = noise if better else 0.03
            err = rng.normal(0, scale, 30) * (1 + ood)
            pred = actual + err
            rows.append(
                pd.DataFrame(
                    {
                        "run_id": [f"r{d}_{i}" for i in range(30)],
                        "dataset_id": d,
                        "method": method,
                        "actual": actual,
                        "predicted": pred,
                        "lo": pred - 0.03,
                        "hi": pred + 0.03,
                        "ood_score": ood,
                    }
                )
            )
    return pd.concat(rows, ignore_index=True)


def test_br85_metrics_are_per_dataset_and_h1a_uses_holm_over_three() -> None:
    per_ds = per_dataset_metrics(_pred())
    assert len(per_ds) == 8 * 4
    result = h1a(per_ds)
    assert [c["baseline"] for c in result["comparisons"]] == [
        "baseline_a_mean",
        "baseline_b_composite",
        "baseline_c_metafeatures",
    ]
    assert all(c["p_holm"] >= c["p"] for c in result["comparisons"])
    assert result["passed"] is True
    worse = h1a(per_dataset_metrics(_pred(better=False)))
    assert worse["passed"] is False


def test_h3_and_h4_follow_the_analysis_plan() -> None:
    pred = _pred()
    out = h3(per_dataset_metrics(pred))
    assert out["n_datasets"] == 8
    assert 0 <= out["ci95"][0] <= out["share"] <= out["ci95"][1] <= 1
    ood = h4(pred)
    assert ood["spearman"] > 0  # galat sintetis membesar seiring skor OOD
    assert ood["ci95"][0] <= ood["spearman"] <= ood["ci95"][1]


def test_bootstrap_ci_is_seeded() -> None:
    values = np.arange(20, dtype="float64")
    assert bootstrap_ci(values) == bootstrap_ci(values)
    lo, hi = bootstrap_ci(values)
    assert lo <= np.median(values) <= hi


def test_h2_dose_response_interpolates_at_ten_percent_affected() -> None:
    """BR-82: ΔAUC dibandingkan pada affected_row_frac yang sama; titik (0, 0) = tanpa korupsi."""
    runs = pd.DataFrame(
        {
            "dataset_id": 1,
            "kinds": "label_uniform",
            "spec_json": json.dumps([{"kind": "label_uniform", "level": 0.1}]),
            "nominal_level": [0.05, 0.2],
            "affected_row_frac": [0.05, 0.2],
            "delta_auc": [0.01, 0.04],
        }
    )
    out = dose_response_at(runs, 0.10)
    assert out["delta_at"].iloc[0] == pytest.approx(0.02)
    beyond = dose_response_at(runs, 0.5)
    assert np.isnan(beyond["delta_at"].iloc[0])
