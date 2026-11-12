"""ceteris.artifact: format dan pemuat artefak meta-model.

Fitur: F-S08 (muat), F-S10 (docs/product.md). Jalur: scan (hanya membaca) dan riset (menulis
lewat `ceteris.metamodel`). Aturan: BR-21 (estimasi dari artefak berversi, tanpa latih ulang),
BR-23 dan AC-9 (versi profil harus cocok), BR-35 (label eksperimental), AC-4 (scan tidak menulis).

Pemuat dipisah dari kode pelatihan agar jalur scan tidak membawa kode riset (AC-3,
execution-plan Phase 3). Satu artefak adalah satu folder:

- `metadata.json`: `ArtifactMetadata`;
- `model.txt`: booster LightGBM meta-model;
- `calibration.parquet`: skor nonconformity dan dataset asalnya (kuantil dihitung ulang dan
  dicocokkan saat dimuat);
- `ood_reference.parquet`: profil referensi untuk skor OOD;
- `learner.yaml`: spesifikasi learner acuan yang dipakai probe saat scan.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

import lightgbm as lgb
import numpy as np
import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field

from ceteris.dqprofile import NoiseFloorStatistic
from ceteris.train import LearnerSpec
from ceteris.uncertainty import (
    OODReference,
    conformal_interval,
    fit_ood_reference,
    weighted_conformal_quantile,
)

ARTIFACT_FORMAT: Final = "1"


class ArtifactError(RuntimeError):
    """Artefak rusak, tidak lengkap, atau tidak cocok dengan profil (BR-23, AC-9)."""


class ArtifactMetadata(BaseModel):
    """Metadata wajib artefak model (architecture.md 6.2)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_version: Literal["1"] = ARTIFACT_FORMAT
    version: str
    experimental: bool
    profile_schema_version: str
    learner_spec_version: str
    learner_spec_sha256: str
    corpus_snapshot: str
    trained_at: str
    datasets: list[int] = Field(min_length=1)
    n_runs: int = Field(ge=1)
    features: list[str] = Field(min_length=1)
    coverage_target: float = 0.90
    conformal_quantile: float = Field(ge=0.0)
    coverage_summary: dict[str, float]
    ood_k: int = Field(ge=1)
    ood_threshold: float = Field(ge=0.0)
    ood_threshold_basis: str
    noise_floor_statistic: NoiseFloorStatistic
    noise_floor_seeds: int = Field(ge=2)


def learner_sha256(learner: LearnerSpec) -> str:
    payload = json.dumps(learner.model_dump(), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Artifact:
    """Artefak yang sudah dimuat: hanya membaca, tidak pernah melatih (AC-4)."""

    path: Path
    metadata: ArtifactMetadata
    booster: lgb.Booster
    ood: OODReference
    learner: LearnerSpec

    def check_profile(self, profile_schema_version: str) -> None:
        """BR-23, AC-9: versi skema profil harus sama dengan versi artefak."""
        expected = self.metadata.profile_schema_version
        if profile_schema_version != expected:
            raise ArtifactError(
                f"versi profil {profile_schema_version!r} tidak cocok dengan artefak "
                f"{self.metadata.version} (profil {expected!r})"
            )

    def _vector(self, features: Mapping[str, float]) -> np.ndarray:
        missing = [name for name in self.metadata.features if name not in features]
        if missing:
            raise ArtifactError(f"fitur profil tidak lengkap: {missing}")
        return np.array([[float(features[n]) for n in self.metadata.features]], dtype="float64")

    def predict(self, features: Mapping[str, float]) -> float:
        """Estimasi ΔAUC dari fitur profil."""
        return float(self.booster.predict(self._vector(features))[0])

    def interval(self, prediction: float) -> tuple[float, float]:
        return conformal_interval(prediction, self.metadata.conformal_quantile)

    def ood_score(self, features: Mapping[str, float]) -> float:
        return self.ood.score([float(features[n]) for n in self.ood.features])

    def ood_high(self, score: float) -> bool:
        return score > self.metadata.ood_threshold


def save_artifact(
    path: Path,
    metadata: ArtifactMetadata,
    booster: lgb.Booster,
    calibration: pd.DataFrame,
    ood_profiles: pd.DataFrame,
    learner: LearnerSpec,
) -> None:
    """Tulis satu folder artefak. Folder yang sudah ada tidak ditimpa (artefak berversi)."""
    folder = Path(path)
    if folder.exists():
        raise ArtifactError(f"artefak {folder} sudah ada; naikkan versi")
    if learner_sha256(learner) != metadata.learner_spec_sha256:
        raise ArtifactError("spesifikasi learner tidak sama dengan metadata")
    if list(calibration.columns) != ["dataset_id", "score"]:
        raise ArtifactError("kalibrasi harus berkolom dataset_id dan score")
    folder.mkdir(parents=True)
    (folder / "metadata.json").write_text(
        json.dumps(metadata.model_dump(), indent=2, sort_keys=True), encoding="utf-8"
    )
    booster.save_model(str(folder / "model.txt"))
    calibration.to_parquet(folder / "calibration.parquet", index=False)
    ood_profiles[metadata.features].to_parquet(folder / "ood_reference.parquet", index=False)
    (folder / "learner.yaml").write_text(
        yaml.safe_dump(learner.model_dump(), sort_keys=True), encoding="utf-8"
    )


def load_artifact(path: Path) -> Artifact:
    """Muat dan periksa artefak: kuantil, spesifikasi learner, dan fitur harus konsisten."""
    folder = Path(path)
    required = ["metadata.json", "model.txt", "calibration.parquet", "ood_reference.parquet"]
    missing = [name for name in [*required, "learner.yaml"] if not (folder / name).exists()]
    if missing:
        raise ArtifactError(f"artefak {folder} tidak lengkap: {missing}")
    metadata = ArtifactMetadata.model_validate_json(
        (folder / "metadata.json").read_text(encoding="utf-8")
    )
    learner = LearnerSpec.model_validate(
        yaml.safe_load((folder / "learner.yaml").read_text(encoding="utf-8"))
    )
    if learner_sha256(learner) != metadata.learner_spec_sha256:
        raise ArtifactError("learner.yaml artefak tidak sama dengan metadata")
    calibration = pd.read_parquet(folder / "calibration.parquet")
    quantile = weighted_conformal_quantile(
        calibration["score"].tolist(), calibration["dataset_id"].tolist(), metadata.coverage_target
    )
    if not math.isclose(quantile, metadata.conformal_quantile, rel_tol=0, abs_tol=1e-12):
        raise ArtifactError("kuantil conformal tidak cocok dengan skor kalibrasi")
    booster = lgb.Booster(model_file=str(folder / "model.txt"))
    if list(booster.feature_name()) != _lgb_names(metadata.features):
        raise ArtifactError("urutan fitur booster tidak sama dengan metadata")
    reference = pd.read_parquet(folder / "ood_reference.parquet")
    ood = fit_ood_reference(reference, metadata.features, metadata.ood_k)
    return Artifact(folder, metadata, booster, ood, learner)


def _lgb_names(features: Sequence[str]) -> list[str]:
    """Nama kolom seperti yang dicatat LightGBM (karakter khusus diganti garis bawah)."""
    return [name.replace(" ", "_") for name in features]
