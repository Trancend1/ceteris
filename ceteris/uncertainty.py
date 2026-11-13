"""ceteris.uncertainty: interval conformal berbobot dataset dan skor OOD.

Fitur: F-S10 (docs/product.md). Jalur: riset dan scan. Aturan: BR-22 (interval 90% conformal
berbasis grup), BR-24 dan AC-8 (skor OOD = jarak kNN profil, bukan fitur meta-model).

Keputusan pemilik repo 12/11/2026 (ADR 0011): kuantil conformal memberi bobot sama pada setiap
dataset, interval tidak dipotong di nol, dan ambang OOD pilot adalah persentil ke-95 skor OOD
leave-one-dataset-out (sementara sampai G3). Modul ini tidak mengimpor kode eksperimen (AC-3).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

COVERAGE = 0.90


def weighted_conformal_quantile(
    scores: Sequence[float], groups: Sequence[object], coverage: float = COVERAGE
) -> float:
    """Kuantil conformal dengan bobot sama per dataset (BR-22, hal terbuka #4).

    Skor run ke-i berbobot w_i = 1 / (jumlah run datasetnya), sehingga setiap dataset berbobot 1.
    Titik baru berbobot rata-rata bobot run (Σw / n) dan diletakkan di +∞. Kuantilnya adalah skor
    terkecil s dengan Σ_{s_j ≤ s} w_j / (Σw + w_baru) ≥ `coverage`. Bila setiap dataset punya
    jumlah run yang sama, hasilnya sama dengan kuantil biasa ⌈(n + 1) × 0,90⌉ (Contoh 3).
    Mengembalikan +∞ bila data kalibrasi terlalu sedikit untuk cakupan yang diminta.
    """
    values = np.asarray(scores, dtype="float64")
    if values.size == 0:
        raise ValueError("kalibrasi conformal butuh minimal satu skor")
    if values.size != len(groups):
        raise ValueError("jumlah skor dan grup harus sama")
    if not 0.0 < coverage < 1.0:
        raise ValueError("coverage harus di antara 0 dan 1")
    labels = pd.Series(list(groups), dtype="object")
    weights = 1.0 / labels.map(labels.value_counts()).to_numpy(dtype="float64")
    w_new = weights.sum() / values.size
    order = np.argsort(values, kind="stable")
    cumulative = np.cumsum(weights[order]) / (weights.sum() + w_new)
    hits = np.flatnonzero(cumulative >= coverage - 1e-12)
    return float(values[order][hits[0]]) if hits.size else float("inf")


def conformal_interval(prediction: float, quantile: float) -> tuple[float, float]:
    """Interval 90% `prediksi ± kuantil`; tidak dipotong di nol (hal terbuka #5, ADR 0011)."""
    return float(prediction - quantile), float(prediction + quantile)


# --- skor OOD (BR-24) ---


@dataclass(frozen=True)
class OODReference:
    """Profil korpus pelatihan (terstandar) untuk jarak kNN. Bukan input meta-model (AC-8)."""

    features: tuple[str, ...]
    center: np.ndarray
    scale: np.ndarray
    points: np.ndarray
    k: int

    def standardise(self, vectors: np.ndarray) -> np.ndarray:
        matrix = np.atleast_2d(np.asarray(vectors, dtype="float64"))
        return np.asarray((matrix - self.center) / self.scale)

    def score(self, vector: Sequence[float]) -> float:
        """Rata-rata jarak Euclid (terstandar) ke k profil referensi terdekat."""
        return float(
            _knn_mean_distance(self.standardise(np.asarray(vector)), self.points, self.k)[0]
        )

    def scores(self, matrix: np.ndarray) -> np.ndarray:
        """Skor OOD untuk banyak profil sekaligus (baris = profil, kolom = `features`)."""
        return _knn_mean_distance(self.standardise(matrix), self.points, self.k)


def fit_ood_reference(profiles: pd.DataFrame, features: Sequence[str], k: int) -> OODReference:
    """Standarisasi z per fitur dari profil referensi; fitur konstan memakai skala 1."""
    if k < 1:
        raise ValueError("k harus >= 1")
    matrix = profiles[list(features)].to_numpy(dtype="float64")
    if len(matrix) < k:
        raise ValueError(f"referensi OOD butuh minimal {k} profil")
    center = matrix.mean(axis=0)
    scale = matrix.std(axis=0)
    scale = np.where(scale > 0, scale, 1.0)
    return OODReference(
        features=tuple(features),
        center=center,
        scale=scale,
        points=(matrix - center) / scale,
        k=int(k),
    )


def _knn_mean_distance(queries: np.ndarray, points: np.ndarray, k: int) -> np.ndarray:
    from sklearn.neighbors import NearestNeighbors

    k_eff = min(k, points.shape[0])
    distances, _ = NearestNeighbors(n_neighbors=k_eff).fit(points).kneighbors(queries)
    return np.asarray(distances.mean(axis=1))


def lodo_ood_scores(
    profiles: pd.DataFrame, groups: Sequence[object], features: Sequence[str], k: int
) -> np.ndarray:
    """Skor OOD tiap profil terhadap profil dataset lain (leave-one-dataset-out).

    Standarisasi memakai seluruh profil sekali, agar skala sama dengan referensi akhir.
    """
    reference = fit_ood_reference(profiles, features, k)
    labels = np.asarray(list(groups), dtype="object")
    scores = np.empty(len(labels))
    for group in pd.unique(labels):
        inside = labels == group
        if (~inside).sum() == 0:
            raise ValueError("skor OOD LODO butuh minimal dua dataset")
        scores[inside] = _knn_mean_distance(reference.points[inside], reference.points[~inside], k)
    return scores


def ood_threshold(lodo_scores: Sequence[float] | np.ndarray, percentile: float = 95.0) -> float:
    """Ambang "OOD tinggi" sementara: persentil skor OOD LODO (ADR 0011; BR #3 tetap [T])."""
    values = np.asarray(lodo_scores, dtype="float64")
    if values.size == 0:
        raise ValueError("ambang OOD butuh minimal satu skor")
    return float(np.percentile(values, percentile))
