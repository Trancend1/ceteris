"""Fixture bersama: dataset sintetis, fetcher palsu, spesifikasi learner, provenance palsu."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ceteris.corpus import RawDataset
from ceteris.store import Provenance
from ceteris.train import LearnerSpec, load_learner_spec

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIGS = REPO_ROOT / "configs"


def make_frame(
    n: int = 600,
    n_classes: int = 2,
    seed: int = 0,
    missing_frac: float = 0.0,
    target: str = "class",
) -> pd.DataFrame:
    """Frame sintetis mentah: float informatif, float derau, integer, kategorikal string."""
    rng = np.random.default_rng(seed)
    labels = rng.integers(0, n_classes, size=n)
    x0 = labels * 1.5 + rng.normal(0, 1, size=n)
    x1 = rng.normal(0, 1, size=n)
    if missing_frac:
        x1[rng.random(n) < missing_frac] = np.nan
    x2 = rng.integers(0, 50, size=n) + labels * 5
    c0 = np.where(rng.random(n) < 0.7, labels, rng.integers(0, n_classes, size=n))
    return pd.DataFrame(
        {
            "x0": x0,
            "x1": x1,
            "x2": x2.astype("int64"),
            "c0": pd.Series([f"lvl{v}" for v in c0], dtype="object"),
            target: pd.Series([f"k{v}" for v in labels], dtype="object"),
        }
    )


class FakeFetcher:
    """Fetcher tanpa jaringan yang menghitung berapa kali sumber dihubungi."""

    def __init__(self, frames: dict[int, pd.DataFrame], target: str = "class") -> None:
        self.frames = frames
        self.target = target
        self.calls: list[int] = []

    def fetch(self, dataset_id: int) -> RawDataset:
        self.calls.append(dataset_id)
        return RawDataset(
            dataset_id=dataset_id,
            name=f"synthetic-{dataset_id}",
            version=1,
            licence="Public",
            source_checksum=f"md5-{dataset_id}",
            target=self.target,
            frame=self.frames[dataset_id].copy(),
        )


def fake_provenance() -> Provenance:
    return Provenance(
        git_commit="0123456789abcdef0123456789abcdef01234567",
        git_dirty=False,
        uv_lock_sha256="f" * 64,
        image_digest=None,
        ceteris_version="0.0.0",
        python_version="3.11",
        lightgbm_version="test",
    )


@pytest.fixture
def learner() -> LearnerSpec:
    return load_learner_spec(CONFIGS / "learner.yaml")


@pytest.fixture
def fast_learner(learner: LearnerSpec) -> LearnerSpec:
    """Learner acuan dengan ronde lebih sedikit agar uji cepat; parameter lain sama."""
    return learner.model_copy(update={"num_boost_round": 20, "version": "test-fast"})
