"""Uji meta-model, baseline (a)–(c), dan artefak pilot (F-S08, F-S09; BR-21, BR-23, AC-8, AC-9)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ceteris.artifact import ArtifactError, load_artifact
from ceteris.dqprofile import FEATURES, NO_FINDING
from ceteris.metamodel import (
    CONTEXT_FEATURES,
    DIRTINESS_FEATURES,
    PROBE_FEATURES,
    CompositeScoreBaseline,
    LightGBMMethod,
    MeanBaseline,
    lodo_predictions,
    pilot_methods,
)
from tests.conftest import SmallPilot


def test_feature_groups_follow_the_thesis_plan() -> None:
    """(c) memakai konteks dan probe saja; (b) memakai indikator kekotoran (nilai tanpa temuan)."""
    assert set(DIRTINESS_FEATURES) == set(NO_FINDING)
    assert not set(CONTEXT_FEATURES + PROBE_FEATURES) & set(DIRTINESS_FEATURES)
    assert CONTEXT_FEATURES == FEATURES[:6]


def test_ac8_ood_score_is_not_a_metamodel_feature(small_pilot: SmallPilot) -> None:
    artifact = load_artifact(small_pilot.artifact_dir)
    assert artifact.metadata.features == list(FEATURES)
    assert not any("ood" in name for name in artifact.metadata.features)


def test_baseline_a_and_b_follow_their_definitions(small_pilot: SmallPilot) -> None:
    runs = small_pilot.runs
    mean = MeanBaseline().fit(runs)
    assert np.allclose(mean.predict(runs), runs["delta_auc"].mean())
    composite = CompositeScoreBaseline().fit(runs)
    scores = composite.score(runs)
    assert ((scores >= 0) & (scores <= 100)).all()
    cleaner = runs.copy()
    for name in DIRTINESS_FEATURES:
        cleaner[f"p_{name}"] = -1.0  # di bawah semua nilai latih: peringkat 0
    assert np.allclose(composite.score(cleaner), 100.0)


def test_br81_lodo_never_trains_on_the_test_dataset(small_pilot: SmallPilot) -> None:
    runs = small_pilot.runs
    seen: list[set[int]] = []

    class Spy(MeanBaseline):
        def fit(self, runs: pd.DataFrame) -> MeanBaseline:
            seen.append(set(runs["dataset_id"]))
            return super().fit(runs)

    out = lodo_predictions(runs, [Spy(name="spy")])
    assert seen == [{43}, {42}]
    assert len(out) == len(runs)
    assert set(out["method"]) == {"spy"}


def test_pilot_methods_produce_predictions_for_every_run(small_pilot: SmallPilot) -> None:
    out = lodo_predictions(small_pilot.runs, pilot_methods())
    assert out.groupby("method").size().eq(len(small_pilot.runs)).all()
    assert out["predicted"].notna().all()


def test_artifact_round_trip_and_metadata(small_pilot: SmallPilot) -> None:
    artifact = load_artifact(small_pilot.artifact_dir)
    meta = artifact.metadata
    assert meta.experimental is True  # BR-35: artefak pilot berlabel eksperimental
    assert meta.datasets == [42, 43]
    assert meta.n_runs == len(small_pilot.runs)
    assert meta.learner_spec_version == small_pilot.learner.version
    retrained = LightGBMMethod("metamodel", FEATURES).fit(small_pilot.runs)
    assert np.allclose(
        artifact.booster.predict(small_pilot.runs[[f"p_{n}" for n in FEATURES]].to_numpy()),
        retrained.predict(small_pilot.runs),
    )


def test_br23_profile_version_mismatch_is_an_error(small_pilot: SmallPilot) -> None:
    artifact = load_artifact(small_pilot.artifact_dir)
    artifact.check_profile("v1")
    with pytest.raises(ArtifactError, match="tidak cocok"):
        artifact.check_profile("v2")


def _tampered(source: Path, target: Path, key: str, value: object) -> Path:
    shutil.copytree(source, target)
    meta = json.loads((target / "metadata.json").read_text(encoding="utf-8"))
    meta[key] = value
    (target / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    return target


def test_artifact_integrity_checks(small_pilot: SmallPilot, tmp_path: Path) -> None:
    bad_q = _tampered(small_pilot.artifact_dir, tmp_path / "q", "conformal_quantile", 0.5)
    with pytest.raises(ArtifactError, match="kuantil"):
        load_artifact(bad_q)
    bad_learner = _tampered(small_pilot.artifact_dir, tmp_path / "l", "learner_spec_sha256", "x")
    with pytest.raises(ArtifactError, match="learner"):
        load_artifact(bad_learner)
    with pytest.raises(ArtifactError, match="tidak lengkap"):
        load_artifact(tmp_path / "missing")


def test_baseline_d_level_mapping_hits_requested_rows() -> None:
    from ceteris.metamodel import _level_for_rows

    assert _level_for_rows("label_uniform", 0.1, 3) == pytest.approx(0.1)
    assert _level_for_rows("duplicate_exact", 0.2, 3) == pytest.approx(0.25)  # 0,25/1,25 = 0,2
    level = _level_for_rows("missing_mcar", 0.271, 3)
    assert level == pytest.approx(0.1, abs=1e-3)  # Contoh 4: 1 − 0,9³ = 0,271


def test_baseline_d_follows_the_g2_operationalisation(small_pilot: SmallPilot) -> None:
    """ADR 0011 G2-7: 4 titik, dosis naik, hanya data kotor, deterministik."""
    from ceteris.corrupt import parse_spec
    from ceteris.experiment import dirty_train
    from ceteris.metamodel import DOSES, baseline_d
    from ceteris.seeding import run_seed

    row = small_pilot.runs[small_pilot.runs["kinds"] == "label_uniform"].iloc[-1]
    prepared = small_pilot.prepared[int(row["dataset_id"])]
    specs = [parse_spec(s) for s in json.loads(row["spec_json"])]
    seed = run_seed(prepared.dataset_id, row["config_id"], int(row["seed_index"]))
    _, result = dirty_train(prepared, specs, seed, small_pilot.learner)
    profile = {name: float(row[f"p_{name}"]) for name in FEATURES}
    first = baseline_d(result.frame, "class", profile, small_pilot.learner, 11)
    second = baseline_d(result.frame, "class", profile, small_pilot.learner, 11)
    assert first.points == second.points  # AC-12
    assert len(first.points) == 1 + len(DOSES)
    xs = [x for x, _ in first.points]
    assert xs == sorted(xs) and xs[0] == pytest.approx(first.p0_total)
    assert "label_uniform" in first.detected
    assert "missing_mcar" not in first.detected  # data sintetis tanpa nilai kosong
    assert first.n_holdout == pytest.approx(0.2 * len(result.frame), abs=1)
    assert first.delta_linear == pytest.approx(
        np.polyval(np.polyfit(xs, [a for _, a in first.points], 1), 0.0) - first.auc_current
    )
