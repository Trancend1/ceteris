"""Uji dqprofile v1: isolasi profil (BR-20), kontrak input (BR-10–BR-15), fitur, determinisme."""

from __future__ import annotations

import inspect

import numpy as np
import pandas as pd
import pytest

from ceteris.corpus import RawDataset, to_base_dataset
from ceteris.corrupt import (
    CorruptionContext,
    DuplicateConflict,
    DuplicateExact,
    LabelUniform,
    MissingMCAR,
    Outlier,
    corrupt,
)
from ceteris.dqprofile import (
    FEATURES,
    NO_FINDING,
    PROFILE_SCHEMA_VERSION,
    InputContractError,
    ProfileConfig,
    compute_profile,
    estimate_noise_floor,
)
from ceteris.train import LearnerSpec
from tests.conftest import make_frame


def base_frame(n: int = 600, n_classes: int = 2, seed: int = 0) -> pd.DataFrame:
    raw = make_frame(n=n, n_classes=n_classes, seed=seed)
    return to_base_dataset(RawDataset(1, "x", 1, "", "", "class", raw))


def ctx_for(frame: pd.DataFrame) -> CorruptionContext:
    features = tuple(c for c in frame.columns if c != "class")
    return CorruptionContext(importance_order=features, confusion_target={0: 1, 1: 0})


@pytest.mark.parametrize(
    ("function", "allowed"),
    [
        (compute_profile, ["dirty", "target", "learner", "seed", "config", "n_jobs"]),
        (estimate_noise_floor, ["dirty", "target", "learner", "seeds", "config"]),
    ],
)
def test_br20_profile_accepts_only_one_dirty_dataset(function: object, allowed: list[str]) -> None:
    """AC-2: daftar parameter tertutup; tidak ada jalur untuk versi bersih, konteks, atau level.

    `n_jobs` (ADR 0020, NFR-1) hanya jumlah thread eksekusi, bukan data.
    """
    params = inspect.signature(function).parameters  # type: ignore[arg-type]
    assert list(params) == allowed
    frames = [p for p in params.values() if "DataFrame" in str(p.annotation)]
    assert [p.name for p in frames] == ["dirty"]
    if "n_jobs" in params:
        assert str(params["n_jobs"].annotation) == "int" and params["n_jobs"].default == 1


def test_profile_has_every_v1_feature_and_is_deterministic(fast_learner: LearnerSpec) -> None:
    frame = base_frame()
    first = compute_profile(frame, "class", learner=fast_learner, seed=7)
    second = compute_profile(frame, "class", learner=fast_learner, seed=7)
    assert first == second
    assert first.schema_version == PROFILE_SCHEMA_VERSION == "v1"
    assert list(first.features) == list(FEATURES)
    assert len(first.vector()) == len(FEATURES)
    assert set(NO_FINDING) <= set(FEATURES)
    rates = [name for name in FEATURES if "rate" in name or "frac" in name or "share" in name]
    assert all(0.0 <= first.features[name] <= 1.0 for name in rates)
    assert first.features["n_rows"] == 600 and first.features["n_classes"] == 2
    assert 0.5 < first.features["probe_auc"] <= 1.0


def test_br70_input_frame_is_not_modified(fast_learner: LearnerSpec) -> None:
    frame = base_frame()
    snapshot = frame.copy(deep=True)
    compute_profile(frame, "class", learner=fast_learner, seed=1)
    pd.testing.assert_frame_equal(frame, snapshot)


@pytest.mark.parametrize(
    ("spec", "feature"),
    [
        (LabelUniform(level=0.3), "label_noise_rate"),
        (MissingMCAR(level=0.3), "missing_rate"),
        (DuplicateExact(level=0.3), "dup_row_rate"),
        (DuplicateConflict(level=0.3), "dup_conflict_rate"),
        (Outlier(level=0.2), "outlier_cell_frac_iqr"),
    ],
    ids=lambda v: getattr(v, "kind", v),
)
def test_profile_reacts_to_each_corruption(
    fast_learner: LearnerSpec, spec: object, feature: str
) -> None:
    clean = base_frame()
    dirty = corrupt(clean, "class", [spec], 3, ctx_for(clean)).frame  # type: ignore[list-item]
    before = compute_profile(clean, "class", learner=fast_learner, seed=2).features[feature]
    after = compute_profile(dirty, "class", learner=fast_learner, seed=2).features[feature]
    assert after > before


def test_br10_too_many_rows_or_columns_is_rejected() -> None:
    frame = base_frame()
    with pytest.raises(InputContractError, match="BR-10") as caught:
        compute_profile(
            frame,
            "class",
            learner=None,  # type: ignore[arg-type]
            seed=0,
            config=ProfileConfig(max_rows=100, max_features=2),
        )
    assert len(caught.value.reasons) == 2


def test_br11_target_problems_are_rejected() -> None:
    frame = base_frame()
    with pytest.raises(InputContractError, match="target_missing"):
        compute_profile(frame, "nope", learner=None, seed=0)  # type: ignore[arg-type]
    one_class = frame.assign(**{"class": "k0"})
    with pytest.raises(InputContractError, match="BR-11"):
        compute_profile(one_class, "class", learner=None, seed=0)  # type: ignore[arg-type]
    rare = frame.copy()
    rare["class"] = rare["class"].astype(str)
    rare.loc[:9, "class"] = "rare"
    with pytest.raises(InputContractError, match="class_too_small"):
        compute_profile(rare, "class", learner=None, seed=0)  # type: ignore[arg-type]


def test_missing_target_rows_are_excluded_with_warning(fast_learner: LearnerSpec) -> None:
    frame = base_frame()
    frame["class"] = frame["class"].astype(object)
    frame.loc[:4, "class"] = None
    profile = compute_profile(frame, "class", learner=fast_learner, seed=0)
    assert "target_missing_rows_excluded: 5" in profile.input_warnings
    assert profile.n_rows_input == 600 and profile.n_rows_used == 595


def test_br13_id_columns_are_dropped_but_float_columns_are_not(fast_learner: LearnerSpec) -> None:
    frame = base_frame()
    frame["row_id"] = np.arange(len(frame))
    frame["code"] = [f"c{i}" for i in range(len(frame))]
    frame["measure"] = np.random.default_rng(0).normal(size=len(frame))
    profile = compute_profile(frame, "class", learner=fast_learner, seed=0)
    assert profile.dropped_columns == {"row_id": "id_column_dropped", "code": "id_column_dropped"}
    assert "id_column_dropped: row_id" in profile.input_warnings
    assert profile.features["n_features"] == 5  # x0, x1, x2, c0, measure


def test_br14_datetime_is_converted_and_free_text_dropped(fast_learner: LearnerSpec) -> None:
    frame = base_frame()
    frame["when"] = pd.date_range("2024-01-01", periods=len(frame), freq="h")
    frame["note"] = ["pelanggan menelepon untuk menanyakan status pesanan"] * len(frame)
    profile = compute_profile(frame, "class", learner=fast_learner, seed=0)
    assert "datetime_converted: when" in profile.input_warnings
    assert profile.dropped_columns.get("note") == "text_column_dropped"


def test_no_features_left_is_rejected() -> None:
    frame = pd.DataFrame({"row_id": np.arange(100), "class": ["a", "b"] * 50})
    with pytest.raises(InputContractError, match="no_features"):
        compute_profile(frame, "class", learner=None, seed=0)  # type: ignore[arg-type]


def test_br15_target_leak_is_flagged(fast_learner: LearnerSpec) -> None:
    frame = base_frame()
    leaky = frame.assign(leak=frame["class"].cat.codes.astype("float64"))
    flagged = compute_profile(leaky, "class", learner=fast_learner, seed=0)
    assert flagged.leakage.flagged and flagged.leakage.feature == "leak"
    assert flagged.leakage.auc == pytest.approx(1.0)
    assert "target_leakage_suspected: leak" in flagged.input_warnings
    clean = compute_profile(frame, "class", learner=fast_learner, seed=0)
    assert not clean.leakage.flagged
    assert clean.leakage.threshold == 0.99


def test_adr0007_adaptive_threshold_drops_with_label_noise(fast_learner: LearnerSpec) -> None:
    frame = base_frame()
    noisy = corrupt(frame, "class", [LabelUniform(level=0.2)], seed=1).frame
    config = ProfileConfig(leakage_threshold="adaptive", leakage_tau_min=0.8)
    profile = compute_profile(noisy, "class", learner=fast_learner, seed=0, config=config)
    expected = max(0.8, 0.99 * (1 - profile.features["label_noise_rate"]))
    assert profile.leakage.threshold == pytest.approx(expected)
    assert profile.leakage.threshold < 0.99


def test_br12_large_inputs_are_sampled_with_all_classes(fast_learner: LearnerSpec) -> None:
    frame = base_frame(n=900, n_classes=3)
    profile = compute_profile(
        frame, "class", learner=fast_learner, seed=0, config=ProfileConfig(sample_max_rows=300)
    )
    assert profile.sample_size == 300
    assert profile.n_rows_used == 900
    assert profile.features["n_rows"] == 900


def test_f_s06_noise_floor_estimate_varies_by_seed(fast_learner: LearnerSpec) -> None:
    frame = base_frame(n=800)
    aucs = estimate_noise_floor(frame, "class", learner=fast_learner, seeds=[1, 2, 3])
    assert len(aucs) == 3 and len(set(aucs)) > 1
    with pytest.raises(ValueError, match="dua seed"):
        estimate_noise_floor(frame, "class", learner=fast_learner, seeds=[1])


def test_br15_multiclass_target_copy_is_flagged(fast_learner: LearnerSpec) -> None:
    """Salinan numerik target 10 kelas seimbang harus terdeteksi (temuan tinjauan Phase 2)."""
    frame = base_frame(n=1000, n_classes=10)
    leaky = frame.assign(leak=frame["class"].cat.codes.astype("float64"))
    profile = compute_profile(leaky, "class", learner=fast_learner, seed=0)
    assert profile.leakage.flagged and profile.leakage.feature == "leak"
    assert profile.leakage.auc == pytest.approx(1.0)


def test_br15_high_cardinality_categorical_leak_is_flagged(fast_learner: LearnerSpec) -> None:
    """64 kategori, masing-masing murni satu kelas: kebocoran walau kodenya acak."""
    frame = base_frame(n=1280)
    rng = np.random.default_rng(3)
    codes = frame["class"].cat.codes.to_numpy()
    buckets = rng.integers(0, 32, size=len(frame))
    leaky = frame.assign(leak=[f"L{c}_{b}" for c, b in zip(codes, buckets, strict=True)])
    profile = compute_profile(leaky, "class", learner=fast_learner, seed=0)
    assert profile.leakage.flagged and profile.leakage.feature == "leak"


def test_br13_integer_ids_are_dropped_even_after_becoming_float(fast_learner: LearnerSpec) -> None:
    frame = base_frame()
    with_na = pd.array(np.arange(len(frame)), dtype="Int64")
    with_na[0] = pd.NA
    frame["nullable_id"] = with_na
    frame["float_id"] = np.arange(len(frame), dtype="float64")
    frame.loc[1, "float_id"] = np.nan
    profile = compute_profile(frame, "class", learner=fast_learner, seed=0)
    assert profile.dropped_columns == {
        "nullable_id": "id_column_dropped",
        "float_id": "id_column_dropped",
    }


def test_outliers_in_zero_iqr_columns_are_visible(fast_learner: LearnerSpec) -> None:
    """Kolom jarang (IQR nol): profil memakai sebaran cadangan yang sama dengan engine."""
    rng = np.random.default_rng(5)
    frame = base_frame()
    sparse = np.where(rng.random(len(frame)) < 0.85, 0.0, rng.normal(size=len(frame)))
    frame["sparse"] = sparse
    clean = compute_profile(frame, "class", learner=fast_learner, seed=0)
    dirty_frame = frame.copy()
    dirty_frame.loc[:59, "sparse"] = 1000.0
    dirty = compute_profile(dirty_frame, "class", learner=fast_learner, seed=0)
    assert dirty.features["outlier_cell_frac_iqr"] > clean.features["outlier_cell_frac_iqr"]


def test_br15_multi_config_auc_matches_single_calls() -> None:
    """Kalibrasi memakai `single_feature_aucs`; hasilnya harus sama dengan probe produksi."""
    from sklearn.model_selection import StratifiedKFold

    from ceteris.dqprofile import single_feature_auc, single_feature_aucs

    frame = base_frame(n=600, n_classes=3)
    y = frame["class"].cat.codes.to_numpy()
    folds = list(StratifiedKFold(5, shuffle=True, random_state=0).split(np.zeros(len(y)), y))
    configs = [
        ProfileConfig(leakage_max_depth=2, leakage_min_samples_leaf=0.05),
        ProfileConfig(leakage_max_depth=6, leakage_min_samples_leaf=0.005),
    ]
    for name in ("x0", "c0"):
        combined = single_feature_aucs(frame[name], y, folds, configs, seed=4)
        assert combined == [single_feature_auc(frame[name], y, folds, c, seed=4) for c in configs]


def test_br12_stratified_sample_keeps_every_class() -> None:
    from ceteris.dqprofile import _sample

    frame = base_frame(n=2000, n_classes=4)
    sample = _sample(frame, "class", ProfileConfig(sample_max_rows=200), seed=1)
    assert len(sample) == 200
    assert set(sample["class"].cat.codes) == {0, 1, 2, 3}
