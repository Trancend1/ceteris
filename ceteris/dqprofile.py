"""ceteris.dqprofile: kontrak input dan quality profile v1, dihitung dari data kotor saja.

Fitur: F-S04 (profil dan kontrak input), F-S05 (estimator label noise), F-S06 (noise floor
estimasi). Jalur: riset **dan** scan, satu implementasi (AC-1); modul ini tidak mengimpor kode
eksperimen (AC-3). Aturan: BR-03 (probe = learner acuan), BR-10–BR-17 (kontrak input), BR-20
(hanya data kotor), BR-12 (sampel); keputusan di ADR 0005, 0007, dan 0009.

Fungsi publik hanya menerima satu DataFrame (data kotor) dan nama kolom target; tidak ada jalur
untuk versi bersih atau level korupsi (BR-20, AC-2).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from ceteris.seeding import derive_seed, sub_seed
from ceteris.train import LearnerSpec, auc_score, feature_importance, oof_predict_proba

PROFILE_SCHEMA_VERSION = "v1"

# Seed tetap profil (BR-12): sama di jalur riset dan scan, sehingga data yang sama selalu
# memberi profil yang sama (BR-16), tidak bergantung pada `config_id` run riset.
PROFILE_SEED = derive_seed("dqprofile", PROFILE_SCHEMA_VERSION)

# Urutan fitur profil v1. Mengubah, menambah, atau menghapus fitur berarti versi skema baru.
FEATURES: tuple[str, ...] = (
    # konteks dataset (terobservasi)
    "n_rows",
    "n_features",
    "frac_numeric",
    "n_classes",
    "class_imbalance",
    "cat_cardinality_ratio_mean",
    # probe (terobservasi)
    "probe_auc",
    "importance_top1_share",
    # missing (terobservasi)
    "missing_rate",
    "missing_col_max",
    "missing_col_mean",
    "missing_col_std",
    "missing_rate_weighted",
    "missing_target_assoc",
    "missing_feature_assoc",
    # label noise
    "label_noise_rate",
    "dup_conflict_rate",
    # outlier
    "outlier_cell_frac_iqr",
    "outlier_row_frac_iforest",
    "outlier_rate_weighted",
    "skew_abs_mean",
    "kurtosis_mean",
    # duplikat dan tipe (terobservasi)
    "dup_row_rate",
    "const_col_frac",
    "type_inconsistency_rate",
)

# Nilai "tanpa temuan" struktural, tidak bergantung data (ADR 0006). Fitur yang tidak ada di sini
# tidak punya nilai ideal struktural dan tidak dinormalkan saat menghitung potensi pemulihan.
NO_FINDING: dict[str, float] = {
    "missing_rate": 0.0,
    "missing_col_max": 0.0,
    "missing_col_mean": 0.0,
    "missing_col_std": 0.0,
    "missing_rate_weighted": 0.0,
    "missing_target_assoc": 0.0,
    "missing_feature_assoc": 0.0,
    "label_noise_rate": 0.0,
    "dup_conflict_rate": 0.0,
    "outlier_cell_frac_iqr": 0.0,
    "outlier_row_frac_iforest": 0.0,
    "outlier_rate_weighted": 0.0,
    "dup_row_rate": 0.0,
    "const_col_frac": 0.0,
    "type_inconsistency_rate": 0.0,
}

# Batas jumlah kolom ber-missing yang diperiksa untuk asosiasi missingness–fitur (biaya O(m·p)).
MAX_ASSOC_COLUMNS = 50


class InputContractError(ValueError):
    """Pelanggaran berat kontrak input: scan berhenti tanpa profil maupun estimasi parsial."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


class ProfileConfig(BaseModel):
    """Parameter kontrak input dan profil. Dibekukan bersama skema v1 di G1."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_rows: int = Field(default=1_000_000, ge=1)  # BR-10
    max_features: int = Field(default=500, ge=1)  # BR-10
    min_classes: int = Field(default=2, ge=2)  # BR-11
    max_classes: int = Field(default=20, ge=2)  # BR-11
    min_class_count: int = Field(default=20, ge=1)  # BR-11
    sample_max_rows: int = Field(default=100_000, ge=100)  # BR-12
    id_unique_ratio: float = Field(default=0.95, gt=0.0, le=1.0)  # BR-13, ADR 0005
    text_min_median_tokens: int = Field(default=5, ge=2)  # BR-14, usulan awal
    n_folds: int = Field(default=5, ge=2)  # ADR 0005 dan 0009 K2
    leakage_auc: float = Field(default=0.99, gt=0.5, le=1.0)  # BR-15, ADR 0005
    leakage_max_depth: int = Field(default=4, ge=1)  # ADR 0005, dikalibrasi di ADR 0010
    leakage_min_samples_leaf: float = Field(default=0.01, gt=0.0, lt=0.5)  # ADR 0005, ADR 0010
    # ADR 0007: "fixed" diputuskan; "adaptive" tetap tersedia untuk evaluasi riset (E0).
    leakage_threshold: Literal["fixed", "adaptive"] = "fixed"
    leakage_tau_min: float = Field(default=0.90, gt=0.5, le=1.0)  # ADR 0007, hanya opsi adaptif


class LeakageResult(BaseModel):
    """Hasil probe kebocoran target (BR-15)."""

    model_config = ConfigDict(frozen=True)

    flagged: bool
    feature: str | None
    auc: float | None
    threshold: float


class QualityProfile(BaseModel):
    """Quality profile v1 satu dataset kotor beserta catatan kontrak inputnya."""

    model_config = ConfigDict(frozen=True)

    schema_version: str
    features: dict[str, float]
    n_rows_input: int
    n_rows_used: int
    sample_size: int
    dropped_columns: dict[str, str]
    input_warnings: list[str]
    leakage: LeakageResult

    def vector(self) -> list[float]:
        """Nilai fitur dalam urutan `FEATURES`."""
        return [self.features[name] for name in FEATURES]


@dataclass(frozen=True)
class _Prepared:
    frame: pd.DataFrame
    target: str
    n_rows_input: int
    dropped: dict[str, str]
    warnings: list[str]


def compute_profile(
    dirty: pd.DataFrame,
    target: str,
    *,
    learner: LearnerSpec,
    seed: int,
    config: ProfileConfig | None = None,
) -> QualityProfile:
    """Terapkan kontrak input (BR-10–BR-17) lalu hitung quality profile v1 dari data kotor.

    Pelanggaran berat menghasilkan `InputContractError` tanpa profil parsial.
    """
    cfg = config or ProfileConfig()
    prepared = prepare_input(dirty, target, cfg)
    frame = prepared.frame
    sample = _sample(frame, target, cfg, sub_seed(seed, "sample"))
    features = [c for c in frame.columns if c != target]

    importance = feature_importance(learner, sample, target, sub_seed(seed, "importance"))
    proba = oof_predict_proba(learner, sample, target, sub_seed(seed, "probe"), cfg.n_folds)
    y_sample = _codes(sample, target)
    label_noise = label_noise_rate(y_sample, proba)

    values: dict[str, float] = {}
    values.update(_context_features(frame, target, features))
    values["probe_auc"] = auc_score(y_sample, proba)
    values["importance_top1_share"] = float(importance.max()) if len(importance) else 0.0
    values.update(_missing_features(frame, target, features, importance))
    values["label_noise_rate"] = label_noise
    values["dup_conflict_rate"] = _dup_conflict_rate(frame, target, features)
    values.update(_outlier_features(frame, features, importance))
    values["outlier_row_frac_iforest"] = _iforest_rate(sample, features, sub_seed(seed, "iforest"))
    values.update(_duplicate_type_features(frame, target, features))

    leakage = _leakage_probe(sample, target, features, cfg, label_noise, sub_seed(seed, "leakage"))
    warnings = list(prepared.warnings)
    if leakage.flagged:
        warnings.append(f"target_leakage_suspected: {leakage.feature}")
    return QualityProfile(
        schema_version=PROFILE_SCHEMA_VERSION,
        features={name: float(values[name]) for name in FEATURES},
        n_rows_input=prepared.n_rows_input,
        n_rows_used=len(frame),
        sample_size=len(sample),
        dropped_columns=prepared.dropped,
        input_warnings=warnings,
        leakage=leakage,
    )


def noise_floor_seeds(n: int) -> list[int]:
    """Seed probe tetap untuk noise floor estimasi, sama di jalur riset dan scan (BR-16, AC-12)."""
    if n < 2:
        raise ValueError("noise floor butuh minimal dua seed")
    return [sub_seed(PROFILE_SEED, f"noise_floor_seed_{i}") for i in range(n)]


def estimate_noise_floor(
    dirty: pd.DataFrame,
    target: str,
    *,
    learner: LearnerSpec,
    seeds: list[int],
    config: ProfileConfig | None = None,
) -> list[float]:
    """F-S06 noise floor estimasi (BR-04): AUC out-of-fold probe per seed pada data kotor.

    Pembagian lipatan tetap; hanya seed learner (bagging) yang berbeda antar-seed, sama seperti
    noise floor terukur yang memakai split latih/uji tetap. Statistik ringkas dan jumlah seed masih
    terbuka sampai G2 (`business-rules.md` hal terbuka #1).
    """
    if len(seeds) < 2:
        raise ValueError("noise floor butuh minimal dua seed")
    cfg = config or ProfileConfig()
    prepared = prepare_input(dirty, target, cfg)
    sample = _sample(prepared.frame, target, cfg, sub_seed(PROFILE_SEED, "sample"))
    y = _codes(sample, target)
    split = sub_seed(PROFILE_SEED, "noise_floor_split")
    return [
        auc_score(y, oof_predict_proba(learner, sample, target, s, cfg.n_folds, split_seed=split))
        for s in seeds
    ]


# --- kontrak input (BR-10–BR-17) ---


def prepare_input(dirty: pd.DataFrame, target: str, config: ProfileConfig) -> _Prepared:
    """Kontrak input: tolak pelanggaran berat, catat peringatan, dan siapkan tipe kolom.

    Data sumber tidak diubah (BR-70): fungsi bekerja pada salinan.
    """
    if target not in dirty.columns:
        raise InputContractError([f"target_missing: kolom {target!r} tidak ada"])
    n_rows_input = len(dirty)
    n_features = dirty.shape[1] - 1
    reasons: list[str] = []
    if n_rows_input > config.max_rows:
        reasons.append(f"too_many_rows: {n_rows_input} > {config.max_rows} (BR-10)")
    if n_features > config.max_features:
        reasons.append(f"too_many_columns: {n_features} > {config.max_features} (BR-10)")
    if reasons:
        raise InputContractError(reasons)

    warnings: list[str] = []
    frame = dirty.copy()
    missing_target = int(frame[target].isna().sum())
    if missing_target:
        frame = frame.loc[frame[target].notna()]
        warnings.append(f"target_missing_rows_excluded: {missing_target}")
    frame = frame.reset_index(drop=True)
    labels = frame[target].astype("str")
    frame[target] = pd.Categorical(labels, categories=sorted(pd.unique(labels)))
    counts = frame[target].value_counts()
    if not config.min_classes <= len(counts) <= config.max_classes:
        reasons.append(
            f"class_count: {len(counts)} di luar {config.min_classes}-{config.max_classes} (BR-11)"
        )
    elif int(counts.min()) < config.min_class_count:
        reasons.append(f"class_too_small: {int(counts.min())} < {config.min_class_count} (BR-11)")
    if reasons:
        raise InputContractError(reasons)

    dropped: dict[str, str] = {}
    for name in [c for c in frame.columns if c != target]:
        column, reason, warning = _prepare_column(frame[name], len(frame), config)
        if reason is not None:
            dropped[str(name)] = reason
            warnings.append(f"{reason}: {name}")
            frame = frame.drop(columns=[name])
            continue
        frame[name] = column
        if warning is not None:
            warnings.append(f"{warning}: {name}")
    if frame.shape[1] == 1:
        raise InputContractError(["no_features: semua kolom fitur dikeluarkan kontrak input"])
    return _Prepared(frame, target, n_rows_input, dropped, warnings)


def _prepare_column(
    column: pd.Series, n_rows: int, config: ProfileConfig
) -> tuple[pd.Series, str | None, str | None]:
    """Kembalikan (kolom siap pakai, alasan dikeluarkan, peringatan konversi)."""
    dtype = column.dtype
    id_candidate = _id_candidate(column)
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return _datetime_days(column), None, "datetime_converted"  # BR-14
    if (
        pd.api.types.is_bool_dtype(dtype)
        or pd.api.types.is_object_dtype(dtype)
        or (pd.api.types.is_string_dtype(dtype) and not isinstance(dtype, pd.CategoricalDtype))
    ):
        if _is_free_text(column, config.text_min_median_tokens):
            return column, "text_column_dropped", None  # BR-14
        column = column.astype("category")
    elif pd.api.types.is_extension_array_dtype(dtype) and not isinstance(
        dtype, pd.CategoricalDtype
    ):
        if pd.api.types.is_integer_dtype(dtype) and not column.isna().any():
            column = column.astype("int64")
        else:
            column = pd.Series(column.to_numpy(dtype="float64", na_value=np.nan), name=column.name)
    if id_candidate and column.nunique(dropna=True) / max(n_rows, 1) >= config.id_unique_ratio:
        return column, "id_column_dropped", None  # BR-13
    return column, None, None


def _id_candidate(column: pd.Series) -> bool:
    """BR-13 berlaku untuk kolom non-float pada tipe asalnya, termasuk kolom float yang semua
    nilainya bilangan bulat (integer yang menjadi float karena ada nilai kosong)."""
    if not pd.api.types.is_float_dtype(column.dtype):
        return True
    values = column.dropna().to_numpy(dtype="float64")
    return bool(len(values)) and bool(np.all(np.mod(values, 1.0) == 0.0))


def _datetime_days(column: pd.Series) -> pd.Series:
    epoch = pd.Timestamp("1970-01-01", tz=getattr(column.dt, "tz", None))
    return (column - epoch) / pd.Timedelta(days=1)


def _is_free_text(column: pd.Series, min_tokens: int) -> bool:
    values = column.dropna().astype("str")
    if values.empty:
        return False
    return bool(values.str.split().str.len().median() >= min_tokens)


def _sample(frame: pd.DataFrame, target: str, config: ProfileConfig, seed: int) -> pd.DataFrame:
    """BR-12: sampel berstrata ≤ `sample_max_rows` baris dengan seed tetap."""
    if len(frame) <= config.sample_max_rows:
        return frame
    from sklearn.model_selection import train_test_split

    rows, _ = train_test_split(
        np.arange(len(frame)),
        train_size=config.sample_max_rows,
        stratify=_codes(frame, target),
        random_state=seed,
    )
    return frame.iloc[np.sort(rows)].reset_index(drop=True)


def _codes(frame: pd.DataFrame, target: str) -> np.ndarray:
    return np.asarray(frame[target].cat.codes.to_numpy(), dtype=np.int64)


def _is_numeric(column: pd.Series) -> bool:
    dtype = column.dtype
    return bool(
        pd.api.types.is_numeric_dtype(dtype)
        and not pd.api.types.is_bool_dtype(dtype)
        and not isinstance(dtype, pd.CategoricalDtype)
    )


# --- fitur profil ---


def _context_features(frame: pd.DataFrame, target: str, features: list[str]) -> dict[str, float]:
    counts = frame[target].value_counts()
    counts = counts[counts > 0]
    categorical = [c for c in features if not _is_numeric(frame[c])]
    ratios = [frame[c].nunique(dropna=True) / len(frame) for c in categorical]
    return {
        "n_rows": float(len(frame)),
        "n_features": float(len(features)),
        "frac_numeric": (len(features) - len(categorical)) / len(features),
        "n_classes": float(len(counts)),
        "class_imbalance": float(counts.min() / counts.max()),
        "cat_cardinality_ratio_mean": float(np.mean(ratios)) if ratios else 0.0,
    }


def _missing_features(
    frame: pd.DataFrame, target: str, features: list[str], importance: pd.Series
) -> dict[str, float]:
    rates = frame[features].isna().mean()
    y = _codes(frame, target)
    target_assoc = 0.0
    for name in rates[rates > 0].index:
        indicator = frame[name].isna().to_numpy()
        overall = indicator.mean()
        for code in np.unique(y):
            target_assoc = max(target_assoc, abs(float(indicator[y == code].mean() - overall)))
    return {
        "missing_rate": float(frame[features].isna().to_numpy().mean()),
        "missing_col_max": float(rates.max()),
        "missing_col_mean": float(rates.mean()),
        "missing_col_std": float(rates.std(ddof=0)),
        "missing_rate_weighted": float((rates * importance.reindex(rates.index).fillna(0)).sum()),
        "missing_target_assoc": target_assoc,
        "missing_feature_assoc": _missing_feature_assoc(frame, features, rates),
    }


def _missing_feature_assoc(frame: pd.DataFrame, features: list[str], rates: pd.Series) -> float:
    """Asosiasi missingness dengan fitur numerik lain (indikasi MAR): |Spearman| maksimum."""
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


def _as_float(column: pd.Series) -> pd.Series:
    return pd.Series(column.to_numpy(dtype="float64", na_value=np.nan))


def label_noise_rate(y: np.ndarray, proba: np.ndarray) -> float:
    """F-S05: proporsi label bermasalah menurut confident learning (cleanlab, ADR 0009 K2)."""
    from cleanlab.count import num_label_issues

    return float(num_label_issues(labels=y, pred_probs=proba)) / len(y)


def _row_hash(frame: pd.DataFrame) -> np.ndarray:
    return np.asarray(pd.util.hash_pandas_object(frame, index=False).to_numpy())


def _dup_conflict_rate(frame: pd.DataFrame, target: str, features: list[str]) -> float:
    """Proporsi baris dalam kelompok fitur identik yang labelnya lebih dari satu."""
    keys = pd.Series(_row_hash(frame[features]))
    labels = pd.Series(_codes(frame, target))
    distinct = labels.groupby(keys).transform("nunique")
    return float((distinct > 1).mean())


def _outlier_features(
    frame: pd.DataFrame, features: list[str], importance: pd.Series
) -> dict[str, float]:
    numeric = [c for c in features if _is_numeric(frame[c])]
    outside = 0
    observed = 0
    per_column: dict[str, float] = {}
    skews: list[float] = []
    kurts: list[float] = []
    for name in numeric:
        values = _as_float(frame[name]).dropna()
        if values.empty:
            continue
        q1, q3, spread = quartiles_with_fallback(values)
        mask = (values < q1 - 1.5 * spread) | (values > q3 + 1.5 * spread)
        outside += int(mask.sum())
        observed += len(values)
        per_column[name] = float(mask.mean())
        if len(values) >= 4 and values.std() > 0:
            skews.append(abs(float(values.skew())))
            kurts.append(float(values.kurt()))
    weighted = sum(per_column.get(name, 0.0) * float(importance.get(name, 0.0)) for name in numeric)
    return {
        "outlier_cell_frac_iqr": outside / observed if observed else 0.0,
        "outlier_rate_weighted": weighted,
        "skew_abs_mean": float(np.mean(skews)) if skews else 0.0,
        "kurtosis_mean": float(np.mean(kurts)) if kurts else 0.0,
    }


def quartiles_with_fallback(values: pd.Series) -> tuple[float, float, float]:
    """Q1, Q3, dan sebaran: IQR; bila nol, simpangan baku; bila nol juga, 1.

    Dipakai profil (pagar 1,5 × sebaran) dan corruption engine (pagar k × sebaran) sehingga
    keduanya melihat skala yang sama, termasuk pada kolom jarang dengan IQR nol.
    """
    if len(values) == 0:
        return 0.0, 0.0, 1.0
    q1, q3 = (float(v) for v in values.quantile([0.25, 0.75]).to_numpy())
    if q3 - q1 > 0:
        return q1, q3, q3 - q1
    std = float(values.std(ddof=0))
    return q1, q3, std if std > 0 else 1.0


def _iforest_rate(sample: pd.DataFrame, features: list[str], seed: int) -> float:
    """Proporsi baris yang dinilai anomali oleh Isolation Forest pada kolom numerik."""
    from sklearn.ensemble import IsolationForest

    numeric = [c for c in features if _is_numeric(sample[c])]
    if not numeric:
        return 0.0
    matrix = sample[numeric].apply(_as_float_column)
    matrix = matrix.fillna(matrix.median()).fillna(0.0)
    model = IsolationForest(n_estimators=100, contamination="auto", random_state=seed)
    return float((model.fit_predict(matrix.to_numpy()) == -1).mean())


def _as_float_column(column: pd.Series) -> pd.Series:
    return pd.Series(column.to_numpy(dtype="float64", na_value=np.nan), index=column.index)


def _duplicate_type_features(
    frame: pd.DataFrame, target: str, features: list[str]
) -> dict[str, float]:
    duplicated = pd.Series(_row_hash(frame)).duplicated(keep="first")
    constant = [c for c in features if frame[c].nunique(dropna=True) <= 1]
    inconsistency: list[float] = []
    for name in features:
        if _is_numeric(frame[name]):
            continue
        values = frame[name].dropna().astype("str")
        if values.empty:
            continue
        share = float(pd.to_numeric(values, errors="coerce").notna().mean())
        inconsistency.append(min(share, 1.0 - share))
    return {
        "dup_row_rate": float(duplicated.mean()),
        "const_col_frac": len(constant) / len(features),
        "type_inconsistency_rate": float(np.mean(inconsistency)) if inconsistency else 0.0,
    }


# --- probe kebocoran target (BR-15, ADR 0005 dan 0007) ---


def _leakage_probe(
    sample: pd.DataFrame,
    target: str,
    features: list[str],
    config: ProfileConfig,
    label_noise: float,
    seed: int,
) -> LeakageResult:
    """AUC satu fitur dengan pohon keputusan dangkal dan validasi silang berstrata."""
    from sklearn.model_selection import StratifiedKFold

    y = _codes(sample, target)
    folds = list(
        StratifiedKFold(n_splits=config.n_folds, shuffle=True, random_state=seed).split(
            np.zeros(len(y)), y
        )
    )
    if config.leakage_threshold == "adaptive":
        threshold = max(config.leakage_tau_min, config.leakage_auc * (1.0 - label_noise))
    else:
        threshold = config.leakage_auc
    best_feature: str | None = None
    best_auc: float | None = None
    for name in features:
        auc = single_feature_auc(sample[name], y, folds, config, seed)
        if best_auc is None or auc > best_auc:
            best_feature, best_auc = name, auc
    flagged = best_auc is not None and best_auc >= threshold
    return LeakageResult(
        flagged=flagged, feature=best_feature, auc=best_auc, threshold=float(threshold)
    )


def single_feature_auc(
    column: pd.Series,
    y: np.ndarray,
    folds: list[tuple[np.ndarray, np.ndarray]],
    config: ProfileConfig,
    seed: int,
) -> float:
    """AUC out-of-fold satu fitur (BR-15): one-vs-rest per kelas, lalu dirata-rata (macro).

    Tiap kelas memakai pohon biner sendiri, sehingga salinan target multikelas tetap terdeteksi.
    Fitur kategorikal dikodekan menurut proporsi kelas itu di lipatan latih; kategori baru dan
    nilai kosong di lipatan validasi memakai proporsi keseluruhan lipatan latih.
    """
    return single_feature_aucs(column, y, folds, [config], seed)[0]


def single_feature_aucs(
    column: pd.Series,
    y: np.ndarray,
    folds: list[tuple[np.ndarray, np.ndarray]],
    configs: Sequence[ProfileConfig],
    seed: int,
) -> list[float]:
    """`single_feature_auc` untuk beberapa konfigurasi pohon sekaligus, dengan hasil yang sama.

    Pengodean kategori per kelas dan lipatan dihitung sekali lalu dipakai semua konfigurasi,
    sehingga kalibrasi probe (ADR 0010) tidak mengulang pekerjaan yang sama.
    """
    from sklearn.metrics import roc_auc_score
    from sklearn.tree import DecisionTreeClassifier

    n_classes = int(y.max()) + 1
    classes = [1] if n_classes == 2 else list(range(n_classes))
    categorical = not _is_numeric(column)
    values = column.astype("object") if categorical else _as_float(column)
    aucs: list[list[float]] = [[] for _ in configs]
    for cls in classes:
        target_c = (y == cls).astype(np.int64)
        scores = [np.zeros(len(y)) for _ in configs]
        for fit_idx, val_idx in folds:
            if categorical:
                x_fit, x_val = _encode_by_rate(values, target_c, fit_idx, val_idx)
            else:
                x_fit = values.iloc[fit_idx].to_numpy()
                x_val = values.iloc[val_idx].to_numpy()
            for score, config in zip(scores, configs, strict=True):
                tree = DecisionTreeClassifier(
                    max_depth=config.leakage_max_depth,
                    min_samples_leaf=config.leakage_min_samples_leaf,
                    random_state=seed,
                )
                tree.fit(x_fit.reshape(-1, 1), target_c[fit_idx])
                proba = tree.predict_proba(x_val.reshape(-1, 1))
                positive = list(tree.classes_).index(1) if 1 in tree.classes_ else None
                score[val_idx] = proba[:, positive] if positive is not None else 0.0
        for out, score in zip(aucs, scores, strict=True):
            out.append(float(roc_auc_score(target_c, score)))
    return [float(np.mean(out)) for out in aucs]


_MISSING = "__missing__"


def _encode_by_rate(
    values: pd.Series, target_c: np.ndarray, fit_idx: np.ndarray, val_idx: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Kode kategori = proporsi kelas di lipatan latih (tanpa informasi lipatan validasi)."""
    fit_values = values.iloc[fit_idx].fillna(_MISSING).to_numpy()
    rates = pd.Series(target_c[fit_idx]).groupby(fit_values).mean()
    overall = float(target_c[fit_idx].mean())
    x_fit = pd.Series(fit_values).map(rates).to_numpy(dtype="float64")
    x_val = (
        values.iloc[val_idx]
        .fillna(_MISSING)
        .map(rates)
        .astype("float64")
        .fillna(overall)
        .to_numpy()
    )
    return x_fit, x_val
