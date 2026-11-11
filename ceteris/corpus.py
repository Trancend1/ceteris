"""ceteris.corpus: loader korpus OpenML-CC18, protokol D₀, saringan, dan split tetap.

Fitur: F-S01 (docs/product.md). Jalur: riset saja (tidak boleh diimpor jalur scan, AC-3).
Aturan: BR-80 (split tetap; partisi uji tidak pernah diubah), BR-10 dan BR-11 (saringan
korpus disamakan dengan kontrak input scan, ADR 0008), BR-84 (seed split).

Protokol D₀ yang diterapkan, tidak lebih dari ini:
1. Baris dengan target kosong dibuang.
2. Kolom bertipe teks, objek, atau boolean diubah menjadi kategorikal.
3. Kolom numerik nullable pandas (Int64, Float64) diubah ke tipe numpy: integer tanpa nilai
   kosong menjadi int64, selain itu float64 dengan NaN. Hanya tipe yang berubah, bukan nilai.
4. Target diubah menjadi kategorikal dengan kategori terurut.
Tidak ada imputasi atau perbaikan lain (BR-70).
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from ceteris.seeding import split_seed

OPENML_API = "https://www.openml.org/api/v1/json"
CC18_SUITE_ID = 99
TRAIN = "train"
TEST = "test"
_META_FILE = "meta.json"
_D0_FILE = "d0.parquet"
_SPLIT_FILE = "split.parquet"


class CorpusError(RuntimeError):
    """Galat saat menyiapkan dataset korpus."""


class CorpusFilter(BaseModel):
    """Saringan korpus (glosarium "Korpus"; BR-10 dan BR-11 menurut ADR 0008)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_rows: int = Field(default=2000, ge=1)
    max_rows: int = Field(default=50000, ge=1)
    max_missing_cell_frac: float = Field(default=0.05, ge=0.0, le=1.0)
    max_features: int = Field(default=500, ge=1)
    min_classes: int = Field(default=2, ge=2)
    max_classes: int = Field(default=20, ge=2)
    min_class_count: int = Field(default=20, ge=1)


class SplitSpec(BaseModel):
    """Spesifikasi split latih/uji yang tetap per dataset."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    test_frac: float = Field(default=0.2, gt=0.0, lt=1.0)
    stratified: bool = True


class ExperimentConfig(BaseModel):
    """Isi `configs/experiment.yaml`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    suite_id: int = CC18_SUITE_ID
    filter: CorpusFilter = Field(default_factory=CorpusFilter)
    split: SplitSpec = Field(default_factory=SplitSpec)


def load_experiment_config(path: Path) -> ExperimentConfig:
    """Muat `configs/experiment.yaml`."""
    import yaml

    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return ExperimentConfig.model_validate(raw)


@dataclass(frozen=True)
class RawDataset:
    """Dataset seperti diterima dari sumber, sebelum protokol D₀."""

    dataset_id: int
    name: str
    version: int
    licence: str
    source_checksum: str
    target: str
    frame: pd.DataFrame


class Fetcher(Protocol):
    """Sumber dataset. Implementasi bawaan: `OpenMLFetcher`."""

    def fetch(self, dataset_id: int) -> RawDataset: ...


class OpenMLFetcher:
    """Mengunduh dataset OpenML lewat scikit-learn; cache lokal membuat unduhan ulang idempoten.

    Parser `liac-arff` dipakai untuk semua dataset. Parser `pandas` (pilihan "auto") gagal pada
    sebagian CC18 dengan pandas 3 (kategori integer), dan satu parser untuk seluruh korpus
    menjaga tipe kolom hasil parsing tetap seragam.
    """

    PARSER = "liac-arff"

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = Path(cache_dir)

    def fetch(self, dataset_id: int) -> RawDataset:
        from sklearn.datasets import fetch_openml

        bunch = fetch_openml(
            data_id=int(dataset_id),
            as_frame=True,
            data_home=str(self.cache_dir),
            parser=self.PARSER,
        )
        details: dict[str, Any] = dict(bunch.details)
        target = details.get("default_target_attribute")
        if not target or "," in str(target):
            raise CorpusError(f"dataset {dataset_id}: target bawaan tidak tunggal ({target!r})")
        return RawDataset(
            dataset_id=int(dataset_id),
            name=str(details.get("name", "")),
            version=int(details.get("version", 0)),
            licence=str(details.get("licence", "")),
            source_checksum=str(details.get("md5_checksum", "")),
            target=str(target),
            frame=bunch.frame.copy(),
        )


def list_suite_dataset_ids(
    suite_id: int = CC18_SUITE_ID,
    fetch_json: Callable[[str], dict[str, Any]] | None = None,
) -> list[int]:
    """Daftar `data_id` dalam suite OpenML (OpenML-CC18 = study 99)."""
    getter = fetch_json or _http_get_json
    payload = getter(f"{OPENML_API}/study/{int(suite_id)}")
    try:
        ids = payload["study"]["data"]["data_id"]
    except (KeyError, TypeError) as exc:
        raise CorpusError(f"respons study {suite_id} tidak berisi data_id") from exc
    return sorted(int(x) for x in ids)


def _http_get_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "ceteris-research-client"})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 (URL tetap)
        data: dict[str, Any] = json.loads(response.read().decode("utf-8"))
    return data


def to_base_dataset(raw: RawDataset) -> pd.DataFrame:
    """Terapkan protokol D₀ (lihat docstring modul) dan kembalikan frame berindeks 0..n-1."""
    if raw.target not in raw.frame.columns:
        raise CorpusError(f"dataset {raw.dataset_id}: kolom target {raw.target!r} tidak ada")
    frame = raw.frame.loc[raw.frame[raw.target].notna()].reset_index(drop=True)
    columns: dict[str, pd.Series] = {}
    for name in frame.columns:
        col = frame[name]
        if name == raw.target:
            labels = col.astype("str")
            columns[name] = pd.Categorical(labels, categories=sorted(pd.unique(labels)))
        elif _is_categorical_like(col):
            columns[name] = col.astype("category")
        elif pd.api.types.is_extension_array_dtype(col.dtype):
            columns[name] = _to_numpy_numeric(col)
        else:
            columns[name] = col
    return pd.DataFrame(columns)


def _to_numpy_numeric(col: pd.Series) -> pd.Series:
    """Tipe numerik nullable pandas (Int64, Float64) menjadi tipe numpy; nilai kosong tetap NaN."""
    if pd.api.types.is_integer_dtype(col.dtype) and not col.isna().any():
        return col.astype("int64")
    return pd.Series(col.to_numpy(dtype="float64", na_value=np.nan), name=col.name)


def _is_categorical_like(col: pd.Series) -> bool:
    dtype = col.dtype
    return bool(
        isinstance(dtype, pd.CategoricalDtype)
        or pd.api.types.is_object_dtype(dtype)
        or pd.api.types.is_string_dtype(dtype)
        or pd.api.types.is_bool_dtype(dtype)
    )


def feature_columns(frame: pd.DataFrame, target: str) -> list[str]:
    """Nama kolom fitur (semua kolom kecuali target), urutan dipertahankan."""
    return [c for c in frame.columns if c != target]


def missing_cell_frac(frame: pd.DataFrame, target: str) -> float:
    """Proporsi sel fitur yang kosong (ADR 0008: missing diukur per sel)."""
    features = frame[feature_columns(frame, target)]
    if features.size == 0:
        return 0.0
    return float(features.isna().to_numpy().sum() / features.size)


def evaluate_filter(frame: pd.DataFrame, target: str, spec: CorpusFilter) -> list[str]:
    """Alasan dataset tidak lolos saringan; daftar kosong berarti lolos."""
    reasons: list[str] = []
    n_rows = len(frame)
    n_features = len(feature_columns(frame, target))
    counts = frame[target].value_counts()
    counts = counts[counts > 0]
    if n_rows < spec.min_rows:
        reasons.append(f"rows {n_rows} < {spec.min_rows}")
    if n_rows > spec.max_rows:
        reasons.append(f"rows {n_rows} > {spec.max_rows}")
    miss = missing_cell_frac(frame, target)
    if miss > spec.max_missing_cell_frac:
        reasons.append(f"missing_cell_frac {miss:.4f} > {spec.max_missing_cell_frac}")
    if n_features > spec.max_features:
        reasons.append(f"features {n_features} > {spec.max_features} (BR-10)")
    if not spec.min_classes <= len(counts) <= spec.max_classes:
        reasons.append(
            f"classes {len(counts)} di luar {spec.min_classes}-{spec.max_classes} (BR-11)"
        )
    if len(counts) and int(counts.min()) < spec.min_class_count:
        reasons.append(f"min_class_count {int(counts.min())} < {spec.min_class_count} (BR-11)")
    return reasons


def frame_sha256(frame: pd.DataFrame) -> str:
    """Hash isi frame yang deterministik (nilai, nama kolom, dan urutan baris)."""
    hasher = hashlib.sha256()
    hasher.update(json.dumps([str(c) for c in frame.columns]).encode("utf-8"))
    hashed = pd.util.hash_pandas_object(frame, index=False).to_numpy()
    hasher.update(np.ascontiguousarray(hashed).tobytes())
    return hasher.hexdigest()


def make_split(frame: pd.DataFrame, target: str, spec: SplitSpec, seed: int) -> np.ndarray:
    """Label partisi (`train`/`test`) per baris; deterministik untuk seed yang sama."""
    from sklearn.model_selection import train_test_split

    index = np.arange(len(frame))
    stratify = frame[target].to_numpy() if spec.stratified else None
    _, test_idx = train_test_split(
        index, test_size=spec.test_frac, random_state=seed, stratify=stratify
    )
    labels = np.full(len(frame), TRAIN, dtype=object)
    labels[np.asarray(test_idx)] = TEST
    return labels


@dataclass(frozen=True)
class PreparedDataset:
    """Dataset korpus yang sudah melalui protokol D₀ dan split tetap."""

    dataset_id: int
    meta: dict[str, Any]
    frame: pd.DataFrame | None = field(repr=False, default=None)
    partition: np.ndarray | None = field(repr=False, default=None)

    @property
    def passed(self) -> bool:
        return bool(self.meta["passed"])

    @property
    def target(self) -> str:
        return str(self.meta["target"])

    def _require_data(self) -> tuple[pd.DataFrame, np.ndarray]:
        if self.frame is None or self.partition is None:
            raise CorpusError(
                f"dataset {self.dataset_id} tidak lolos saringan; data tidak disimpan"
            )
        return self.frame, self.partition

    def train_frame(self) -> pd.DataFrame:
        frame, partition = self._require_data()
        return frame.loc[partition == TRAIN].reset_index(drop=True)

    def test_frame(self) -> pd.DataFrame:
        frame, partition = self._require_data()
        return frame.loc[partition == TEST].reset_index(drop=True)


def prepare_dataset(
    dataset_id: int,
    fetcher: Fetcher,
    root: Path,
    corpus_filter: CorpusFilter | None = None,
    split: SplitSpec | None = None,
) -> PreparedDataset:
    """Unduh (bila belum ada), terapkan protokol D₀, saring, dan buat split tetap.

    Idempoten: bila dataset sudah disiapkan di `root`, sumber tidak dihubungi lagi dan
    hash isi diperiksa ulang. Isi yang berubah menghasilkan `CorpusError`, bukan data baru.
    """
    spec = corpus_filter or CorpusFilter()
    split_spec = split or SplitSpec()
    folder = Path(root) / str(int(dataset_id))
    meta_path = folder / _META_FILE
    if meta_path.exists():
        return _load_prepared(int(dataset_id), folder, spec, split_spec)

    raw = fetcher.fetch(int(dataset_id))
    base = to_base_dataset(raw)
    reasons = evaluate_filter(base, raw.target, spec)
    meta: dict[str, Any] = {
        "dataset_id": int(dataset_id),
        "name": raw.name,
        "version": raw.version,
        "licence": raw.licence,
        "source_checksum": raw.source_checksum,
        "target": raw.target,
        "n_rows": len(base),
        "n_features": len(feature_columns(base, raw.target)),
        "n_classes": int((base[raw.target].value_counts() > 0).sum()),
        "missing_cell_frac": missing_cell_frac(base, raw.target),
        "passed": not reasons,
        "reasons": reasons,
        "filter": spec.model_dump(),
        "split": split_spec.model_dump(),
        "split_seed": None,
        "d0_sha256": None,
        "train_sha256": None,
        "test_sha256": None,
        "prepared_at": datetime.now(UTC).isoformat(),
    }
    folder.mkdir(parents=True, exist_ok=True)
    if reasons:
        _write_json(meta_path, meta)
        return PreparedDataset(int(dataset_id), meta)

    seed = split_seed(int(dataset_id))
    partition = make_split(base, raw.target, split_spec, seed)
    # Scan hanya melihat partisi latih (BR-17), jadi BR-11 juga harus terpenuhi di sana.
    train_counts = base.loc[partition == TRAIN, raw.target].value_counts()
    train_min = int(train_counts[train_counts.index.isin(base[raw.target].unique())].min())
    if train_min < spec.min_class_count:
        meta.update(
            passed=False,
            reasons=[f"train min_class_count {train_min} < {spec.min_class_count} (BR-11, BR-17)"],
        )
        _write_json(meta_path, meta)
        return PreparedDataset(int(dataset_id), meta)
    base.to_parquet(folder / _D0_FILE, index=False)
    pd.DataFrame({"partition": partition.astype(str)}).to_parquet(folder / _SPLIT_FILE, index=False)
    # Hash dihitung dari salinan yang dibaca ulang dari disk, sehingga muatan berikutnya
    # menghasilkan hash yang sama persis.
    stored = pd.read_parquet(folder / _D0_FILE)
    stored_partition = pd.read_parquet(folder / _SPLIT_FILE)["partition"].to_numpy(dtype=object)
    prepared = PreparedDataset(int(dataset_id), meta, stored, stored_partition)
    meta.update(
        split_seed=seed,
        d0_sha256=frame_sha256(stored),
        train_sha256=frame_sha256(prepared.train_frame()),
        test_sha256=frame_sha256(prepared.test_frame()),
    )
    _write_json(meta_path, meta)
    return prepared


def _load_prepared(
    dataset_id: int, folder: Path, spec: CorpusFilter, split_spec: SplitSpec
) -> PreparedDataset:
    meta: dict[str, Any] = json.loads((folder / _META_FILE).read_text(encoding="utf-8"))
    if meta.get("filter") != spec.model_dump() or meta.get("split") != split_spec.model_dump():
        raise CorpusError(
            f"dataset {dataset_id} disiapkan dengan saringan atau split berbeda; "
            "pakai folder korpus baru"
        )
    if not meta["passed"]:
        return PreparedDataset(dataset_id, meta)
    frame = pd.read_parquet(folder / _D0_FILE)
    partition = pd.read_parquet(folder / _SPLIT_FILE)["partition"].to_numpy(dtype=object)
    prepared = PreparedDataset(dataset_id, meta, frame, partition)
    checks = {
        "d0_sha256": frame_sha256(frame),
        "test_sha256": frame_sha256(prepared.test_frame()),
    }
    for key, actual in checks.items():
        if actual != meta[key]:
            raise CorpusError(f"dataset {dataset_id}: {key} berubah sejak disiapkan")
    return prepared


def prepare_corpus(
    dataset_ids: Sequence[int],
    fetcher: Fetcher,
    root: Path,
    corpus_filter: CorpusFilter | None = None,
    split: SplitSpec | None = None,
) -> list[PreparedDataset]:
    """Siapkan banyak dataset berurutan; kembalikan semuanya, lolos atau tidak."""
    return [prepare_dataset(i, fetcher, root, corpus_filter, split) for i in dataset_ids]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
