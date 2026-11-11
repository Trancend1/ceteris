"""ceteris.train: learner acuan (LightGBM), AUC, dan ΔAUC.

Fitur: F-S03 (docs/product.md); bagian noise floor terukur (F-S06) menyusul di Phase 2.
Jalur: riset. Aturan: BR-01 (ΔAUC pada test set bersih yang sama), BR-02 (ΔAUC relatif),
BR-03 (learner acuan deterministik dari `configs/learner.yaml`), BR-07 (hanya ΔAUC).

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


def fit_predict_proba(
    spec: LearnerSpec,
    train: pd.DataFrame,
    test: pd.DataFrame,
    target: str,
    seed: int,
) -> np.ndarray:
    """Latih learner acuan pada `train`, kembalikan probabilitas kelas untuk `test` (n × K)."""
    x_train, y_train = _xy(train, target)
    x_test, _ = _xy(test, target)
    if list(train[target].cat.categories) != list(test[target].cat.categories):
        raise ValueError("kategori target latih dan uji harus identik")
    n_classes = len(train[target].cat.categories)
    params: dict[str, Any] = {**spec.params, "seed": int(seed)}
    if n_classes == 2:
        params["objective"] = "binary"
    else:
        params.update(objective="multiclass", num_class=n_classes)
    dataset = lgb.Dataset(x_train, label=y_train, free_raw_data=True)
    booster = lgb.train(params, dataset, num_boost_round=spec.num_boost_round)
    raw = np.asarray(booster.predict(x_test))
    if n_classes == 2:
        return np.column_stack([1.0 - raw, raw])
    return raw.reshape(len(x_test), n_classes)


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
