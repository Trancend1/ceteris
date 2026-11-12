"""Uji corruption engine: properti BR-82, contoh 4, urutan BR-83, determinisme, BR-80, K3a–K3e."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ceteris.corpus import RawDataset, to_base_dataset
from ceteris.corrupt import (
    APPLY_ORDER,
    CorruptionContext,
    CorruptionNotApplicable,
    DuplicateConflict,
    DuplicateExact,
    LabelClassConditional,
    LabelUniform,
    MissingMAR,
    MissingMCAR,
    Outlier,
    build_context,
    corrupt,
    load_corruption_grid,
    parse_spec,
)
from ceteris.train import LearnerSpec
from tests.conftest import CONFIGS, make_frame


def base_frame(
    n: int = 400, n_classes: int = 2, seed: int = 0, missing: float = 0.0
) -> pd.DataFrame:
    raw = make_frame(n=n, n_classes=n_classes, seed=seed, missing_frac=missing)
    return to_base_dataset(RawDataset(1, "x", 1, "", "", "class", raw))


def ctx_for(frame: pd.DataFrame, target: str = "class") -> CorruptionContext:
    """Konteks sederhana untuk uji unit: urutan kolom apa adanya, kelas pindah ke berikutnya."""
    features = tuple(c for c in frame.columns if c != target)
    k = len(frame[target].cat.categories)
    return CorruptionContext(
        importance_order=features, confusion_target={c: (c + 1) % k for c in range(k)}
    )


def independent_affected(clean: pd.DataFrame, dirty: pd.DataFrame) -> int:
    """Hitung baris terdampak dengan cara berbeda dari engine: bandingkan teks per baris."""
    head = dirty.iloc[: len(clean)].astype("string").fillna("<NA>")
    before = clean.astype("string").fillna("<NA>")
    head = head.apply(lambda col: col.str.replace(r"\.0$", "", regex=True))
    before = before.apply(lambda col: col.str.replace(r"\.0$", "", regex=True))
    changed = int((head.to_numpy() != before.to_numpy()).any(axis=1).sum())
    return changed + (len(dirty) - len(clean))


KINDS = st.sampled_from(sorted(APPLY_ORDER))


@settings(max_examples=60, deadline=None, derandomize=True)
@given(
    kind=KINDS,
    level=st.floats(min_value=0.01, max_value=0.5),
    n=st.integers(min_value=60, max_value=400),
    n_classes=st.integers(min_value=2, max_value=4),
    seed=st.integers(min_value=0, max_value=2**31 - 2),
)
def test_br82_affected_row_frac_matches_actual_change(
    kind: str, level: float, n: int, n_classes: int, seed: int
) -> None:
    clean = base_frame(n=n, n_classes=n_classes, seed=seed % 1000)
    spec = parse_spec({"kind": kind, "level": level})
    result = corrupt(clean, "class", [spec], seed, ctx_for(clean))
    assert result.n_affected == independent_affected(clean, result.frame)
    assert result.affected_row_frac == pytest.approx(result.n_affected / len(result.frame))
    k = int(round(level * n))
    if kind in ("label_uniform", "outlier"):
        assert result.n_affected == k
    elif kind.startswith("duplicate"):
        assert len(result.frame) == n + k
        assert result.affected_row_frac == pytest.approx(k / (n + k))
    elif kind == "label_class_conditional":
        counts = clean["class"].value_counts()
        expected = k if n_classes == 2 else sum(int(round(level * c)) for c in counts)
        assert result.n_affected == expected
    else:
        for name in result.steps[0].columns:
            new_missing = result.frame[name].isna() & ~clean[name].isna()
            assert int(new_missing.sum()) == min(k, int(clean[name].notna().sum()))


def test_br82_contoh4_mcar_on_three_columns_vs_label_noise() -> None:
    """Contoh 4: 8.000 baris latih; MCAR 10% di 3 kolom ≈ 0,271; label noise 10% = 800 baris."""
    rng = np.random.default_rng(4)
    train = pd.DataFrame({f"f{i}": rng.normal(size=8000) for i in range(3)})
    train["class"] = pd.Categorical(rng.choice(["a", "b"], size=8000), categories=["a", "b"])
    mcar = corrupt(train, "class", [MissingMCAR(level=0.1, n_columns=3)], 11, ctx_for(train))
    assert mcar.affected_row_frac == pytest.approx(0.271, abs=0.015)
    label = corrupt(train, "class", [LabelUniform(level=0.1)], seed=11)
    assert label.n_affected == 800
    assert label.affected_row_frac == pytest.approx(0.10)


def test_br83_mixed_corruption_uses_fixed_order() -> None:
    specs = [
        MissingMCAR(level=0.1),
        Outlier(level=0.1),
        LabelUniform(level=0.1),
        DuplicateExact(level=0.1),
    ]
    frame = base_frame()
    result = corrupt(frame, "class", specs, 3, ctx_for(frame))
    applied = [step.kind for step in result.steps]
    assert applied == ["duplicate_exact", "label_uniform", "outlier", "missing_mcar"]
    reversed_result = corrupt(frame, "class", list(reversed(specs)), 3, ctx_for(frame))
    pd.testing.assert_frame_equal(result.frame, reversed_result.frame)


def test_br84_corruption_is_deterministic_per_seed() -> None:
    specs = [MissingMAR(level=0.2), LabelClassConditional(level=0.1), DuplicateConflict(level=0.1)]
    frame = base_frame(n_classes=3)
    first = corrupt(frame, "class", specs, 99, ctx_for(frame))
    second = corrupt(frame, "class", specs, 99, ctx_for(frame))
    other = corrupt(frame, "class", specs, 100, ctx_for(frame))
    pd.testing.assert_frame_equal(first.frame, second.frame)
    assert not first.frame.equals(other.frame)


def test_br80_input_partition_is_not_mutated() -> None:
    clean = base_frame()
    snapshot = clean.copy(deep=True)
    specs = [MissingMCAR(level=0.3), Outlier(level=0.3), LabelUniform(level=0.3)]
    corrupt(clean, "class", specs, 5, ctx_for(clean))
    pd.testing.assert_frame_equal(clean, snapshot)


def test_missing_skips_cells_that_are_already_missing() -> None:
    clean = base_frame(n=300, missing=0.3)
    result = corrupt(clean, "class", [MissingMCAR(level=0.5, n_columns=4)], 1, ctx_for(clean))
    cells = result.steps[0].details["cells_per_column"]
    assert cells["x1"] == min(150, int(clean["x1"].notna().sum()))


def test_k3e_missing_targets_high_or_low_importance_columns() -> None:
    frame = base_frame()
    ctx = CorruptionContext(
        importance_order=("c0", "x0", "x2", "x1"), confusion_target={0: 1, 1: 0}
    )
    high = corrupt(frame, "class", [MissingMCAR(level=0.1, n_columns=2)], 1, ctx)
    low = corrupt(
        frame, "class", [MissingMCAR(level=0.1, n_columns=2, columns="low_importance")], 1, ctx
    )
    assert high.steps[0].columns == ("c0", "x0")
    assert low.steps[0].columns == ("x2", "x1")
    with pytest.raises(ValueError, match="CorruptionContext"):
        corrupt(frame, "class", [MissingMCAR(level=0.1)], seed=1)


def test_k3b_mar_driver_is_most_correlated_column() -> None:
    rng = np.random.default_rng(0)
    a = rng.normal(size=4000)
    train = pd.DataFrame(
        {"a": a, "b": a + rng.normal(scale=0.3, size=4000), "c": rng.normal(size=4000)}
    )
    train["class"] = pd.Categorical(rng.choice(["x", "y"], size=4000))
    ctx = CorruptionContext(importance_order=("a", "b", "c"), confusion_target={0: 1, 1: 0})
    result = corrupt(train, "class", [MissingMAR(level=0.3, n_columns=1)], 2, ctx)
    step = result.steps[0]
    assert step.columns == ("a",)
    assert step.details["drivers"] == {"a": "b"}
    missing = result.frame["a"].isna()
    high = train["b"] > train["b"].median()
    assert missing[high].mean() > missing[~high].mean() * 1.5


def test_k3c_binary_flips_minority_twice_as_often() -> None:
    rng = np.random.default_rng(1)
    labels = np.where(rng.random(4000) < 0.25, "pos", "neg")
    train = pd.DataFrame({"f": rng.normal(size=4000)})
    train["class"] = pd.Categorical(labels, categories=["neg", "pos"])
    result = corrupt(train, "class", [LabelClassConditional(level=0.1)], seed=3)
    details = result.steps[0].details
    n_pos = int((labels == "pos").sum())
    n_neg = 4000 - n_pos
    assert details["positive"] == "pos"
    assert details["positive_to_negative"] + details["negative_to_positive"] == 400
    rate_pos = details["positive_to_negative"] / n_pos
    rate_neg = details["negative_to_positive"] / n_neg
    assert rate_pos == pytest.approx(2 * rate_neg, rel=0.02)


def test_k3c_multiclass_moves_rows_to_most_confused_class() -> None:
    frame = base_frame(n=600, n_classes=3)
    ctx = CorruptionContext(importance_order=("x0",), confusion_target={0: 2, 1: 0, 2: 1})
    result = corrupt(frame, "class", [LabelClassConditional(level=0.2)], 4, ctx)
    before = frame["class"].cat.codes.to_numpy()
    after = result.frame["class"].cat.codes.to_numpy()
    changed = before != after
    assert changed.sum() == sum(int(round(0.2 * c)) for c in np.bincount(before))
    for old, new in zip(before[changed], after[changed], strict=True):
        assert ctx.confusion_target[int(old)] == int(new)
    with pytest.raises(ValueError, match="CorruptionContext"):
        corrupt(frame, "class", [LabelClassConditional(level=0.2)], seed=4)


def test_k3d_outliers_fall_outside_tukey_fence() -> None:
    clean = base_frame(n=500)
    result = corrupt(clean, "class", [Outlier(level=0.2)], seed=8)
    for name in result.steps[0].columns:
        q1, q3 = clean[name].quantile([0.25, 0.75])
        fence = 3.0 * (q3 - q1)
        changed = result.frame[name] != clean[name]
        values = result.frame.loc[changed, name]
        assert ((values >= q3 + fence) | (values <= q1 - fence)).all()
    assert result.frame["x2"].dtype == "int64"
    with pytest.raises(ValueError, match="k_max"):
        Outlier(level=0.1, k_min=5.0, k_max=3.0)


def test_integer_outliers_keep_exact_count_when_fence_hits_observed_values() -> None:
    """Q1 = Q3 = 1, sebaran 0,3: pengganti 2 yang sama dengan nilai asal didorong keluar."""
    values = np.array([1] * 90 + [2] * 10, dtype="int64")
    clean = pd.DataFrame({"v": values, "class": pd.Categorical(["a", "b"] * 50)})
    for seed in range(5):
        result = corrupt(clean, "class", [Outlier(level=0.5)], seed=seed)
        changed = result.frame["v"] != clean["v"]
        assert changed.sum() == 50
        assert ((result.frame.loc[changed, "v"] >= 2) | (result.frame.loc[changed, "v"] <= 0)).all()


def test_not_applicable_cases_raise() -> None:
    only_cat = pd.DataFrame(
        {"c": pd.Categorical(["a", "b"] * 20), "class": pd.Categorical(["x", "y"] * 20)}
    )
    with pytest.raises(CorruptionNotApplicable):
        corrupt(only_cat, "class", [Outlier(level=0.1)], seed=0)
    single = pd.DataFrame({"f": np.arange(40.0), "class": pd.Categorical(["x"] * 40)})
    for spec in [
        LabelUniform(level=0.1),
        LabelClassConditional(level=0.1),
        DuplicateConflict(level=0.1),
    ]:
        with pytest.raises(CorruptionNotApplicable):
            corrupt(single, "class", [spec], seed=0)
    no_features = pd.DataFrame({"class": pd.Categorical(["x", "y"] * 20)})
    empty_ctx = CorruptionContext(importance_order=(), confusion_target={0: 1, 1: 0})
    with pytest.raises(CorruptionNotApplicable):
        corrupt(no_features, "class", [MissingMCAR(level=0.1)], 0, empty_ctx)
    one_feature = pd.DataFrame({"f": np.arange(40.0), "class": pd.Categorical(["x", "y"] * 20)})
    with pytest.raises(CorruptionNotApplicable, match="MAR"):
        corrupt(one_feature, "class", [MissingMAR(level=0.1)], 0, ctx_for(one_feature))


def test_invalid_inputs_are_rejected() -> None:
    clean = base_frame()
    with pytest.raises(ValueError, match="target"):
        corrupt(clean, "nope", [LabelUniform(level=0.1)], seed=0)
    with pytest.raises(ValueError, match="minimal"):
        corrupt(clean, "class", [], seed=0)
    with pytest.raises(ValueError, match="kategorikal"):
        corrupt(
            clean.assign(**{"class": clean["class"].astype(str)}),
            "class",
            [LabelUniform(level=0.1)],
            0,
        )
    with pytest.raises(ValueError):
        LabelUniform(level=1.0)


def test_k3a_grid_follows_thesis_plan() -> None:
    grid = load_corruption_grid(CONFIGS / "corruption.yaml")
    assert grid.version.endswith("draft")
    assert {s.kind for s in grid.singles} == set(APPLY_ORDER)
    assert len(grid.singles) == 45
    missing = [s for s in grid.singles if s.kind.startswith("missing")]
    assert {s.columns for s in missing} == {"high_importance", "low_importance"}  # type: ignore[union-attr]
    assert sorted({s.level for s in grid.singles if s.kind == "label_uniform"}) == [
        0.02,
        0.05,
        0.1,
        0.2,
        0.3,
    ]
    assert grid.mixtures == ()


def test_grid_loader_accepts_variants_and_mixtures(tmp_path: Path) -> None:
    path = tmp_path / "grid.yaml"
    path.write_text(
        "version: t\n"
        "singles:\n  - kind: outlier\n    levels: [0.1]\n    variants: [{k_min: 2.0, k_max: 4.0}]\n"
        "  - kind: label_uniform\n    levels: [0.1, 0.2]\n"
        "mixtures:\n  - [{kind: label_uniform, level: 0.1}, {kind: duplicate_exact, level: 0.1}]\n",
        encoding="utf-8",
    )
    grid = load_corruption_grid(path)
    assert grid.singles == (
        Outlier(level=0.1, k_min=2.0, k_max=4.0),
        LabelUniform(level=0.1),
        LabelUniform(level=0.2),
    )
    assert grid.mixtures == ((LabelUniform(level=0.1), DuplicateExact(level=0.1)),)


def test_build_context_ranks_features_and_maps_confusions(fast_learner: LearnerSpec) -> None:
    frame = base_frame(n=600, n_classes=3)
    ctx = build_context(frame, "class", fast_learner, seed=5)
    assert sorted(ctx.importance_order) == sorted(c for c in frame.columns if c != "class")
    assert ctx.importance_order[0] in ("x0", "c0")  # kolom paling informatif di depan
    assert set(ctx.confusion_target) == {0, 1, 2}
    assert all(src != dst for src, dst in ctx.confusion_target.items())
    assert ctx == build_context(frame, "class", fast_learner, seed=5)


def nullable_frame(n: int = 300, seed: int = 0) -> pd.DataFrame:
    """Frame bertipe nullable pandas (Int64, dengan dan tanpa NA), seperti keluaran liac-arff."""
    rng = np.random.default_rng(seed)
    with_na = pd.array(rng.integers(0, 20, size=n), dtype="Int64")
    with_na[rng.random(n) < 0.1] = pd.NA
    return pd.DataFrame(
        {
            "i_full": pd.array(rng.integers(0, 50, size=n), dtype="Int64"),
            "i_na": with_na,
            "f": rng.normal(size=n),
            "class": pd.Categorical(rng.choice(["a", "b", "c"], size=n)),
        }
    )


@pytest.mark.parametrize(
    "spec",
    [
        MissingMCAR(level=0.2, n_columns=3),
        MissingMAR(level=0.2, n_columns=3),
        LabelUniform(level=0.2),
        LabelClassConditional(level=0.2),
        Outlier(level=0.3),
        DuplicateExact(level=0.2),
        DuplicateConflict(level=0.2),
    ],
    ids=lambda s: s.kind,
)
def test_br82_nullable_integer_columns_are_supported(spec: object) -> None:
    clean = nullable_frame()
    result = corrupt(clean, "class", [spec], 6, ctx_for(clean))  # type: ignore[list-item]
    assert result.n_affected == independent_affected(clean, result.frame)


def test_outlier_keeps_nullable_integer_dtype_without_missing() -> None:
    clean = nullable_frame()[["i_full", "class"]]
    result = corrupt(clean, "class", [Outlier(level=0.2)], seed=1)
    assert str(result.frame["i_full"].dtype) == "Int64"


@pytest.mark.parametrize(
    "specs",
    [
        [MissingMCAR(level=0.3), MissingMAR(level=0.3)],
        [DuplicateExact(level=0.1), DuplicateConflict(level=0.1)],
        [LabelUniform(level=0.1), LabelUniform(level=0.2)],
    ],
)
def test_br84_order_within_a_group_does_not_change_result(specs: list[object]) -> None:
    frame = base_frame(n_classes=3)
    first = corrupt(frame, "class", specs, 17, ctx_for(frame))  # type: ignore[arg-type]
    second = corrupt(frame, "class", list(reversed(specs)), 17, ctx_for(frame))  # type: ignore[arg-type]
    pd.testing.assert_frame_equal(first.frame, second.frame)
    assert first.affected_row_frac == second.affected_row_frac


def test_identical_specs_use_separate_random_streams() -> None:
    result = corrupt(base_frame(), "class", [LabelUniform(level=0.1), LabelUniform(level=0.1)], 3)
    assert len(result.steps) == 2
    assert result.n_affected > 40  # dua langkah tidak memilih baris yang persis sama
