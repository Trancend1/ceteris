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
    fit_predict_proba,
    load_learner_spec,
    measure_delta_auc,
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


def test_br03_learner_spec_requires_determinism(tmp_path: Path) -> None:
    good = {
        "version": "x",
        "num_boost_round": 5,
        "params": {"deterministic": True, "force_row_wise": True},
    }
    LearnerSpec.model_validate(good)
    with pytest.raises(ValidationError, match="deterministic"):
        LearnerSpec.model_validate({**good, "params": {"force_row_wise": True}})
    with pytest.raises(ValidationError, match="force_row_wise"):
        LearnerSpec.model_validate({**good, "params": {"deterministic": True}})
    with pytest.raises(ValidationError, match="harness"):
        LearnerSpec.model_validate({**good, "params": {**good["params"], "seed": 1}})  # type: ignore[dict-item]


def test_br03_repository_learner_spec_is_valid() -> None:
    spec = load_learner_spec(CONFIGS / "learner.yaml")
    assert spec.params["deterministic"] is True
    assert spec.version.endswith("draft")


def test_br07_no_delta_f1_anywhere_in_package() -> None:
    for path in (REPO_ROOT / "ceteris").glob("*.py"):
        assert "delta_f1" not in path.read_text(encoding="utf-8"), path.name
