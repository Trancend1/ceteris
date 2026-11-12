"""Fixture bersama: dataset sintetis, fetcher palsu, spesifikasi learner, provenance palsu."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ceteris.corpus import PreparedDataset, RawDataset
from ceteris.store import Provenance, RunStore
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


@dataclass(frozen=True)
class SmallPilot:
    """Run store kecil dua dataset sintetis dan artefak yang dilatih darinya."""

    store: RunStore
    runs: pd.DataFrame
    prepared: dict[int, PreparedDataset]
    learner: LearnerSpec
    artifact_dir: Path


@pytest.fixture(scope="session")
def small_pilot(tmp_path_factory: pytest.TempPathFactory) -> SmallPilot:
    """Dua dataset × lima konfigurasi × dua seed; dipakai uji meta-model, scan, dan BR-16."""
    from ceteris.corpus import CorpusFilter, prepare_dataset
    from ceteris.corrupt import DuplicateExact, LabelUniform, MissingMCAR, Outlier
    from ceteris.experiment import run_corruption
    from ceteris.metamodel import build_artifact

    root = tmp_path_factory.mktemp("pilot")
    fast = load_learner_spec(CONFIGS / "learner.yaml").model_copy(
        update={"num_boost_round": 20, "version": "test-fast"}
    )
    small = CorpusFilter(min_rows=100, max_rows=5000, min_class_count=5)
    frames = {42: make_frame(n=500, seed=0), 43: make_frame(n=500, n_classes=3, seed=1)}
    fetcher = FakeFetcher(frames)
    store = RunStore(root / "runs")
    prepared = {d: prepare_dataset(d, fetcher, root / "corpus", small) for d in frames}
    configs = [
        [LabelUniform(level=0.1)],
        [LabelUniform(level=0.3)],
        [MissingMCAR(level=0.2)],
        [DuplicateExact(level=0.2)],
        [Outlier(level=0.1)],
    ]
    for dataset in prepared.values():
        for specs in configs:
            for seed_index in range(2):
                run_corruption(dataset, specs, seed_index, fast, store, fake_provenance)
    runs = store.read("corruption_run").sort_values("run_id").reset_index(drop=True)
    artifact_dir = root / "artifact"
    build_artifact(
        runs,
        fast,
        artifact_dir,
        version="0.0.1-test",
        corpus_snapshot="test:2",
        noise_floor_statistic="range",
        noise_floor_seeds=3,
        ood_k=3,
    )
    return SmallPilot(store, runs, prepared, fast, artifact_dir)


@pytest.fixture
def learner() -> LearnerSpec:
    return load_learner_spec(CONFIGS / "learner.yaml")


@pytest.fixture
def fast_learner(learner: LearnerSpec) -> LearnerSpec:
    """Learner acuan dengan ronde lebih sedikit agar uji cepat; parameter lain sama."""
    return learner.model_copy(update={"num_boost_round": 20, "version": "test-fast"})
