"""Uji kalibrator conformal berbobot dataset dan skor OOD (F-S10; BR-22, BR-24, ADR 0011)."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from ceteris.uncertainty import (
    conformal_interval,
    fit_ood_reference,
    lodo_ood_scores,
    ood_threshold,
    weighted_conformal_quantile,
)

EXAMPLE_3 = [
    0.001, 0.002, 0.002, 0.003, 0.004, 0.004, 0.005, 0.006, 0.007, 0.008,
    0.009, 0.010, 0.011, 0.012, 0.014, 0.015, 0.017, 0.019, 0.027,
]  # fmt: skip


def test_br22_example_3_quantile_and_interval() -> None:
    """Contoh 3: 19 run kalibrasi, peringkat ⌈20 × 0,90⌉ = 18, skor 0,019."""
    q = weighted_conformal_quantile(EXAMPLE_3, groups=list(range(19)))
    assert q == 0.019
    lo, hi = conformal_interval(0.031, q)
    assert (round(lo, 3), round(hi, 3)) == (0.012, 0.050)


def test_br22_example_3_with_nine_runs_uses_the_largest_score() -> None:
    nine = EXAMPLE_3[:9]
    assert weighted_conformal_quantile(nine, groups=list(range(9))) == max(nine)


@given(
    st.lists(st.floats(0, 1, allow_nan=False), min_size=2, max_size=8),
    st.integers(1, 6),
)
def test_br22_equal_runs_per_dataset_equals_pooled_quantile(
    base: list[float], runs_per_dataset: int
) -> None:
    """ADR 0011: bila jumlah run per dataset sama, bobot per dataset = kuantil biasa."""
    scores = [s + 0.001 * i for i, s in enumerate(base * runs_per_dataset)]
    groups = [i % len(base) for i in range(len(scores))]
    n = len(scores)
    rank = math.ceil((n + 1) * 0.90)
    pooled = sorted(scores)[rank - 1] if rank <= n else math.inf
    assert weighted_conformal_quantile(scores, groups) == pooled


def test_adr0011_large_dataset_does_not_dominate_the_quantile() -> None:
    """Satu dataset dengan banyak skor kecil tidak boleh menyempitkan interval dataset lain."""
    small = [0.001] * 90  # dataset 0: 90 run
    others = [0.05, 0.06, 0.07, 0.08, 0.09, 0.10, 0.11, 0.12, 0.13, 0.14]  # 10 dataset, 1 run
    scores = small + others
    groups = [0] * 90 + list(range(1, 11))
    pooled = sorted(scores)[math.ceil((len(scores) + 1) * 0.9) - 1]
    weighted = weighted_conformal_quantile(scores, groups)
    assert pooled == 0.05  # skor dataset besar mendominasi
    assert weighted >= 0.13


def test_br22_too_few_calibration_scores_give_infinite_interval() -> None:
    assert weighted_conformal_quantile([0.01, 0.02], ["a", "b"]) == math.inf
    with pytest.raises(ValueError, match="minimal satu"):
        weighted_conformal_quantile([], [])


def test_adr0011_interval_is_not_clipped_at_zero() -> None:
    lo, hi = conformal_interval(0.004, 0.019)
    assert lo < 0 < hi
    assert (lo, hi) == pytest.approx((-0.015, 0.023))


def _profiles(seed: int, n: int, shift: float) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame({"a": rng.normal(shift, 1, n), "b": rng.normal(0, 1, n), "c": 1.0})


def test_br24_ood_score_grows_with_distance_and_ignores_constant_features() -> None:
    reference = fit_ood_reference(_profiles(0, 200, 0.0), ["a", "b", "c"], k=5)
    near = reference.score([0.0, 0.0, 1.0])
    far = reference.score([8.0, 0.0, 1.0])
    assert near < far
    assert reference.scale[2] == 1.0  # fitur konstan tidak membagi dengan nol


def test_adr0011_lodo_scores_flag_a_shifted_dataset() -> None:
    frames = [_profiles(1, 50, 0.0), _profiles(2, 50, 0.2), _profiles(3, 50, 6.0)]
    profiles = pd.concat(frames, ignore_index=True)
    groups = [0] * 50 + [1] * 50 + [2] * 50
    scores = lodo_ood_scores(profiles, groups, ["a", "b", "c"], k=5)
    assert scores[100:].mean() > 2 * scores[:100].mean()
    threshold = ood_threshold(scores, 95)
    assert np.mean(scores > threshold) == pytest.approx(0.05, abs=0.01)
    with pytest.raises(ValueError, match="dua dataset"):
        lodo_ood_scores(frames[0], [0] * 50, ["a", "b", "c"], k=5)
