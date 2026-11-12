"""Uji potensi pemulihan per temuan (F-S12; BR-40–BR-43, ADR 0006)."""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd
import pytest

from ceteris.dqprofile import FEATURES, NO_FINDING
from ceteris.recovery import (
    FINDING_FEATURES,
    RECOVERY_LABEL,
    finding_volumes,
    missing_row_frac,
    normalised,
    ranked_findings,
    recovery_potentials,
)


def _profile(**overrides: float) -> dict[str, float]:
    base = {name: 0.5 for name in FEATURES}
    base.update({name: 0.0 for name in NO_FINDING})
    base.update(overrides)
    return base


def test_finding_features_have_structural_no_finding_values() -> None:
    """ADR 0006 butir 3: hanya fitur dengan nilai "tanpa temuan" struktural yang dinormalkan."""
    grouped = [name for names in FINDING_FEATURES.values() for name in names]
    assert len(grouped) == len(set(grouped))
    assert set(grouped) <= set(NO_FINDING)


def test_br40_normalising_touches_only_the_finding_features() -> None:
    profile = _profile(label_noise_rate=0.07, missing_rate=0.2, missing_col_max=0.6)
    out = normalised(profile, "missing")
    assert out["missing_rate"] == 0.0 and out["missing_col_max"] == 0.0
    assert out["label_noise_rate"] == 0.07
    assert profile["missing_rate"] == 0.2  # masukan tidak diubah


def test_br40_br43_example_5_ordering_uses_potential_not_volume() -> None:
    """Contoh 5: label noise 7% berpotensi 0,022; missing 18% berpotensi 0,006."""
    profile = _profile(label_noise_rate=0.07, missing_rate=0.05)

    def predict(features: Mapping[str, float]) -> float:
        value = 0.031
        if features["label_noise_rate"] == 0.0:
            value -= 0.022
        if features["missing_rate"] == 0.0:
            value -= 0.006
        return value

    potentials = recovery_potentials(profile, predict)
    assert potentials == pytest.approx({"label_noise": 0.022, "missing": 0.006})
    # BR-42: potensi tidak aditif; 0,022 + 0,006 bukan bagian dari laporan.
    ranked = ranked_findings(profile, missing_rows=0.18, predict=predict)
    assert [f.issue_type for f in ranked] == ["label_noise", "missing"]
    assert ranked[1].rows_affected_pct == pytest.approx(18.0)
    assert ranked[0].observed_or_estimated == "estimated"
    assert "ideal" in RECOVERY_LABEL


def test_absent_findings_are_not_reported() -> None:
    potentials = recovery_potentials(_profile(), lambda f: 0.0)
    assert potentials == {}


def test_volumes_are_row_proportions() -> None:
    volumes = finding_volumes(_profile(dup_row_rate=0.1, label_noise_rate=0.05), 0.3)
    assert volumes["missing"] == 0.3
    assert volumes["duplicate_exact"] == 0.1
    assert all(0.0 <= v <= 1.0 for v in volumes.values())


def test_missing_row_frac_ignores_the_target() -> None:
    frame = pd.DataFrame({"a": [1.0, None, 3.0, 4.0], "b": [1, 2, 3, None], "y": [None, 1, 1, 0]})
    assert missing_row_frac(frame, "y") == pytest.approx(0.5)
