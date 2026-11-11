"""ceteris.corrupt: corruption engine deterministik untuk partisi latih.

Fitur: F-S02 (docs/product.md). Jalur: riset saja (tidak boleh diimpor jalur scan, AC-3).
Aturan: BR-80 (hanya partisi latih), BR-82 (`affected_row_frac`), BR-83 (urutan campuran),
BR-84 (seed turunan). Semantik level per jenis dicatat di ADR 0008.

Semantik level:
- missing (MCAR, MAR): tepat round(level × n) sel per kolom terpilih, pada sel yang belum kosong.
- label (uniform, class-conditional): tepat round(level × n) baris berganti label
  (class-conditional: round(level × n_c) per kelas c, berpindah ke kelas berikutnya).
- outlier: tepat round(level × n) baris, masing-masing satu kolom numerik diganti nilai di luar
  rentang yang teramati.
- duplikat (eksak, konflik label): round(level × n) baris salinan ditambahkan.

`affected_row_frac` = proporsi baris latih kotor yang berbeda dari baris asalnya atau merupakan
baris tambahan, dihitung dari perbandingan nyata, bukan dari niat korupsi.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Literal

import numpy as np
import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from ceteris.seeding import sub_seed


class CorruptionNotApplicable(ValueError):
    """Korupsi tidak bisa diterapkan pada dataset ini (misalnya tidak ada kolom numerik)."""


class _Spec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    level: float = Field(gt=0.0, lt=1.0)


class MissingMCAR(_Spec):
    kind: Literal["missing_mcar"] = "missing_mcar"
    n_columns: int = Field(default=3, ge=1)


class MissingMAR(_Spec):
    kind: Literal["missing_mar"] = "missing_mar"
    n_columns: int = Field(default=3, ge=1)


class LabelUniform(_Spec):
    kind: Literal["label_uniform"] = "label_uniform"


class LabelClassConditional(_Spec):
    kind: Literal["label_class_conditional"] = "label_class_conditional"


class Outlier(_Spec):
    kind: Literal["outlier"] = "outlier"
    scale: float = Field(default=3.0, gt=0.0)


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


def parse_spec(payload: dict[str, Any]) -> AnySpec:
    """Validasi satu spesifikasi korupsi dari dict (misalnya hasil YAML)."""
    return _SPEC_ADAPTER.validate_python(payload)


def load_corruption_grid(path: Path) -> list[AnySpec]:
    """Grid korupsi dari `configs/corruption.yaml`: setiap jenis × setiap level."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    levels = [float(x) for x in raw["levels"]]
    specs: list[AnySpec] = []
    for kind, params in raw["kinds"].items():
        for level in levels:
            specs.append(parse_spec({"kind": kind, "level": level, **(params or {})}))
    return specs


def corrupt(
    train: pd.DataFrame,
    target: str,
    specs: Sequence[AnySpec],
    seed: int,
) -> CorruptionResult:
    """Terapkan korupsi pada partisi latih dengan urutan tetap (BR-83).

    Masukan tidak diubah. Fungsi ini hanya menerima partisi latih; partisi uji tidak pernah
    melewati corruption engine (BR-80).
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
        steps.append(_APPLY[spec.kind](state, spec, rng))

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


def _apply_duplicate(state: _State, spec: AnySpec, rng: np.random.Generator) -> StepRecord:
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


def _apply_label_uniform(state: _State, spec: AnySpec, rng: np.random.Generator) -> StepRecord:
    n_classes = state.n_classes()
    if n_classes < 2:
        raise CorruptionNotApplicable("label noise butuh minimal dua kelas")
    k = _count(spec.level, state.n)
    rows = np.sort(rng.choice(state.n, size=k, replace=False))
    codes = state.frame[state.target].cat.codes.to_numpy()[rows]
    new = (codes + rng.integers(1, n_classes, size=k)) % n_classes
    state.set_target_codes(rows, new)
    return StepRecord(kind=spec.kind, level=spec.level, rows_touched=k, rows_added=0)


def _apply_label_class_conditional(
    state: _State, spec: AnySpec, rng: np.random.Generator
) -> StepRecord:
    n_classes = state.n_classes()
    if n_classes < 2:
        raise CorruptionNotApplicable("label noise butuh minimal dua kelas")
    codes = state.frame[state.target].cat.codes.to_numpy()
    chosen: list[np.ndarray] = []
    targets: list[np.ndarray] = []
    per_class: dict[str, int] = {}
    for code in range(n_classes):
        members = np.flatnonzero(codes == code)
        k = _count(spec.level, len(members))
        picked = np.sort(rng.choice(members, size=k, replace=False))
        chosen.append(picked)
        targets.append(np.full(k, (code + 1) % n_classes))
        per_class[str(state.frame[state.target].cat.categories[code])] = k
    rows = np.concatenate(chosen)
    state.set_target_codes(rows, np.concatenate(targets))
    return StepRecord(
        kind=spec.kind,
        level=spec.level,
        rows_touched=len(rows),
        rows_added=0,
        details={"per_class": per_class},
    )


def _apply_outlier(state: _State, spec: AnySpec, rng: np.random.Generator) -> StepRecord:
    assert isinstance(spec, Outlier)
    numeric = state.numeric_features()
    if not numeric:
        raise CorruptionNotApplicable("outlier butuh minimal satu kolom fitur numerik")
    k = _count(spec.level, state.n)
    rows = np.sort(rng.choice(state.n, size=k, replace=False))
    column_index = rng.integers(0, len(numeric), size=k)
    signs = rng.choice(np.array([-1.0, 1.0]), size=k)
    touched: list[str] = []
    for j, name in enumerate(numeric):
        mask = column_index == j
        if not mask.any():
            continue
        touched.append(name)
        values = state.frame[name].astype("float64")
        observed = values.dropna()
        low, high = (float(observed.min()), float(observed.max())) if len(observed) else (0.0, 0.0)
        spread = _spread(observed)
        replacement = np.where(
            signs[mask] > 0, high + spec.scale * spread, low - spec.scale * spread
        )
        if pd.api.types.is_integer_dtype(state.frame[name].dtype):
            # Batas atas dibulatkan ke atas, batas bawah ke bawah: tetap di luar rentang teramati.
            replacement = np.where(signs[mask] > 0, np.ceil(replacement), np.floor(replacement))
        column = values.to_numpy().copy()
        column[rows[mask]] = replacement
        state.frame[name] = _restore_dtype(column, state.frame[name].dtype)
    return StepRecord(
        kind=spec.kind,
        level=spec.level,
        rows_touched=k,
        rows_added=0,
        columns=tuple(touched),
        details={"scale": spec.scale},
    )


def _spread(observed: pd.Series) -> float:
    if len(observed) == 0:
        return 1.0
    q25, q75 = observed.quantile([0.25, 0.75]).to_numpy()
    iqr = float(q75 - q25)
    if iqr > 0:
        return iqr
    std = float(observed.std(ddof=0))
    return std if std > 0 else 1.0


def _restore_dtype(values: np.ndarray, dtype: Any) -> pd.Series:
    if pd.api.types.is_integer_dtype(dtype) and not np.isnan(values).any():
        # Lewat Series agar tipe nullable pandas (misalnya Int64) juga didukung.
        return pd.Series(values).astype(dtype)
    return pd.Series(values, dtype="float64")


def _apply_missing(state: _State, spec: AnySpec, rng: np.random.Generator) -> StepRecord:
    assert isinstance(spec, MissingMCAR | MissingMAR)
    features = state.features()
    if not features:
        raise CorruptionNotApplicable("missing butuh minimal satu kolom fitur")
    n_cols = min(spec.n_columns, len(features))
    columns = [str(c) for c in rng.choice(np.array(features, dtype=object), n_cols, replace=False)]
    k = _count(spec.level, state.n)
    cells: dict[str, int] = {}
    drivers: dict[str, str] = {}
    for name in columns:
        candidates = np.flatnonzero(state.frame[name].notna().to_numpy())
        take = min(k, len(candidates))
        if isinstance(spec, MissingMAR) and len(features) > 1 and take:
            others = [c for c in features if c != name]
            driver = str(others[int(rng.integers(0, len(others)))])
            weights = _driver_weights(state.frame[driver]).to_numpy()[candidates]
            rows = rng.choice(candidates, size=take, replace=False, p=weights / weights.sum())
            drivers[name] = driver
        else:
            rows = rng.choice(candidates, size=take, replace=False)
        _set_missing(state, name, np.sort(rows))
        cells[name] = take
    details: dict[str, Any] = {"cells_per_column": cells}
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


def _driver_weights(driver: pd.Series) -> pd.Series:
    """Bobot MAR: makin tinggi nilai kolom pendorong, makin besar peluang hilang."""
    if isinstance(driver.dtype, pd.CategoricalDtype):
        driver = pd.Series(driver.cat.codes.replace(-1, np.nan), dtype="float64")
    ranks = driver.rank(method="average", na_option="keep")
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
