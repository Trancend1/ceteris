"""ceteris.metamodel: meta-model, baseline (a)–(c), dan pembuat artefak.

Fitur: F-S08, F-S09 (docs/product.md). Jalur: riset saja; scan memuat artefak lewat
`ceteris.artifact` (AC-3, AC-4). Aturan: BR-21, BR-22, BR-23, BR-24, AC-8 (skor OOD bukan fitur),
BR-85 (unit analisis dataset).

Definisi baseline mengikuti rencana skripsi (Draft-1-Skripsi, bagian Baseline):

- (a) rata-rata ΔAUC data latih;
- (b) skor gabungan: setiap indikator kekotoran dinormalkan ke 0–1 menurut peringkatnya di data
  latih, skor = 100 × (1 − rata-rata indikator) dengan bobot sama tanpa tuning, lalu regresi
  linear ΔAUC pada skor;
- (c) meta-fitur saja: LightGBM dengan fitur konteks dan probe, tanpa indikator kekotoran.

Baseline (d) dose–response butuh data latih kotor dan corruption engine, sehingga dibangun
terpisah. Hiperparameter meta-model pilot tetap (tanpa tuning); tuning bersarang ada di Phase 4.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import lightgbm as lgb
import numpy as np
import pandas as pd

from ceteris.artifact import (
    ArtifactMetadata,
    learner_sha256,
    save_artifact,
)
from ceteris.dqprofile import (
    FEATURES,
    NO_FINDING,
    PROFILE_SCHEMA_VERSION,
    NoiseFloorStatistic,
)
from ceteris.train import LearnerSpec
from ceteris.uncertainty import lodo_ood_scores, ood_threshold, weighted_conformal_quantile

TARGET = "delta_auc"
CONTEXT_FEATURES: tuple[str, ...] = FEATURES[:6]
PROBE_FEATURES: tuple[str, ...] = ("probe_auc", "importance_top1_share")
DIRTINESS_FEATURES: tuple[str, ...] = tuple(name for name in FEATURES if name in NO_FINDING)

# Hiperparameter meta-model pilot, tetap dan deterministik (tanpa tuning di pilot).
META_PARAMS: dict[str, Any] = {
    "objective": "regression",
    "learning_rate": 0.05,
    "num_leaves": 15,
    "min_data_in_leaf": 20,
    "deterministic": True,
    "force_row_wise": True,
    "num_threads": 1,
    "verbosity": -1,
    "seed": 20261112,
}
META_ROUNDS = 300


def profile_columns(features: Sequence[str]) -> list[str]:
    return [f"p_{name}" for name in features]


def feature_frame(runs: pd.DataFrame, features: Sequence[str]) -> pd.DataFrame:
    """Fitur profil dari baris `corruption_run` dengan nama fitur aslinya."""
    frame = runs[profile_columns(features)].astype("float64")
    frame.columns = list(features)
    return frame


class Method(Protocol):
    """Metode estimasi ΔAUC yang dievaluasi dengan LODO (meta-model dan baseline)."""

    name: str

    def fit(self, runs: pd.DataFrame) -> Method: ...

    def predict(self, runs: pd.DataFrame) -> np.ndarray: ...


def fit_booster(features: pd.DataFrame, target: np.ndarray) -> lgb.Booster:
    data = lgb.Dataset(features, label=target, feature_name=list(features.columns))
    return lgb.train(META_PARAMS, data, num_boost_round=META_ROUNDS)


@dataclass
class LightGBMMethod:
    """Meta-model utama (semua fitur profil) atau baseline (c) (konteks dan probe)."""

    name: str
    features: tuple[str, ...]
    booster: lgb.Booster | None = None

    def fit(self, runs: pd.DataFrame) -> LightGBMMethod:
        self.booster = fit_booster(
            feature_frame(runs, self.features), runs[TARGET].to_numpy("float64")
        )
        return self

    def predict(self, runs: pd.DataFrame) -> np.ndarray:
        if self.booster is None:
            raise RuntimeError(f"{self.name} belum dilatih")
        return np.asarray(self.booster.predict(feature_frame(runs, self.features)))


@dataclass
class MeanBaseline:
    """Baseline (a): rata-rata ΔAUC data latih."""

    name: str = "baseline_a_mean"
    mean: float | None = None

    def fit(self, runs: pd.DataFrame) -> MeanBaseline:
        self.mean = float(runs[TARGET].mean())
        return self

    def predict(self, runs: pd.DataFrame) -> np.ndarray:
        if self.mean is None:
            raise RuntimeError("baseline (a) belum dilatih")
        return np.full(len(runs), self.mean)


@dataclass
class CompositeScoreBaseline:
    """Baseline (b): skor kualitas gabungan berbobot sama, dikalibrasi dengan regresi linear."""

    name: str = "baseline_b_composite"
    reference: dict[str, np.ndarray] = field(default_factory=dict)
    slope: float | None = None
    intercept: float | None = None

    def score(self, runs: pd.DataFrame) -> np.ndarray:
        """Skor 0–100: 100 berarti tidak ada indikator kekotoran di atas data latih terendah."""
        frame = feature_frame(runs, DIRTINESS_FEATURES)
        ranks = [
            np.searchsorted(self.reference[name], frame[name].to_numpy("float64"), side="right")
            / len(self.reference[name])
            for name in DIRTINESS_FEATURES
        ]
        return np.asarray(100.0 * (1.0 - np.mean(ranks, axis=0)))

    def fit(self, runs: pd.DataFrame) -> CompositeScoreBaseline:
        frame = feature_frame(runs, DIRTINESS_FEATURES)
        self.reference = {name: np.sort(frame[name].to_numpy("float64")) for name in frame}
        x = self.score(runs)
        y = runs[TARGET].to_numpy("float64")
        if np.ptp(x) == 0:
            self.slope, self.intercept = 0.0, float(y.mean())
        else:
            slope, intercept = np.polyfit(x, y, deg=1)
            self.slope, self.intercept = float(slope), float(intercept)
        return self

    def predict(self, runs: pd.DataFrame) -> np.ndarray:
        if self.slope is None or self.intercept is None:
            raise RuntimeError("baseline (b) belum dilatih")
        return self.intercept + self.slope * self.score(runs)


def pilot_methods() -> list[Method]:
    """Meta-model utama dan baseline (a)–(c) dalam urutan laporan."""
    return [
        LightGBMMethod("metamodel", FEATURES),
        MeanBaseline(),
        CompositeScoreBaseline(),
        LightGBMMethod("baseline_c_metafeatures", CONTEXT_FEATURES + PROBE_FEATURES),
    ]


def lodo_predictions(runs: pd.DataFrame, methods: Sequence[Method]) -> pd.DataFrame:
    """Prediksi leave-one-dataset-out: dataset uji tidak dipakai melatih apa pun (BR-81).

    Versi pilot tanpa tuning dan tanpa kalibrasi di dalam fold; LODO bersarang penuh (F-S11)
    dibangun di Phase 4.
    """
    rows: list[pd.DataFrame] = []
    for dataset_id in sorted(runs["dataset_id"].unique()):
        test = runs[runs["dataset_id"] == dataset_id]
        train = runs[runs["dataset_id"] != dataset_id]
        for method in methods:
            fitted = method.fit(train)
            rows.append(
                pd.DataFrame(
                    {
                        "run_id": test["run_id"].to_numpy(),
                        "dataset_id": dataset_id,
                        "method": method.name,
                        "actual": test[TARGET].to_numpy("float64"),
                        "predicted": fitted.predict(test),
                    }
                )
            )
    return pd.concat(rows, ignore_index=True)


# --- artefak pilot (F-S08, F-S10) ---


def build_artifact(
    runs: pd.DataFrame,
    learner: LearnerSpec,
    out_dir: Path,
    *,
    version: str,
    corpus_snapshot: str,
    noise_floor_statistic: NoiseFloorStatistic,
    noise_floor_seeds: int,
    ood_k: int = 5,
    ood_percentile: float = 95.0,
    experimental: bool = True,
) -> ArtifactMetadata:
    """Latih meta-model akhir dan tulis artefak beserta kalibrator dan referensi OOD.

    Skor kalibrasi conformal adalah residu absolut leave-one-dataset-out, sehingga setiap skor
    berasal dari model yang tidak melihat datasetnya (BR-22). Kuantil memberi bobot sama per
    dataset; ambang OOD adalah persentil skor OOD LODO (ADR 0011, sementara sampai G3).
    """
    if runs["dataset_id"].nunique() < 2:
        raise ValueError("artefak butuh minimal dua dataset untuk kalibrasi LODO")
    if (runs["profile_schema_version"] != PROFILE_SCHEMA_VERSION).any():
        raise ValueError("semua run harus memakai skema profil yang sama dengan kode")
    lodo = lodo_predictions(runs, [LightGBMMethod("metamodel", FEATURES)])
    calibration = pd.DataFrame(
        {
            "dataset_id": lodo["dataset_id"].astype("int64"),
            "score": (lodo["actual"] - lodo["predicted"]).abs(),
        }
    )
    quantile = weighted_conformal_quantile(
        calibration["score"].tolist(), calibration["dataset_id"].tolist()
    )
    profiles = feature_frame(runs, FEATURES)
    ood_scores = lodo_ood_scores(profiles, runs["dataset_id"].tolist(), FEATURES, ood_k)
    metadata = ArtifactMetadata(
        version=version,
        experimental=experimental,
        profile_schema_version=PROFILE_SCHEMA_VERSION,
        learner_spec_version=learner.version,
        learner_spec_sha256=learner_sha256(learner),
        corpus_snapshot=corpus_snapshot,
        trained_at=datetime.now(UTC).isoformat(),
        datasets=sorted(int(d) for d in runs["dataset_id"].unique()),
        n_runs=len(runs),
        features=list(FEATURES),
        conformal_quantile=quantile,
        coverage_summary=lodo_coverage_summary(lodo),
        ood_k=ood_k,
        ood_threshold=ood_threshold(ood_scores, ood_percentile),
        ood_threshold_basis=f"p{ood_percentile:g} skor OOD LODO, k={ood_k} (sementara sampai G3)",
        noise_floor_statistic=noise_floor_statistic,
        noise_floor_seeds=noise_floor_seeds,
    )
    booster = fit_booster(profiles, runs[TARGET].to_numpy("float64"))
    save_artifact(out_dir, metadata, booster, calibration, profiles, learner)
    return metadata


def lodo_coverage_summary(lodo: pd.DataFrame) -> dict[str, float]:
    """Coverage LODO per dataset, dengan kuantil dari dataset lain saja (tanpa kebocoran)."""
    residual = (lodo["actual"] - lodo["predicted"]).abs()
    coverages: list[float] = []
    widths: list[float] = []
    for dataset_id in sorted(lodo["dataset_id"].unique()):
        inside = lodo["dataset_id"] == dataset_id
        q = weighted_conformal_quantile(
            residual[~inside].tolist(), lodo.loc[~inside, "dataset_id"].tolist()
        )
        coverages.append(float((residual[inside] <= q).mean()))
        widths.append(2.0 * q)
    return {
        "coverage_median": float(np.median(coverages)),
        "coverage_min": float(np.min(coverages)),
        "coverage_max": float(np.max(coverages)),
        "width_median": float(np.median(widths)),
        "n_datasets": float(len(coverages)),
    }
