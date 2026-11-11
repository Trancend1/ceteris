"""Uji corruption engine: properti BR-82, contoh 4, urutan BR-83, determinisme, BR-80."""

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
    CorruptionNotApplicable,
    DuplicateConflict,
    DuplicateExact,
    LabelClassConditional,
    LabelUniform,
    MissingMAR,
    MissingMCAR,
    Outlier,
    corrupt,
    load_corruption_grid,
    parse_spec,
)
from tests.conftest import CONFIGS, make_frame


def base_frame(
    n: int = 400, n_classes: int = 2, seed: int = 0, missing: float = 0.0
) -> pd.DataFrame:
    raw = make_frame(n=n, n_classes=n_classes, seed=seed, missing_frac=missing)
    return to_base_dataset(RawDataset(1, "x", 1, "", "", "class", raw))


def independent_affected(clean: pd.DataFrame, dirty: pd.DataFrame) -> int:
    """Hitung baris terdampak dengan cara berbeda dari engine: bandingkan teks per baris."""
    head = dirty.iloc[: len(clean)].astype("string").fillna("<NA>")
    before = clean.astype("string").fillna("<NA>")
    head = head.apply(lambda col: col.str.replace(r"\.0$", "", regex=True))
    before = before.apply(lambda col: col.str.replace(r"\.0$", "", regex=True))
    changed = int((head.to_numpy() != before.to_numpy()).any(axis=1).sum())
    return changed + (len(dirty) - len(clean))


KINDS = st.sampled_from(
    [
        "missing_mcar",
        "missing_mar",
        "label_uniform",
        "label_class_conditional",
        "outlier",
        "duplicate_exact",
        "duplicate_conflict",
    ]
)


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
    result = corrupt(clean, "class", [parse_spec({"kind": kind, "level": level})], seed)
    assert result.n_affected == independent_affected(clean, result.frame)
    assert result.affected_row_frac == pytest.approx(result.n_affected / len(result.frame))
    k = int(round(level * n))
    if kind == "label_uniform" or kind == "outlier":
        assert result.n_affected == k
    elif kind.startswith("duplicate"):
        assert len(result.frame) == n + k
        assert result.affected_row_frac == pytest.approx(k / (n + k))
    elif kind == "label_class_conditional":
        counts = clean["class"].value_counts()
        assert result.n_affected == sum(int(round(level * c)) for c in counts)
    else:
        cells = result.steps[0].details["cells_per_column"]
        assert all(v == k for v in cells.values())


def test_br82_contoh4_mcar_on_three_columns_vs_label_noise() -> None:
    """Contoh 4: 8.000 baris latih; MCAR 10% di 3 kolom ≈ 0,271; label noise 10% = 800 baris."""
    rng = np.random.default_rng(4)
    train = pd.DataFrame({f"f{i}": rng.normal(size=8000) for i in range(3)})
    train["class"] = pd.Categorical(rng.choice(["a", "b"], size=8000), categories=["a", "b"])
    mcar = corrupt(train, "class", [MissingMCAR(level=0.1, n_columns=3)], seed=11)
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
    result = corrupt(base_frame(), "class", specs, seed=3)
    applied = [step.kind for step in result.steps]
    assert applied == ["duplicate_exact", "label_uniform", "outlier", "missing_mcar"]
    assert [APPLY_ORDER[k] for k in applied] == sorted(APPLY_ORDER[k] for k in applied)
    reversed_result = corrupt(base_frame(), "class", list(reversed(specs)), seed=3)
    pd.testing.assert_frame_equal(result.frame, reversed_result.frame)


def test_br84_corruption_is_deterministic_per_seed() -> None:
    specs = [MissingMAR(level=0.2), LabelClassConditional(level=0.1), DuplicateConflict(level=0.1)]
    first = corrupt(base_frame(n_classes=3), "class", specs, seed=99)
    second = corrupt(base_frame(n_classes=3), "class", specs, seed=99)
    other = corrupt(base_frame(n_classes=3), "class", specs, seed=100)
    pd.testing.assert_frame_equal(first.frame, second.frame)
    assert not first.frame.equals(other.frame)


def test_br80_input_partition_is_not_mutated() -> None:
    clean = base_frame()
    snapshot = clean.copy(deep=True)
    corrupt(
        clean, "class", [MissingMCAR(level=0.3), Outlier(level=0.3), LabelUniform(level=0.3)], 5
    )
    pd.testing.assert_frame_equal(clean, snapshot)


def test_missing_skips_cells_that_are_already_missing() -> None:
    clean = base_frame(n=300, missing=0.3)
    result = corrupt(clean, "class", [MissingMCAR(level=0.5, n_columns=4)], seed=1)
    cells = result.steps[0].details["cells_per_column"]
    available = int(clean["x1"].notna().sum())
    if "x1" in cells:
        assert cells["x1"] == min(150, available)


def test_mar_missingness_depends_on_driver_column() -> None:
    rng = np.random.default_rng(0)
    train = pd.DataFrame({"a": rng.normal(size=4000), "b": rng.normal(size=4000)})
    train["class"] = pd.Categorical(rng.choice(["x", "y"], size=4000))
    result = corrupt(train, "class", [MissingMAR(level=0.3, n_columns=1)], seed=2)
    step = result.steps[0]
    (column,) = step.columns
    driver = step.details["drivers"][column]
    missing = result.frame[column].isna()
    high = train[driver] > train[driver].median()
    assert missing[high].mean() > missing[~high].mean() * 1.5


def test_outlier_values_fall_outside_observed_range() -> None:
    clean = base_frame(n=500)
    result = corrupt(clean, "class", [Outlier(level=0.2, scale=3.0)], seed=8)
    for name in result.steps[0].columns:
        changed = result.frame[name] != clean[name]
        values = result.frame.loc[changed, name]
        assert ((values > clean[name].max()) | (values < clean[name].min())).all()
    assert result.frame["x2"].dtype == "int64"


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
    with pytest.raises(CorruptionNotApplicable):
        corrupt(no_features, "class", [MissingMCAR(level=0.1)], seed=0)


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


def test_grid_config_expands_kinds_by_levels() -> None:
    grid = load_corruption_grid(CONFIGS / "corruption.yaml")
    kinds = {s.kind for s in grid}
    assert kinds == set(APPLY_ORDER)
    assert len(grid) == len(kinds) * 4


def test_grid_loader_accepts_custom_file(tmp_path: Path) -> None:
    path = tmp_path / "grid.yaml"
    path.write_text(
        "levels: [0.1]\nkinds:\n  outlier: {scale: 2.0}\n  label_uniform:\n", encoding="utf-8"
    )
    grid = load_corruption_grid(path)
    assert grid == [Outlier(level=0.1, scale=2.0), LabelUniform(level=0.1)]


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
        Outlier(level=0.3, scale=3.0),
        DuplicateExact(level=0.2),
        DuplicateConflict(level=0.2),
    ],
    ids=lambda s: s.kind,
)
def test_br82_nullable_integer_columns_are_supported(spec: object) -> None:
    clean = nullable_frame()
    result = corrupt(clean, "class", [spec], seed=6)  # type: ignore[list-item]
    assert result.n_affected == independent_affected(clean, result.frame)


def test_outlier_keeps_nullable_integer_dtype_without_missing() -> None:
    clean = nullable_frame()[["i_full", "class"]]
    result = corrupt(clean, "class", [Outlier(level=0.2, scale=3.0)], seed=1)
    assert str(result.frame["i_full"].dtype) == "Int64"


def test_integer_outliers_stay_outside_range_after_rounding() -> None:
    """Minimum 1, sebaran kecil: batas bawah 1 − 3·0,3 = 0,1 harus dibulatkan ke 0, bukan 1."""
    values = np.array([1] * 90 + [2] * 10, dtype="int64")
    clean = pd.DataFrame({"v": values, "class": pd.Categorical(["a", "b"] * 50)})
    for seed in range(5):
        result = corrupt(clean, "class", [Outlier(level=0.5, scale=3.0)], seed=seed)
        changed = result.frame["v"] != clean["v"]
        assert changed.sum() == 50
        assert ((result.frame.loc[changed, "v"] > 2) | (result.frame.loc[changed, "v"] < 1)).all()


@pytest.mark.parametrize(
    "specs",
    [
        [MissingMCAR(level=0.3), MissingMAR(level=0.3)],
        [DuplicateExact(level=0.1), DuplicateConflict(level=0.1)],
        [LabelUniform(level=0.1), LabelUniform(level=0.2)],
    ],
)
def test_br84_order_within_a_group_does_not_change_result(specs: list[object]) -> None:
    first = corrupt(base_frame(n_classes=3), "class", specs, seed=17)  # type: ignore[arg-type]
    second = corrupt(base_frame(n_classes=3), "class", list(reversed(specs)), seed=17)  # type: ignore[arg-type]
    pd.testing.assert_frame_equal(first.frame, second.frame)
    assert first.affected_row_frac == second.affected_row_frac


def test_identical_specs_use_separate_random_streams() -> None:
    result = corrupt(base_frame(), "class", [LabelUniform(level=0.1), LabelUniform(level=0.1)], 3)
    assert len(result.steps) == 2
    assert result.n_affected > 40  # dua langkah tidak memilih baris yang persis sama
