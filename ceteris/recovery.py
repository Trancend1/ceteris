"""ceteris.recovery: temuan, volume temuan, dan potensi pemulihan per temuan.

Fitur: F-S12 (docs/product.md). Jalur: riset dan scan; modul ini tidak mengimpor kode eksperimen
(AC-3). Aturan: BR-40 (potensi = estimasi saat ini − estimasi setelah fitur temuan dinormalkan),
BR-41 (label "potensi pemulihan ideal"), BR-42 (tidak dijumlahkan), BR-43 (urutan memakai
potensi, bukan volume); ADR 0006 butir 3 (nilai "tanpa temuan" struktural, `NO_FINDING`).

Satu temuan (`issue_type`) memetakan satu jenis kekotoran ke kelompok fitur profil yang
dinormalkan bersama. Pemetaan ini sejajar dengan jenis korupsi korpus, sehingga keuntungan AUC
nyata dari memulihkan satu jenis (`ablation_run`) bisa dibandingkan dengan urutan temuan (H2b).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final, Literal

import pandas as pd

from ceteris.dqprofile import NO_FINDING

RECOVERY_LABEL: Final = "potensi pemulihan ideal"

# Temuan → fitur profil yang dinormalkan ke nilai "tanpa temuan" (BR-40, ADR 0006).
FINDING_FEATURES: Final[dict[str, tuple[str, ...]]] = {
    "missing": (
        "missing_rate",
        "missing_col_max",
        "missing_col_mean",
        "missing_col_std",
        "missing_rate_weighted",
        "missing_target_assoc",
        "missing_feature_assoc",
    ),
    "label_noise": ("label_noise_rate",),
    "duplicate_conflict": ("dup_conflict_rate",),
    "outlier": ("outlier_cell_frac_iqr", "outlier_row_frac_iforest", "outlier_rate_weighted"),
    "duplicate_exact": ("dup_row_rate",),
}

# Jenis korupsi korpus → temuan yang memulihkannya (dipakai `ablation_run`, H2b).
KIND_TO_FINDING: Final[dict[str, str]] = {
    "missing_mcar": "missing",
    "missing_mar": "missing",
    "label_uniform": "label_noise",
    "label_class_conditional": "label_noise",
    "duplicate_conflict": "duplicate_conflict",
    "outlier": "outlier",
    "duplicate_exact": "duplicate_exact",
}

# Volume temuan: proporsi baris terdampak. Missing dihitung dari data; lainnya dari fitur profil.
VOLUME_SOURCE: Final[dict[str, str | None]] = {
    "missing": None,
    "label_noise": "label_noise_rate",
    "duplicate_conflict": "dup_conflict_rate",
    "outlier": "outlier_row_frac_iforest",
    "duplicate_exact": "dup_row_rate",
}
OBSERVED: Final[dict[str, Literal["observed", "estimated"]]] = {
    "missing": "observed",
    "label_noise": "estimated",
    "duplicate_conflict": "observed",
    "outlier": "estimated",
    "duplicate_exact": "observed",
}


def missing_row_frac(frame: pd.DataFrame, target: str) -> float:
    """Proporsi baris dengan minimal satu sel fitur kosong (data setelah kontrak input)."""
    features = [c for c in frame.columns if c != target]
    if not features or frame.empty:
        return 0.0
    return float(frame[features].isna().to_numpy().any(axis=1).mean())


def finding_volumes(features: Mapping[str, float], missing_rows: float) -> dict[str, float]:
    """Volume tiap temuan sebagai proporsi baris 0–1 (urutan volume pembanding H2b)."""
    out: dict[str, float] = {}
    for issue, source in VOLUME_SOURCE.items():
        value = missing_rows if source is None else float(features[source])
        out[issue] = min(max(value, 0.0), 1.0)
    return out


def normalised(features: Mapping[str, float], issue_type: str) -> dict[str, float]:
    """Salinan profil dengan fitur temuan `issue_type` diset ke nilai "tanpa temuan"."""
    if issue_type not in FINDING_FEATURES:
        raise KeyError(f"temuan tidak dikenal: {issue_type}")
    out = {name: float(value) for name, value in features.items()}
    for name in FINDING_FEATURES[issue_type]:
        out[name] = NO_FINDING[name]
    return out


def present(features: Mapping[str, float], issue_type: str) -> bool:
    """Temuan ada bila salah satu fiturnya berbeda dari nilai "tanpa temuan"."""
    return any(float(features[name]) != NO_FINDING[name] for name in FINDING_FEATURES[issue_type])


def recovery_potentials(
    features: Mapping[str, float], predict: Callable[[Mapping[str, float]], float]
) -> dict[str, float]:
    """BR-40: potensi pemulihan ideal tiap temuan yang ada.

    Nilainya tidak dijumlahkan dan tidak dibandingkan dengan ΔAUC total (BR-42).
    """
    current = float(predict(features))
    return {
        issue: current - float(predict(normalised(features, issue)))
        for issue in FINDING_FEATURES
        if present(features, issue)
    }


@dataclass(frozen=True)
class RankedFinding:
    issue_type: str
    rows_affected_pct: float
    observed_or_estimated: Literal["observed", "estimated"]
    recovery_potential: float


def ranked_findings(
    features: Mapping[str, float],
    missing_rows: float,
    predict: Callable[[Mapping[str, float]], float],
) -> list[RankedFinding]:
    """Temuan yang ada, diurutkan menurut potensi pemulihan menurun (BR-43).

    Seri dipecah menurut nama temuan agar urutan deterministik (AC-12).
    """
    volumes = finding_volumes(features, missing_rows)
    potentials = recovery_potentials(features, predict)
    items = [
        RankedFinding(
            issue_type=issue,
            rows_affected_pct=100.0 * volumes[issue],
            observed_or_estimated=OBSERVED[issue],
            recovery_potential=potential,
        )
        for issue, potential in potentials.items()
    ]
    return sorted(items, key=lambda f: (-f.recovery_potential, f.issue_type))
