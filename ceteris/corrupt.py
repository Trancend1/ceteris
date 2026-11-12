"""ceteris.corrupt: corruption engine deterministik untuk partisi latih.

Fitur: F-S02 (docs/product.md). Jalur: riset saja (tidak boleh diimpor jalur scan, AC-3).
Aturan: BR-80 (hanya partisi latih), BR-82 (`affected_row_frac`), BR-83 (urutan campuran),
BR-84 (seed turunan). Semantik level per jenis: ADR 0008, diperbarui ADR 0009 (K3a–K3e).

Semantik level:
- missing (MCAR, MAR): tepat round(level × n) sel per kolom sasaran, pada sel yang belum kosong.
  Kolom sasaran = `n_columns` kolom dengan importance tertinggi atau terendah menurut learner
  acuan pada D₀ (K3e). MAR memilih kolom pemicu dengan korelasi Spearman absolut tertinggi; sel
  dipilih dengan bobot menurut peringkat nilai pemicu (K3b).
- label uniform: tepat round(level × n) baris berganti ke kelas lain secara acak.
- label class-conditional (K3c): biner, laju positif → negatif dua kali laju sebaliknya dengan
  total tepat round(level × n) (kelas minoritas = positif); multikelas, round(level × n_c) baris
  per kelas c pindah ke kelas yang paling sering tertukar menurut confusion matrix out-of-fold
  learner acuan pada D₀.
- outlier (K3d): tepat round(level × n) baris, masing-masing satu kolom numerik diganti nilai di
  luar pagar Tukey [Q1 − k·IQR; Q3 + k·IQR] dengan k ∼ U[k_min; k_max] per sel.
- duplikat (eksak, konflik label): round(level × n) baris salinan ditambahkan.

`affected_row_frac` = proporsi baris latih kotor yang berbeda dari baris asalnya atau merupakan
baris tambahan, dihitung dari perbandingan nyata, bukan dari niat korupsi.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal

import numpy as np
import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from ceteris.dqprofile import quartiles_with_fallback
from ceteris.seeding import sub_seed

if TYPE_CHECKING:
    from ceteris.train import LearnerSpec


class CorruptionNotApplicable(ValueError):
    """Korupsi tidak bisa diterapkan pada dataset ini (misalnya tidak ada kolom numerik)."""


class _Spec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    level: float = Field(gt=0.0, lt=1.0)


ColumnChoice = Literal["high_importance", "low_importance"]


class MissingMCAR(_Spec):
    kind: Literal["missing_mcar"] = "missing_mcar"
    n_columns: int = Field(default=3, ge=1)
    columns: ColumnChoice = "high_importance"


class MissingMAR(_Spec):
    kind: Literal["missing_mar"] = "missing_mar"
    n_columns: int = Field(default=3, ge=1)
    columns: ColumnChoice = "high_importance"


class LabelUniform(_Spec):
    kind: Literal["label_uniform"] = "label_uniform"


class LabelClassConditional(_Spec):
    kind: Literal["label_class_conditional"] = "label_class_conditional"


class Outlier(_Spec):
    kind: Literal["outlier"] = "outlier"
    k_min: float = Field(default=3.0, gt=0.0)
    k_max: float = Field(default=10.0, gt=0.0)

    @model_validator(mode="after")
    def _range(self) -> Outlier:
        if self.k_max < self.k_min:
            raise ValueError("k_max harus >= k_min")
        return self


class DuplicateExact(_Spec):
    kind: Literal["duplicate_exact"] = "duplicate_exact"


class DuplicateConflict(_Spec):
    kind: Literal["duplicate_conflict"] = "duplicate_conflict"


AnySpec = (
    MissingMCAR
    | MissingMAR
    | LabelUniform
    | LabelClassConditional
    | Outlier
    | DuplicateExact
    | DuplicateConflict
)
CorruptionSpec = Annotated[AnySpec, Field(discriminator="kind")]
_SPEC_ADAPTER: TypeAdapter[AnySpec] = TypeAdapter(CorruptionSpec)

# BR-83: duplikat → label → outlier → missing.
APPLY_ORDER: dict[str, int] = {
    "duplicate_exact": 0,
    "duplicate_conflict": 0,
    "label_uniform": 1,
    "label_class_conditional": 1,
    "outlier": 2,
    "missing_mcar": 3,
    "missing_mar": 3,
}


@dataclass(frozen=True)
class CorruptionContext:
    """Informasi dari D₀ (jalur riset saja) untuk memilih kolom dan kelas sasaran (ADR 0009).

    Konteks dihitung dari partisi latih versi bersih, tidak pernah dari data kotor, dan tidak
    pernah masuk ke profil (BR-20): ia hanya mengarahkan ke mana korupsi disuntikkan.
    """

    importance_order: tuple[str, ...]
    confusion_target: dict[int, int]


@dataclass(frozen=True)
class StepRecord:
    """Ringkasan satu langkah korupsi."""

    kind: str
    level: float
    rows_touched: int
    rows_added: int
    columns: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CorruptionResult:
    """Partisi latih kotor beserta jejak korupsinya."""

    frame: pd.DataFrame
    origin: np.ndarray
    added: np.ndarray
    affected: np.ndarray
    steps: tuple[StepRecord, ...]

    @property
    def n_affected(self) -> int:
        return int(self.affected.sum())

    @property
    def affected_row_frac(self) -> float:
        """BR-82: proporsi baris latih kotor yang terdampak."""
        return float(self.affected.mean()) if len(self.affected) else 0.0


@dataclass(frozen=True)
class CorruptionGrid:
    """Isi `configs/corruption.yaml`: konfigurasi tunggal dan campuran."""

    version: str
    singles: tuple[AnySpec, ...]
    mixtures: tuple[tuple[AnySpec, ...], ...]


def parse_spec(payload: dict[str, Any]) -> AnySpec:
    """Validasi satu spesifikasi korupsi dari dict (misalnya hasil YAML)."""
    return _SPEC_ADAPTER.validate_python(payload)


def load_corruption_grid(path: Path) -> CorruptionGrid:
    """Grid dari `configs/corruption.yaml`: setiap jenis × level × varian, ditambah campuran."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    singles: list[AnySpec] = []
    for entry in raw["singles"]:
        variants = entry.get("variants") or [{}]
        for level in entry["levels"]:
            for variant in variants:
                singles.append(
                    parse_spec({"kind": entry["kind"], "level": float(level), **variant})
                )
    mixtures = tuple(tuple(parse_spec(item) for item in mix) for mix in raw.get("mixtures") or [])
    return CorruptionGrid(version=str(raw["version"]), singles=tuple(singles), mixtures=mixtures)


def build_context(
    train: pd.DataFrame, target: str, learner: LearnerSpec, seed: int
) -> CorruptionContext:
    """Konteks korupsi dari partisi latih D₀: urutan importance dan kelas yang paling tertukar."""
    from ceteris.train import feature_importance, oof_predict_proba

    importance = feature_importance(learner, train, target, sub_seed(seed, "importance"))
    values = importance.to_numpy()
    order = sorted(range(len(values)), key=lambda i: (-values[i], i))
    importance_order = tuple(str(importance.index[i]) for i in order)

    codes = train[target].cat.codes.to_numpy()
    n_classes = len(train[target].cat.categories)
    proba = oof_predict_proba(learner, train, target, sub_seed(seed, "confusion"))
    matrix = np.zeros((n_classes, n_classes), dtype=np.int64)
    np.add.at(matrix, (codes, proba.argmax(axis=1)), 1)
    confusion_target: dict[int, int] = {}
    for code in range(n_classes):
        row = matrix[code].astype("float64")
        row[code] = -1.0
        best = int(np.argmax(row))  # seri: kode terkecil
        confusion_target[code] = best if row[best] > 0 else (code + 1) % n_classes
    return CorruptionContext(importance_order=importance_order, confusion_target=confusion_target)


def corrupt(
    train: pd.DataFrame,
    target: str,
    specs: Sequence[AnySpec],
    seed: int,
    context: CorruptionContext | None = None,
) -> CorruptionResult:
    """Terapkan korupsi pada partisi latih dengan urutan tetap (BR-83).

    Masukan tidak diubah. Fungsi ini hanya menerima partisi latih; partisi uji tidak pernah
    melewati corruption engine (BR-80). Korupsi missing dan label class-conditional multikelas
    membutuhkan `context` dari `build_context`.
    """
    if target not in train.columns:
        raise ValueError(f"kolom target {target!r} tidak ada")
    if not specs:
        raise ValueError("minimal satu spesifikasi korupsi")
    if not isinstance(train[target].dtype, pd.CategoricalDtype):
        raise ValueError("target harus kategorikal (protokol D₀)")

    # Urutan kanonik: kelompok BR-83 lebih dulu, lalu isi spesifikasi. Seed tiap langkah diturunkan
    # dari isi spesifikasinya, bukan dari posisi, sehingga urutan masukan tidak berpengaruh (BR-84).
    keyed = sorted(
        ((APPLY_ORDER[s.kind], json.dumps(s.model_dump(), sort_keys=True), s) for s in specs),
        key=lambda item: (item[0], item[1]),
    )
    state = _State(train.copy(deep=True).reset_index(drop=True), target)
    steps: list[StepRecord] = []
    seen: dict[str, int] = {}
    for _, key, spec in keyed:
        occurrence = seen.get(key, 0)
        seen[key] = occurrence + 1
        rng = np.random.default_rng(sub_seed(seed, f"{key}#{occurrence}"))
        steps.append(_APPLY[spec.kind](state, spec, rng, context))

    clean = train.reset_index(drop=True)
    affected = _affected_rows(clean, state.frame, state.added)
    return CorruptionResult(
        frame=state.frame,
        origin=state.origin,
        added=state.added,
        affected=affected,
        steps=tuple(steps),
    )


class _State:
    def __init__(self, frame: pd.DataFrame, target: str) -> None:
        self.frame = frame
        self.target = target
        self.origin = np.arange(len(frame))
        self.added = np.zeros(len(frame), dtype=bool)

    @property
    def n(self) -> int:
        return len(self.frame)

    def features(self) -> list[str]:
        return [c for c in self.frame.columns if c != self.target]

    def numeric_features(self) -> list[str]:
        return [
            c
            for c in self.features()
            if pd.api.types.is_numeric_dtype(self.frame[c].dtype)
            and not pd.api.types.is_bool_dtype(self.frame[c].dtype)
            and not isinstance(self.frame[c].dtype, pd.CategoricalDtype)
        ]

    def n_classes(self) -> int:
        return len(self.frame[self.target].cat.categories)

    def codes(self) -> np.ndarray:
        return np.asarray(self.frame[self.target].cat.codes.to_numpy())

    def set_target_codes(self, rows: np.ndarray, codes: np.ndarray) -> None:
        current = self.frame[self.target]
        new_codes = current.cat.codes.to_numpy().copy()
        new_codes[rows] = codes
        self.frame[self.target] = pd.Categorical.from_codes(
            new_codes, categories=current.cat.categories
        )

    def append_rows(self, source_rows: np.ndarray, rows: pd.DataFrame) -> None:
        self.frame = pd.concat([self.frame, rows], ignore_index=True)
        self.origin = np.concatenate([self.origin, self.origin[source_rows]])
        self.added = np.concatenate([self.added, np.ones(len(source_rows), dtype=bool)])


def _count(level: float, n: int) -> int:
    return int(round(level * n))


def _require_context(context: CorruptionContext | None, what: str) -> CorruptionContext:
    if context is None:
        raise ValueError(f"{what} butuh CorruptionContext dari build_context (ADR 0009)")
    return context


def _apply_duplicate(
    state: _State, spec: AnySpec, rng: np.random.Generator, context: CorruptionContext | None
) -> StepRecord:
    conflict = isinstance(spec, DuplicateConflict)
    if conflict and state.n_classes() < 2:
        raise CorruptionNotApplicable("duplikat konflik label butuh minimal dua kelas")
    k = _count(spec.level, state.n)
    source = np.sort(rng.choice(state.n, size=k, replace=False))
    rows = state.frame.iloc[source].reset_index(drop=True)
    if conflict and k:
        n_classes = state.n_classes()
        codes = rows[state.target].cat.codes.to_numpy()
        shifted = (codes + rng.integers(1, n_classes, size=k)) % n_classes
        rows[state.target] = pd.Categorical.from_codes(
            shifted, categories=rows[state.target].cat.categories
        )
    state.append_rows(source, rows)
    return StepRecord(kind=spec.kind, level=spec.level, rows_touched=0, rows_added=k)


def _apply_label_uniform(
    state: _State, spec: AnySpec, rng: np.random.Generator, context: CorruptionContext | None
) -> StepRecord:
    n_classes = state.n_classes()
    if n_classes < 2:
        raise CorruptionNotApplicable("label noise butuh minimal dua kelas")
    k = _count(spec.level, state.n)
    rows = np.sort(rng.choice(state.n, size=k, replace=False))
    codes = state.codes()[rows]
    new = (codes + rng.integers(1, n_classes, size=k)) % n_classes
    state.set_target_codes(rows, new)
    return StepRecord(kind=spec.kind, level=spec.level, rows_touched=k, rows_added=0)


def _apply_label_class_conditional(
    state: _State, spec: AnySpec, rng: np.random.Generator, context: CorruptionContext | None
) -> StepRecord:
    n_classes = state.n_classes()
    if n_classes < 2:
        raise CorruptionNotApplicable("label noise butuh minimal dua kelas")
    codes = state.codes()
    categories = state.frame[state.target].cat.categories
    if n_classes == 2:
        return _flip_binary_asymmetric(state, spec, rng, codes, categories)
    ctx = _require_context(context, "label noise class-conditional multikelas")
    chosen: list[np.ndarray] = []
    targets: list[np.ndarray] = []
    per_class: dict[str, dict[str, Any]] = {}
    for code in range(n_classes):
        members = np.flatnonzero(codes == code)
        k = _count(spec.level, len(members))
        picked = np.sort(rng.choice(members, size=k, replace=False))
        destination = ctx.confusion_target[code]
        chosen.append(picked)
        targets.append(np.full(k, destination))
        per_class[str(categories[code])] = {"rows": k, "to": str(categories[destination])}
    rows = np.concatenate(chosen)
    state.set_target_codes(rows, np.concatenate(targets))
    return StepRecord(
        kind=spec.kind,
        level=spec.level,
        rows_touched=len(rows),
        rows_added=0,
        details={"per_class": per_class},
    )


def _flip_binary_asymmetric(
    state: _State,
    spec: AnySpec,
    rng: np.random.Generator,
    codes: np.ndarray,
    categories: pd.Index,
) -> StepRecord:
    """Biner (K3c): laju positif → negatif dua kali laju sebaliknya; kelas minoritas = positif."""
    counts = np.bincount(codes, minlength=2)
    positive = 1 if counts[0] == counts[1] else int(np.argmin(counts))
    negative = 1 - positive
    n_pos, n_neg = int(counts[positive]), int(counts[negative])
    k_total = _count(spec.level, state.n)
    rate_neg = spec.level * state.n / (2 * n_pos + n_neg)
    k_pos = min(n_pos, int(round(2 * rate_neg * n_pos)))
    k_neg = min(n_neg, k_total - k_pos)
    from_pos = np.sort(rng.choice(np.flatnonzero(codes == positive), size=k_pos, replace=False))
    from_neg = np.sort(rng.choice(np.flatnonzero(codes == negative), size=k_neg, replace=False))
    rows = np.concatenate([from_pos, from_neg])
    new = np.concatenate([np.full(k_pos, negative), np.full(k_neg, positive)])
    state.set_target_codes(rows, new)
    return StepRecord(
        kind=spec.kind,
        level=spec.level,
        rows_touched=len(rows),
        rows_added=0,
        details={
            "positive": str(categories[positive]),
            "positive_to_negative": k_pos,
            "negative_to_positive": k_neg,
        },
    )


def _apply_outlier(
    state: _State, spec: AnySpec, rng: np.random.Generator, context: CorruptionContext | None
) -> StepRecord:
    assert isinstance(spec, Outlier)
    numeric = state.numeric_features()
    if not numeric:
        raise CorruptionNotApplicable("outlier butuh minimal satu kolom fitur numerik")
    k = _count(spec.level, state.n)
    rows = np.sort(rng.choice(state.n, size=k, replace=False))
    column_index = rng.integers(0, len(numeric), size=k)
    signs = rng.choice(np.array([-1.0, 1.0]), size=k)
    multipliers = rng.uniform(spec.k_min, spec.k_max, size=k)
    touched: list[str] = []
    for j, name in enumerate(numeric):
        mask = column_index == j
        if not mask.any():
            continue
        touched.append(name)
        values = state.frame[name].astype("float64")
        q1, q3, spread = quartiles_with_fallback(values.dropna())
        replacement = np.where(
            signs[mask] > 0, q3 + multipliers[mask] * spread, q1 - multipliers[mask] * spread
        )
        integer = pd.api.types.is_integer_dtype(state.frame[name].dtype)
        replacement = _round_outward(replacement, signs[mask], integer)
        column = values.to_numpy().copy()
        original = column[rows[mask]]
        # Nilai pengganti yang kebetulan sama dengan nilai asal didorong lebih jauh ke luar,
        # supaya jumlah baris terdampak tetap tepat (BR-82).
        same = replacement == original
        step = max(spread, 1.0) if integer else spread
        pushed = _round_outward(replacement + signs[mask] * step, signs[mask], integer)
        column[rows[mask]] = np.where(same, pushed, replacement)
        state.frame[name] = _restore_dtype(column, state.frame[name].dtype)
    return StepRecord(
        kind=spec.kind,
        level=spec.level,
        rows_touched=k,
        rows_added=0,
        columns=tuple(touched),
        details={"k_min": spec.k_min, "k_max": spec.k_max},
    )


def _round_outward(values: np.ndarray, signs: np.ndarray, integer: bool) -> np.ndarray:
    """Kolom integer: batas atas dibulatkan ke atas, batas bawah ke bawah (tetap di luar pagar)."""
    if not integer:
        return values
    return np.asarray(np.where(signs > 0, np.ceil(values), np.floor(values)))


def _restore_dtype(values: np.ndarray, dtype: Any) -> pd.Series:
    if pd.api.types.is_integer_dtype(dtype) and not np.isnan(values).any():
        # Lewat Series agar tipe nullable pandas (misalnya Int64) juga didukung.
        return pd.Series(values).astype(dtype)
    return pd.Series(values, dtype="float64")


def _apply_missing(
    state: _State, spec: AnySpec, rng: np.random.Generator, context: CorruptionContext | None
) -> StepRecord:
    assert isinstance(spec, MissingMCAR | MissingMAR)
    ctx = _require_context(context, "korupsi missing")
    features = state.features()
    ranked = [c for c in ctx.importance_order if c in features]
    if not ranked:
        raise CorruptionNotApplicable("missing butuh minimal satu kolom fitur")
    n_cols = min(spec.n_columns, len(ranked))
    columns = ranked[:n_cols] if spec.columns == "high_importance" else ranked[-n_cols:]
    k = _count(spec.level, state.n)
    cells: dict[str, int] = {}
    drivers: dict[str, str] = {}
    for name in columns:
        candidates = np.flatnonzero(state.frame[name].notna().to_numpy())
        take = min(k, len(candidates))
        if isinstance(spec, MissingMAR) and take:
            driver = _mar_driver(state, name)
            weights = _driver_weights(state.frame[driver]).to_numpy()[candidates]
            rows = rng.choice(candidates, size=take, replace=False, p=weights / weights.sum())
            drivers[name] = driver
        else:
            rows = rng.choice(candidates, size=take, replace=False)
        _set_missing(state, name, np.sort(rows))
        cells[name] = take
    details: dict[str, Any] = {"cells_per_column": cells, "columns": spec.columns}
    if drivers:
        details["drivers"] = drivers
    return StepRecord(
        kind=spec.kind,
        level=spec.level,
        rows_touched=0,
        rows_added=0,
        columns=tuple(columns),
        details=details,
    )


def _as_float(column: pd.Series) -> pd.Series:
    if isinstance(column.dtype, pd.CategoricalDtype):
        return pd.Series(column.cat.codes.replace(-1, np.nan), dtype="float64")
    return pd.Series(column.to_numpy(dtype="float64", na_value=np.nan))


def _mar_driver(state: _State, column: str) -> str:
    """Kolom pemicu MAR (K3b): korelasi Spearman absolut tertinggi; seri ke urutan kolom."""
    numeric = [c for c in state.numeric_features() if c != column]
    candidates = numeric or [c for c in state.features() if c != column]
    if not candidates:
        raise CorruptionNotApplicable("MAR butuh minimal dua kolom fitur")
    reference = _as_float(state.frame[column])
    best, best_corr = candidates[0], -1.0
    for name in candidates:
        corr = reference.corr(_as_float(state.frame[name]), method="spearman")
        value = 0.0 if pd.isna(corr) else abs(float(corr))
        if value > best_corr:
            best, best_corr = name, value
    return best


def _driver_weights(driver: pd.Series) -> pd.Series:
    """Bobot MAR: makin tinggi nilai kolom pemicu, makin besar peluang hilang."""
    ranks = _as_float(driver).rank(method="average", na_option="keep")
    return ranks.fillna(1.0).astype("float64")


def _set_missing(state: _State, name: str, rows: np.ndarray) -> None:
    column = state.frame[name]
    if pd.api.types.is_integer_dtype(column.dtype) or pd.api.types.is_bool_dtype(column.dtype):
        column = column.astype("float64")
    column = column.copy()
    column.iloc[rows] = np.nan
    state.frame[name] = column


_APPLY = {
    "duplicate_exact": _apply_duplicate,
    "duplicate_conflict": _apply_duplicate,
    "label_uniform": _apply_label_uniform,
    "label_class_conditional": _apply_label_class_conditional,
    "outlier": _apply_outlier,
    "missing_mcar": _apply_missing,
    "missing_mar": _apply_missing,
}


def _affected_rows(clean: pd.DataFrame, dirty: pd.DataFrame, added: np.ndarray) -> np.ndarray:
    """Baris kotor yang berbeda dari baris asalnya, atau baris tambahan (BR-82)."""
    n_clean = len(clean)
    differs = np.zeros(n_clean, dtype=bool)
    head = dirty.iloc[:n_clean]
    for name in clean.columns:
        differs |= _column_differs(clean[name], head[name])
    return np.concatenate([differs, added[n_clean:]])


def _column_differs(before: pd.Series, after: pd.Series) -> np.ndarray:
    if isinstance(before.dtype, pd.CategoricalDtype) and isinstance(
        after.dtype, pd.CategoricalDtype
    ):
        return np.asarray(before.cat.codes.to_numpy() != after.cat.codes.to_numpy())
    missing_before = before.isna().to_numpy()
    missing_after = after.isna().to_numpy()
    both_missing = missing_before & missing_after
    comparable = ~(missing_before | missing_after)
    if pd.api.types.is_numeric_dtype(before.dtype) and pd.api.types.is_numeric_dtype(after.dtype):
        a = before.to_numpy(dtype="float64", na_value=np.nan)
        b = after.to_numpy(dtype="float64", na_value=np.nan)
        return np.asarray((a != b) & ~both_missing)
    # Perbandingan elemen hanya pada pasangan yang keduanya terisi; pd.NA tidak pernah dibandingkan.
    a_obj = before.to_numpy(dtype=object)
    b_obj = after.to_numpy(dtype=object)
    equal = np.zeros(len(before), dtype=bool)
    idx = np.flatnonzero(comparable)
    equal[idx] = [bool(a_obj[i] == b_obj[i]) for i in idx]
    return np.asarray(~(equal | both_missing))
