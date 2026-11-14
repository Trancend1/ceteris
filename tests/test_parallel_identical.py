"""Optimasi NFR-1 tidak mengubah hasil (AC-12, BR-16, ADR 0020).

- Spearman indikator missing dengan peringkat cache identik bit demi bit dengan
  `Series.corr(method="spearman")` yang dipakai saat profil v1 dibekukan.
- Probe kebocoran ber-thread (`n_jobs` > 1) memberi profil yang identik dengan eksekusi berurutan.
  Fit LightGBM selalu berurutan (ADR 0020).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ceteris.dqprofile import (
    PROFILE_SEED,
    _missing_feature_assoc,
    compute_profile,
)
from ceteris.train import LearnerSpec
from tests.conftest import make_frame


def _reference_assoc(frame: pd.DataFrame, features: list[str], rates: pd.Series) -> float:
    """Implementasi profil v1 sebelum optimasi (Phase 2), sebagai acuan."""
    from ceteris.dqprofile import MAX_ASSOC_COLUMNS, _as_float, _is_numeric

    numeric = [c for c in features if _is_numeric(frame[c])]
    with_missing = rates[rates > 0].sort_values(ascending=False).index[:MAX_ASSOC_COLUMNS]
    best = 0.0
    for name in with_missing:
        indicator = pd.Series(frame[name].isna().to_numpy(dtype="float64"))
        if indicator.std() == 0:
            continue
        for other in numeric:
            if other == name:
                continue
            corr = indicator.corr(_as_float(frame[other]), method="spearman")
            if not pd.isna(corr):
                best = max(best, abs(float(corr)))
    return best


@pytest.mark.parametrize("seed", range(6))
def test_spearman_cache_is_bit_identical_to_pandas(seed: int) -> None:
    rng = np.random.default_rng(seed)
    n = 400
    frame = pd.DataFrame(
        {
            "a": rng.normal(size=n),
            "b": rng.integers(0, 4, size=n).astype("float64"),  # banyak nilai seri
            "c": np.where(rng.random(n) < 0.5, 1.0, 2.0),
            "konstan": np.ones(n),
            "kat": pd.Series(rng.choice(["x", "y"], size=n), dtype="category"),
        }
    )
    for col, frac in (("a", 0.2), ("b", 0.05), ("c", 0.4), ("konstan", 0.1)):
        frame.loc[rng.random(n) < frac, col] = np.nan
    if seed == 5:
        frame.loc[:, "b"] = np.nan  # kolom tanpa nilai teramati
    features = list(frame.columns)
    rates = frame[features].isna().mean()
    assert _missing_feature_assoc(frame, features, rates) == _reference_assoc(
        frame, features, rates
    )


def test_parallel_profile_is_identical(fast_learner: LearnerSpec) -> None:
    raw = make_frame(n=700, n_classes=2, seed=6, missing_frac=0.15)
    serial = compute_profile(raw, "class", learner=fast_learner, seed=PROFILE_SEED, n_jobs=1)
    parallel = compute_profile(raw, "class", learner=fast_learner, seed=PROFILE_SEED, n_jobs=4)
    assert serial.features == parallel.features
    assert serial.leakage == parallel.leakage
