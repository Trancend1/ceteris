"""Uji learner acuan dan ΔAUC (BR-01, BR-02, BR-03, BR-07)."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from ceteris.corpus import RawDataset, SplitSpec, frame_sha256, make_split, to_base_dataset
from ceteris.corrupt import LabelUniform, corrupt
from ceteris.train import (
    LearnerSpec,
    auc_score,
    delta_auc,
    delta_auc_relative,
    feature_importance,
    fit_predict_proba,
    load_learner_spec,
    measure_delta_auc,
    measure_noise_floor,
    oof_predict_proba,
)
from tests.conftest import CONFIGS, REPO_ROOT, make_frame


def split_frames(n: int = 600, n_classes: int = 2, seed: int = 0):  # type: ignore[no-untyped-def]
    base = to_base_dataset(RawDataset(1, "x", 1, "", "", "class", make_frame(n, n_classes, seed)))
    labels = make_split(base, "class", SplitSpec(), seed=1)
    return base.loc[labels == "train"].reset_index(drop=True), base.loc[
        labels == "test"
    ].reset_index(drop=True)


def test_br02_contoh1_relative_delta() -> None:
    delta = delta_auc(0.85, 0.72)
    assert delta == pytest.approx(0.13)
    assert delta_auc_relative(0.85, delta) == pytest.approx(0.13 / 0.35)
    assert round(delta_auc_relative(0.85, delta), 3) == 0.371
    assert delta_auc_relative(0.98, delta_auc(0.98, 0.95)) == pytest.approx(0.0625)


def test_br02_relative_delta_is_nan_without_headroom() -> None:
    assert math.isnan(delta_auc_relative(0.5, 0.01))
    assert math.isnan(delta_auc_relative(0.4, 0.01))


def test_br01_two_models_one_clean_test_set(fast_learner: LearnerSpec) -> None:
    train, test = split_frames()
    dirty = corrupt(train, "class", [LabelUniform(level=0.3)], seed=4).frame
    before = frame_sha256(test)
    result = measure_delta_auc(fast_learner, train, dirty, test, "class", seed=12)
    assert frame_sha256(test) == before, "test set bersih tidak boleh berubah"
    assert result.delta_auc == pytest.approx(result.auc_clean - result.auc_dirty)
    assert result.auc_clean > 0.75
    assert result.delta_auc > 0, "label noise 30% seharusnya merugikan pada data sintetis ini"


def test_br03_same_seed_same_delta(fast_learner: LearnerSpec) -> None:
    train, test = split_frames(n_classes=3)
    dirty = corrupt(train, "class", [LabelUniform(level=0.2)], seed=4).frame
    first = measure_delta_auc(fast_learner, train, dirty, test, "class", seed=21)
    second = measure_delta_auc(fast_learner, train, dirty, test, "class", seed=21)
    assert first == second


def test_multiclass_auc_is_macro_one_vs_rest() -> None:
    y = np.array([0, 1, 2, 0, 1, 2])
    perfect = np.eye(3)[y]
    assert auc_score(y, perfect) == 1.0
    assert (
        auc_score(
            np.array([0, 1, 0, 1]), np.array([[0.9, 0.1], [0.2, 0.8], [0.6, 0.4], [0.3, 0.7]])
        )
        == 1.0
    )


def test_predictions_have_one_column_per_class(fast_learner: LearnerSpec) -> None:
    train, test = split_frames(n_classes=4)
    proba = fit_predict_proba(fast_learner, train, test, "class", seed=1)
    assert proba.shape == (len(test), 4)
    assert np.allclose(proba.sum(axis=1), 1.0)


def test_mismatched_target_categories_are_rejected(fast_learner: LearnerSpec) -> None:
    train, test = split_frames()
    test = test.assign(**{"class": test["class"].cat.add_categories(["extra"])})
    with pytest.raises(ValueError, match="kategori"):
        fit_predict_proba(fast_learner, train, test, "class", seed=1)


def test_target_must_be_categorical_and_complete(fast_learner: LearnerSpec) -> None:
    train, test = split_frames()
    with pytest.raises(ValueError, match="kategorikal"):
        fit_predict_proba(
            fast_learner, train.assign(**{"class": train["class"].astype(str)}), test, "class", 1
        )
    broken = train.copy()
    broken.loc[0, "class"] = np.nan
    with pytest.raises(ValueError, match="kosong"):
        fit_predict_proba(fast_learner, broken, test, "class", 1)


def test_br03_learner_spec_requires_determinism_and_bagging(tmp_path: Path) -> None:
    params = {
        "deterministic": True,
        "force_row_wise": True,
        "bagging_fraction": 0.8,
        "bagging_freq": 1,
    }
    good = {"version": "x", "num_boost_round": 5, "params": params}
    LearnerSpec.model_validate(good)
    drop = {k: v for k, v in params.items() if k != "deterministic"}
    with pytest.raises(ValidationError, match="deterministic"):
        LearnerSpec.model_validate({**good, "params": drop})
    drop = {k: v for k, v in params.items() if k != "force_row_wise"}
    with pytest.raises(ValidationError, match="force_row_wise"):
        LearnerSpec.model_validate({**good, "params": drop})
    with pytest.raises(ValidationError, match="harness"):
        LearnerSpec.model_validate({**good, "params": {**params, "seed": 1}})
    for broken in ({"bagging_freq": 0}, {"bagging_fraction": 1.0}):
        with pytest.raises(ValidationError, match="bagging"):
            LearnerSpec.model_validate({**good, "params": {**params, **broken}})


def test_br04_different_seeds_give_different_models(fast_learner: LearnerSpec) -> None:
    """ADR 0009 K1: seed harus berpengaruh, kalau tidak noise floor terukur selalu 0."""
    train, test = split_frames(n=800)
    a = fit_predict_proba(fast_learner, train, test, "class", seed=1)
    b = fit_predict_proba(fast_learner, train, test, "class", seed=2)
    assert not np.array_equal(a, b)


def test_br04_noise_floor_harness_returns_auc_per_seed(fast_learner: LearnerSpec) -> None:
    train, test = split_frames(n=800)
    aucs = measure_noise_floor(fast_learner, train, test, "class", [1, 2, 3])
    assert len(aucs) == 3 and all(0.5 < a <= 1.0 for a in aucs)
    assert aucs == measure_noise_floor(fast_learner, train, test, "class", [1, 2, 3])
    with pytest.raises(ValueError, match="dua seed"):
        measure_noise_floor(fast_learner, train, test, "class", [1])


def test_oof_predictions_cover_every_row(fast_learner: LearnerSpec) -> None:
    train, _ = split_frames(n=600, n_classes=3)
    proba = oof_predict_proba(fast_learner, train, "class", seed=4)
    assert proba.shape == (len(train), 3)
    assert np.allclose(proba.sum(axis=1), 1.0)
    assert np.array_equal(proba, oof_predict_proba(fast_learner, train, "class", seed=4))


def test_feature_importance_is_normalised_per_column(fast_learner: LearnerSpec) -> None:
    train, _ = split_frames(n=600)
    importance = feature_importance(fast_learner, train, "class", seed=3)
    assert list(importance.index) == [c for c in train.columns if c != "class"]
    assert importance.sum() == pytest.approx(1.0)
    assert importance["x1"] < min(importance["x0"], importance["c0"])  # x1 hanya derau


def test_br03_repository_learner_spec_is_frozen_at_g1() -> None:
    """ADR 0010 B1: versi 1.0.0 dibekukan; mengubah isinya wajib menaikkan versi."""
    spec = load_learner_spec(CONFIGS / "learner.yaml")
    assert spec.version == "1.0.0"
    assert spec.num_boost_round == 100
    assert spec.params == {
        "learning_rate": 0.1,
        "num_leaves": 31,
        "min_data_in_leaf": 20,
        "bagging_fraction": 0.8,
        "bagging_freq": 1,
        "deterministic": True,
        "force_row_wise": True,
        "num_threads": 1,
        "verbosity": -1,
    }


def test_br07_no_delta_f1_anywhere_in_package() -> None:
    for path in (REPO_ROOT / "ceteris").glob("*.py"):
        assert "delta_f1" not in path.read_text(encoding="utf-8"), path.name
