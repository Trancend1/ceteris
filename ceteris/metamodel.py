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


# --- baseline (d): dose–response (F-S09, ADR 0011 G2-7) ---

DOSES: tuple[float, ...] = (0.05, 0.10, 0.20)
HOLDOUT_FRAC = 0.20
# Jenis yang dideteksi dari profil Dₖ dan fitur taksiran proporsi baris terdampaknya.
DOSE_TYPES: dict[str, str | None] = {
    "missing_mcar": None,  # dihitung langsung: proporsi baris dengan minimal satu sel kosong
    "label_uniform": "label_noise_rate",
    "duplicate_exact": "dup_row_rate",
    "duplicate_conflict": "dup_conflict_rate",
    "outlier": "outlier_row_frac_iforest",
}


@dataclass(frozen=True)
class DoseResponse:
    """Hasil baseline (d) untuk satu dataset kotor."""

    delta_linear: float
    delta_quadratic: float
    auc_current: float
    p0_total: float
    detected: dict[str, float]
    points: list[tuple[float, float]]
    seconds: float
    n_train: int
    n_holdout: int


def _level_for_rows(kind: str, rows: float, n_columns: int) -> float:
    """Level spesifikasi korupsi agar proporsi baris terdampak ≈ `rows` (semantik ADR 0009)."""
    rows = min(max(rows, 0.0), 0.9)
    if kind.startswith("duplicate"):
        return rows / (1.0 - rows)  # baris tambahan / (n + tambahan) = rows
    if kind == "missing_mcar":
        return float(1.0 - (1.0 - rows) ** (1.0 / n_columns))  # 3 kolom independen
    return rows


def baseline_d(
    dirty: pd.DataFrame,
    target: str,
    profile: dict[str, float],
    learner: LearnerSpec,
    seed: int,
) -> DoseResponse:
    """Baseline (d) dose–response, hanya dari data kotor Dₖ dan profilnya (ADR 0011 G2-7).

    1. Taksiran proporsi baris terdampak per jenis (missing dari data, lainnya dari profil);
       jenis terdeteksi bila taksirannya > 0.
    2. Dₖ dibagi berstrata 80/20 (seed tetap); korupsi tambahan hanya di bagian latih.
    3. Dosis +5%, +10%, +20% baris terdampak, dibagi antar-jenis sebanding taksirannya.
    4. Learner acuan dilatih untuk empat titik; AUC diukur pada hold-out data kotor.
    5. Garis AUC terhadap proporsi terdampak total diekstrapolasi ke nol:
       Δ = AUC(0) − AUC saat ini; kuadratik sebagai pembanding.
    """
    import time

    from sklearn.model_selection import train_test_split

    from ceteris.corrupt import CorruptionContext, corrupt, parse_spec
    from ceteris.seeding import sub_seed
    from ceteris.train import auc_score, feature_importance, fit_predict_proba

    start = time.perf_counter()
    features = [c for c in dirty.columns if c != target]
    train, holdout = train_test_split(
        dirty,
        test_size=HOLDOUT_FRAC,
        stratify=dirty[target],
        random_state=sub_seed(seed, "d_split") % (2**32),
    )
    train = train.reset_index(drop=True)
    holdout = holdout.reset_index(drop=True)
    detected: dict[str, float] = {}
    for kind, column in DOSE_TYPES.items():
        share = (
            float(dirty[features].isna().any(axis=1).mean())
            if column is None
            else float(profile[column])
        )
        if share > 0:
            detected[kind] = share
    learner_seed = sub_seed(seed, "d_learner")
    y_holdout = holdout[target].cat.codes.to_numpy()
    auc_current = auc_score(
        y_holdout, fit_predict_proba(learner, train, holdout, target, learner_seed)
    )
    p0 = min(sum(detected.values()), 1.0)
    points = [(p0, auc_current)]
    if detected:
        importance = feature_importance(learner, train, target, sub_seed(seed, "d_importance"))
        context = CorruptionContext(
            importance_order=tuple(importance.sort_values(ascending=False).index),
            confusion_target={},
        )
        n_columns = min(3, len(features))
        for i, dose in enumerate(DOSES):
            specs = []
            for kind, share in detected.items():
                level = _level_for_rows(kind, dose * share / p0, n_columns)
                if level > 0:
                    payload: dict[str, Any] = {"kind": kind, "level": level}
                    specs.append(parse_spec(payload))
            # Outlier tanpa kolom numerik tidak terdeteksi (taksiran Isolation Forest = 0).
            result = corrupt(train, target, specs, sub_seed(seed, f"d_dose{i}"), context)
            auc = auc_score(
                y_holdout, fit_predict_proba(learner, result.frame, holdout, target, learner_seed)
            )
            points.append((p0 + result.affected_row_frac, auc))
    x = np.array([p for p, _ in points])
    y = np.array([a for _, a in points])
    if len(points) < 2 or np.ptp(x) == 0:
        delta_linear = delta_quadratic = 0.0
    else:
        delta_linear = float(np.polyval(np.polyfit(x, y, 1), 0.0) - auc_current)
        degree = 2 if len(points) >= 3 else 1
        delta_quadratic = float(np.polyval(np.polyfit(x, y, degree), 0.0) - auc_current)
    return DoseResponse(
        delta_linear=delta_linear,
        delta_quadratic=delta_quadratic,
        auc_current=float(auc_current),
        p0_total=float(p0),
        detected=detected,
        points=[(float(p), float(a)) for p, a in points],
        seconds=time.perf_counter() - start,
        n_train=len(train),
        n_holdout=len(holdout),
    )


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
