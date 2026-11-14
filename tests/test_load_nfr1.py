"""Uji beban NFR-1 (marker `load`): scan 100.000 baris × 100 kolom, median ≤ 5 menit.

Memakai artefak `artifacts/metamodel-1.0.0` bila ada di mesin ini (artefak tidak di-commit).
Jalankan manual:

    uv run pytest -m load tests/test_load_nfr1.py -s

Data sintetis dibangkitkan dengan seed tetap (BR-84): 70 kolom numerik, 30 kolom kategorikal,
± 5% sel kosong, target biner. Hasil waktu dicatat di ADR 0020.
"""

from __future__ import annotations

import statistics
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ceteris.scan import scan_file
from ceteris.seeding import derive_seed

pytestmark = pytest.mark.load

ARTIFACT = Path(__file__).resolve().parents[1] / "artifacts" / "metamodel-1.0.0"
N_ROWS, N_NUMERIC, N_CATEGORICAL = 100_000, 70, 30
RUNS = 3
LIMIT_SECONDS = 300.0


def _frame() -> pd.DataFrame:
    rng = np.random.default_rng(derive_seed("nfr1", N_ROWS))
    y = rng.integers(0, 2, size=N_ROWS)
    columns: dict[str, object] = {}
    for i in range(N_NUMERIC):
        values = rng.normal(0, 1, size=N_ROWS) + (y * 0.3 if i < 10 else 0)
        values[rng.random(N_ROWS) < 0.05] = np.nan
        columns[f"num_{i}"] = values
    for i in range(N_CATEGORICAL):
        levels = rng.integers(0, 12, size=N_ROWS)
        columns[f"cat_{i}"] = pd.Series([f"v{v}" for v in levels], dtype="object")
    columns["target"] = pd.Series(np.where(y == 1, "ya", "tidak"), dtype="object")
    return pd.DataFrame(columns)


@pytest.mark.skipif(not ARTIFACT.exists(), reason="artefak metamodel-1.0.0 tidak ada di mesin ini")
def test_nfr1_scan_100k_rows_100_columns_median_under_5_minutes(tmp_path: Path) -> None:
    path = tmp_path / "nfr1.parquet"
    _frame().to_parquet(path, index=False)
    timings = []
    for i in range(RUNS):
        start = time.perf_counter()
        report = scan_file(path, "target", ARTIFACT, f"nfr1-{i}")
        timings.append(time.perf_counter() - start)
        assert report.estimate.ood_score >= 0
    median = statistics.median(timings)
    print(f"NFR-1 waktu scan (detik): {[round(t, 1) for t in timings]}, median {median:.1f}")
    assert median <= LIMIT_SECONDS
