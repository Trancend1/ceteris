"""ceteris.train: learner acuan (LightGBM), AUC, dan ΔAUC.

Fitur: F-S03 (docs/product.md); noise floor terukur dan probe (F-S06, F-S05).
Jalur: riset dan scan (probe). Aturan: BR-01 (ΔAUC pada test set bersih yang sama), BR-02 (ΔAUC
relatif), BR-03 (learner acuan deterministik dari `configs/learner.yaml`, juga untuk probe),
BR-04 (noise floor terukur), BR-07 (hanya ΔAUC); ADR 0009 K1 (bagging agar seed berpengaruh).

Modul ini tidak mengimpor kode korupsi atau korpus, sehingga spesifikasi learner bisa dipakai
probe di jalur scan tanpa melanggar AC-3.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold

from ceteris.seeding import sub_seed

# Parameter yang diatur oleh harness, bukan oleh berkas spesifikasi.
_RESERVED = {"objective", "num_class", "seed", "random_state", "num_iterations", "n_estimators"}


class LearnerSpec(BaseModel):
    """Spesifikasi learner acuan (BR-03). Dibekukan di G1; perubahan sesudahnya = versi baru."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = Field(min_length=1)
    num_boost_round: int = Field(ge=1)
    params: dict[str, Any]

    @field_validator("params")
    @classmethod
    def _deterministic(cls, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("deterministic") is not True:
            raise ValueError("learner acuan wajib deterministic: true (BR-03)")
        if not (params.get("force_row_wise") or params.get("force_col_wise")):
            raise ValueError("learner acuan wajib force_row_wise atau force_col_wise (BR-03)")
        reserved = _RESERVED.intersection(params)
        if reserved:
            raise ValueError(f"parameter diatur harness, jangan di spesifikasi: {sorted(reserved)}")
        fraction = params.get("bagging_fraction", 1.0)
        if not (int(params.get("bagging_freq", 0)) >= 1 and 0.0 < float(fraction) < 1.0):
            raise ValueError(
                "learner acuan wajib bagging aktif (bagging_freq >= 1, 0 < bagging_fraction < 1) "
                "agar seed berpengaruh pada noise floor (ADR 0009 K1)"
            )
        return params


def load_learner_spec(path: Path) -> LearnerSpec:
    """Muat `configs/learner.yaml`."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return LearnerSpec.model_validate(raw)


def _xy(frame: pd.DataFrame, target: str) -> tuple[pd.DataFrame, np.ndarray]:
    if not isinstance(frame[target].dtype, pd.CategoricalDtype):
        raise ValueError("target harus kategorikal (protokol D₀)")
    codes = frame[target].cat.codes.to_numpy()
    if (codes < 0).any():
        raise ValueError("target tidak boleh kosong")
    features = frame.drop(columns=[target])
    # LightGBM menolak beberapa karakter JSON di nama fitur; nama posisi menghindarinya.
    features.columns = [f"f{i}" for i in range(features.shape[1])]
    return features, codes.astype(np.int64)


def _fit(spec: LearnerSpec, train: pd.DataFrame, target: str, seed: int) -> lgb.Booster:
    x_train, y_train = _xy(train, target)
    n_classes = len(train[target].cat.categories)
    params: dict[str, Any] = {**spec.params, "seed": int(seed)}
    if n_classes == 2:
        params["objective"] = "binary"
    else:
        params.update(objective="multiclass", num_class=n_classes)
    dataset = lgb.Dataset(x_train, label=y_train, free_raw_data=True)
    return lgb.train(params, dataset, num_boost_round=spec.num_boost_round)


def _predict(booster: lgb.Booster, frame: pd.DataFrame, target: str) -> np.ndarray:
    x, _ = _xy(frame, target)
    n_classes = len(frame[target].cat.categories)
    raw = np.asarray(booster.predict(x))
    if n_classes == 2:
        return np.column_stack([1.0 - raw, raw])
    return raw.reshape(len(x), n_classes)


def fit_predict_proba(
    spec: LearnerSpec,
    train: pd.DataFrame,
    test: pd.DataFrame,
    target: str,
    seed: int,
) -> np.ndarray:
    """Latih learner acuan pada `train`, kembalikan probabilitas kelas untuk `test` (n × K)."""
    _xy(train, target)
    _xy(test, target)
    if list(train[target].cat.categories) != list(test[target].cat.categories):
        raise ValueError("kategori target latih dan uji harus identik")
    return _predict(_fit(spec, train, target, seed), test, target)


def oof_predict_proba(
    spec: LearnerSpec,
    frame: pd.DataFrame,
    target: str,
    seed: int,
    n_folds: int = 5,
    split_seed: int | None = None,
) -> np.ndarray:
    """Probabilitas out-of-fold dari validasi silang berstrata (probe dan confident learning).

    `split_seed` menentukan pembagian lipatan (bawaan: `seed`); seed learner tiap lipatan
    diturunkan dari `seed` sehingga tidak bertabrakan antar-seed.
    """
    _, y = _xy(frame, target)
    proba = np.zeros((len(frame), len(frame[target].cat.categories)))
    split = int(seed if split_seed is None else split_seed)
    folds = StratifiedKFold(n_splits=n_folds, shuffle=True, random_state=split)
    for fold, (fit_idx, val_idx) in enumerate(folds.split(np.zeros(len(y)), y)):
        booster = _fit(spec, frame.iloc[fit_idx], target, sub_seed(seed, f"fold{fold}"))
        proba[val_idx] = _predict(booster, frame.iloc[val_idx], target)
    return proba


def feature_importance(spec: LearnerSpec, frame: pd.DataFrame, target: str, seed: int) -> pd.Series:
    """Importance gain per kolom fitur, dinormalisasi berjumlah 1 (nol semua bila tanpa split)."""
    booster = _fit(spec, frame, target, seed)
    gain = np.asarray(booster.feature_importance(importance_type="gain"), dtype="float64")
    total = gain.sum()
    names = [c for c in frame.columns if c != target]
    return pd.Series(gain / total if total > 0 else gain, index=names, dtype="float64")


def measure_noise_floor(
    spec: LearnerSpec,
    train: pd.DataFrame,
    test: pd.DataFrame,
    target: str,
    seeds: list[int],
) -> list[float]:
    """BR-04 noise floor terukur: AUC model versi bersih per seed pada test set yang sama.

    Statistik ringkasnya (rentang, simpangan baku, atau persentil) masih terbuka sampai G2
    (`business-rules.md` hal terbuka #1), jadi fungsi ini mengembalikan AUC per seed.
    """
    if len(seeds) < 2:
        raise ValueError("noise floor butuh minimal dua seed")
    _, y_test = _xy(test, target)
    return [auc_score(y_test, fit_predict_proba(spec, train, test, target, s)) for s in seeds]


def auc_score(y_true: np.ndarray, proba: np.ndarray) -> float:
    """AUC; multikelas memakai macro one-vs-rest (BR-01)."""
    n_classes = proba.shape[1]
    if n_classes == 2:
        return float(roc_auc_score(y_true, proba[:, 1]))
    return float(
        roc_auc_score(
            y_true, proba, multi_class="ovr", average="macro", labels=list(range(n_classes))
        )
    )


def delta_auc(auc_clean: float, auc_dirty: float) -> float:
    """BR-01: AUC model versi bersih − AUC model versi kotor. Positif berarti rugi."""
    return float(auc_clean - auc_dirty)


def delta_auc_relative(auc_clean: float, delta: float) -> float:
    """BR-02: ΔAUC / (AUC bersih − 0,5). NaN bila tidak ada headroom di atas tebakan acak."""
    headroom = auc_clean - 0.5
    if headroom <= 0:
        return math.nan
    return float(delta / headroom)


@dataclass(frozen=True)
class DeltaAUCResult:
    """Hasil pengukuran ΔAUC satu run."""

    auc_clean: float
    auc_dirty: float
    delta_auc: float
    delta_auc_relative: float


def measure_delta_auc(
    spec: LearnerSpec,
    train_clean: pd.DataFrame,
    train_dirty: pd.DataFrame,
    test: pd.DataFrame,
    target: str,
    seed: int,
) -> DeltaAUCResult:
    """Latih dua model (learner dan seed sama), nilai pada satu test set bersih (BR-01)."""
    _, y_test = _xy(test, target)
    auc_clean = auc_score(y_test, fit_predict_proba(spec, train_clean, test, target, seed))
    auc_dirty = auc_score(y_test, fit_predict_proba(spec, train_dirty, test, target, seed))
    delta = delta_auc(auc_clean, auc_dirty)
    return DeltaAUCResult(
        auc_clean=auc_clean,
        auc_dirty=auc_dirty,
        delta_auc=delta,
        delta_auc_relative=delta_auc_relative(auc_clean, delta),
    )
