"""ceteris.store: run store offline (Parquet + DuckDB), run log, dan experiment registry.

Fitur: F-S07 (docs/product.md). Jalur: riset. Aturan: BR-84 (seed tercatat), NFR reprodusibilitas
R0 (commit, `uv.lock`, image digest di setiap baris `run_log`), AC-11 (store offline terpisah
dari store online; `corruption_run` tidak dipecah).

Setiap rekaman ditulis sebagai satu berkas Parquet per kunci di `<root>/<tabel>/`. DuckDB
membaca semuanya lewat view dengan `union_by_name`, sehingga kolom baru (misalnya profil di
Phase 2) bisa ditambahkan tanpa menulis ulang rekaman lama.
"""

from __future__ import annotations

import hashlib
import os
import platform
import subprocess
from dataclasses import asdict, dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
_EMPTY = "_empty.parquet"

CORPUS_DATASET = pa.schema(
    [
        ("dataset_id", pa.int64()),
        ("name", pa.string()),
        ("version", pa.int64()),
        ("licence", pa.string()),
        ("source_checksum", pa.string()),
        ("target", pa.string()),
        ("n_rows", pa.int64()),
        ("n_features", pa.int64()),
        ("n_classes", pa.int64()),
        ("missing_cell_frac", pa.float64()),
        ("passed", pa.bool_()),
        ("reasons", pa.string()),
        ("split_seed", pa.int64()),
        ("test_frac", pa.float64()),
        ("d0_sha256", pa.string()),
        ("train_sha256", pa.string()),
        ("test_sha256", pa.string()),
        ("prepared_at", pa.string()),
    ]
)

EXPERIMENT_CONFIG = pa.schema(
    [
        ("config_id", pa.string()),
        ("kind", pa.string()),
        ("spec_json", pa.string()),
        ("learner_spec_version", pa.string()),
        ("learner_spec_sha256", pa.string()),
        ("registered_at", pa.string()),
    ]
)

CORRUPTION_RUN = pa.schema(
    [
        ("run_id", pa.string()),
        ("dataset_id", pa.int64()),
        ("config_id", pa.string()),
        ("seed_index", pa.int64()),
        ("seed", pa.int64()),
        ("corruption_seed", pa.int64()),
        ("learner_seed", pa.int64()),
        ("spec_json", pa.string()),
        ("kinds", pa.string()),
        ("nominal_level", pa.float64()),
        ("affected_row_frac", pa.float64()),
        ("n_affected", pa.int64()),
        ("n_train_clean", pa.int64()),
        ("n_train_dirty", pa.int64()),
        ("steps_json", pa.string()),
        ("auc_clean", pa.float64()),
        ("auc_dirty", pa.float64()),
        ("delta_auc", pa.float64()),
        ("delta_auc_relative", pa.float64()),
        ("test_sha256", pa.string()),
        ("learner_spec_version", pa.string()),
        ("learner_spec_sha256", pa.string()),
        ("created_at", pa.string()),
    ]
)

RUN_LOG = pa.schema(
    [
        ("log_id", pa.string()),
        ("run_id", pa.string()),
        ("kind", pa.string()),
        ("dataset_id", pa.int64()),
        ("config_id", pa.string()),
        ("seed_index", pa.int64()),
        ("seed", pa.int64()),
        ("git_commit", pa.string()),
        ("git_dirty", pa.bool_()),
        ("uv_lock_sha256", pa.string()),
        ("image_digest", pa.string()),
        ("ceteris_version", pa.string()),
        ("python_version", pa.string()),
        ("lightgbm_version", pa.string()),
        ("started_at", pa.string()),
        ("finished_at", pa.string()),
        ("status", pa.string()),
        ("error", pa.string()),
    ]
)

TABLES: dict[str, pa.Schema] = {
    "corpus_dataset": CORPUS_DATASET,
    "experiment_config": EXPERIMENT_CONFIG,
    "corruption_run": CORRUPTION_RUN,
    "run_log": RUN_LOG,
}


class StoreError(RuntimeError):
    """Galat run store."""


class RecordExistsError(StoreError):
    """Rekaman dengan kunci yang sama sudah ada."""


class ProvenanceError(StoreError):
    """Asal-usul run (commit) tidak bisa ditentukan."""


@dataclass(frozen=True)
class Provenance:
    """Asal-usul lingkungan yang dicatat di setiap baris `run_log`."""

    git_commit: str
    git_dirty: bool
    uv_lock_sha256: str | None
    image_digest: str | None
    ceteris_version: str
    python_version: str
    lightgbm_version: str


def provenance(repo_root: Path = REPO_ROOT) -> Provenance:
    """Kumpulkan commit, hash `uv.lock`, image digest, dan versi pustaka.

    `CETERIS_GIT_COMMIT` (dan `CETERIS_GIT_DIRTY`) menggantikan pemanggilan git, misalnya di
    dalam image Docker tanpa folder `.git`. Tanpa keduanya, commit wajib terbaca dari git.
    """
    commit = os.environ.get("CETERIS_GIT_COMMIT")
    if commit:
        dirty = os.environ.get("CETERIS_GIT_DIRTY", "false").lower() == "true"
    else:
        commit, dirty = _git_state(repo_root)
    lock = repo_root / "uv.lock"
    return Provenance(
        git_commit=commit,
        git_dirty=dirty,
        uv_lock_sha256=hashlib.sha256(lock.read_bytes()).hexdigest() if lock.exists() else None,
        image_digest=os.environ.get("CETERIS_IMAGE_DIGEST") or None,
        ceteris_version=_version("ceteris"),
        python_version=platform.python_version(),
        lightgbm_version=_version("lightgbm"),
    )


def _git_state(repo_root: Path) -> tuple[str, bool]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ProvenanceError(
            "commit git tidak terbaca; set CETERIS_GIT_COMMIT bila berjalan di luar repository"
        ) from exc
    if not commit:
        raise ProvenanceError("commit git kosong")
    return commit, bool(status.strip())


def _version(package: str) -> str:
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return "unknown"


def provenance_fields(prov: Provenance) -> dict[str, Any]:
    """Kolom `run_log` yang berasal dari `Provenance`."""
    return asdict(prov)


class RunStore:
    """Run store offline di folder `root` (Parquet per rekaman, dibaca lewat DuckDB)."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        for table, schema in TABLES.items():
            folder = self.root / table
            folder.mkdir(parents=True, exist_ok=True)
            empty = folder / _EMPTY
            if not empty.exists():
                pq.write_table(schema.empty_table(), empty)

    def _path(self, table: str, key: str) -> Path:
        if not key or any(ch in key for ch in '/\\:*?"<>|') or key.startswith("_"):
            raise StoreError(f"kunci rekaman tidak sah: {key!r}")
        return self.root / table / f"{key}.parquet"

    def _write(self, table: str, key: str, row: dict[str, Any], overwrite: bool) -> None:
        schema = TABLES[table]
        expected = set(schema.names)
        missing, extra = expected - set(row), set(row) - expected
        if missing or extra:
            raise StoreError(
                f"{table}: kolom kurang {sorted(missing)}, kolom lebih {sorted(extra)}"
            )
        path = self._path(table, key)
        if path.exists() and not overwrite:
            raise RecordExistsError(f"{table}/{key} sudah ada")
        tmp = path.with_suffix(".tmp")
        pq.write_table(pa.Table.from_pylist([row], schema=schema), tmp)
        os.replace(tmp, path)

    def write_corpus_dataset(self, row: dict[str, Any]) -> None:
        """Tulis atau perbarui satu baris `corpus_dataset` (kunci: `dataset_id`)."""
        self._write("corpus_dataset", str(int(row["dataset_id"])), row, overwrite=True)

    def register_config(self, row: dict[str, Any]) -> None:
        """Daftarkan konfigurasi eksperimen; `config_id` yang sama wajib punya isi yang sama."""
        path = self._path("experiment_config", str(row["config_id"]))
        if path.exists():
            existing = pq.read_table(path).to_pylist()[0]
            if existing["spec_json"] != row["spec_json"]:
                raise StoreError(f"config_id {row['config_id']} sudah dipakai untuk isi berbeda")
            return
        self._write("experiment_config", str(row["config_id"]), row, overwrite=False)

    def has_run(self, run_id: str) -> bool:
        return self._path("corruption_run", run_id).exists()

    def write_corruption_run(self, row: dict[str, Any]) -> None:
        """Tulis satu baris `corruption_run`; run yang sama tidak ditulis dua kali."""
        self._write("corruption_run", str(row["run_id"]), row, overwrite=False)

    def write_run_log(self, row: dict[str, Any]) -> None:
        """Tulis satu baris `run_log` (satu per percobaan, termasuk yang gagal)."""
        if not row.get("git_commit") or row.get("seed") is None:
            raise StoreError("run_log wajib mencatat git_commit dan seed")
        self._write("run_log", str(row["log_id"]), row, overwrite=False)

    def connect(self) -> duckdb.DuckDBPyConnection:
        """Koneksi DuckDB di memori dengan satu view per tabel."""
        con = duckdb.connect(database=":memory:")
        for table in TABLES:
            pattern = (self.root / table).as_posix().replace("'", "''") + "/*.parquet"
            con.execute(
                f"CREATE VIEW {table} AS "
                f"SELECT * FROM read_parquet('{pattern}', union_by_name = true)"
            )
        return con

    def read(self, table: str) -> pd.DataFrame:
        """Seluruh isi satu tabel sebagai DataFrame."""
        if table not in TABLES:
            raise StoreError(f"tabel tidak dikenal: {table}")
        con = self.connect()
        try:
            frame: pd.DataFrame = con.execute(f"SELECT * FROM {table}").df()
        finally:
            con.close()
        return frame
