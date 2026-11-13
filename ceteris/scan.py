"""ceteris.scan: orkestrasi scan, status hasil, `ScanReport` v1, dan CLI.

Fitur: F-S13, F-S14 (docs/product.md). Jalur: scan. Aturan: BR-05 (ambang T), BR-06 (kalimat
kondisi), BR-10 (format CSV atau Parquet), BR-30 sampai BR-35 (status), BR-60 (versi kontrak);
AC-3 (tidak mengimpor kode eksperimen), AC-4 (hanya membaca artefak), AC-12 (deterministik).

`findings` berisi temuan yang ada beserta potensi pemulihan ideal (F-S12, BR-40–BR-43): tidak
dijumlahkan, diurutkan menurut potensi (atau volume bila artefak menetapkan `finding_order` =
`volume`, fallback H2b). `estimate.delta_relative` berasal dari meta-model ΔAUC relatif terpisah
bila artefak memuatnya (K7, ADR 0011); artefak tanpa model itu memberi null.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from typing import Annotated, Final, Literal

import pandas as pd
import typer
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ceteris.artifact import Artifact, ArtifactError, load_artifact
from ceteris.dqprofile import (
    PROFILE_SEED,
    InputContractError,
    ProfileConfig,
    compute_profile,
    estimate_noise_floor,
    noise_floor_seeds,
    noise_floor_value,
    prepare_input,
)
from ceteris.recovery import displayed_potential, missing_row_frac, ranked_findings

SCHEMA_VERSION: Final = "1.0"
CONDITION: Final = "dibanding model yang dilatih pada versi bersih dan dievaluasi pada data bersih"
MIN_THRESHOLD = 0.01

StatusValue = Literal["material", "tidak_material", "tidak_yakin"]


# --- kontrak ScanReport v1 (architecture.md 6.1, BR-60) ---


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ModelInfo(_Strict):
    version: str
    experimental: bool
    profile_schema_version: str


class Estimate(_Strict):
    metric: Literal["auc"] = "auc"
    delta: float
    delta_relative: float | None
    interval_90: tuple[float, float]
    ood_score: float

    @model_validator(mode="after")
    def _ordered(self) -> Estimate:
        lo, hi = self.interval_90
        if lo > hi:
            raise ValueError("interval_90 harus [lo, hi] dengan lo <= hi")
        return self


class Status(_Strict):
    value: StatusValue
    threshold: float
    noise_floor_estimated: float
    reasons: list[str] = Field(min_length=1)


class Finding(_Strict):
    issue_type: str
    column: str | None
    rows_affected_pct: float
    observed_or_estimated: Literal["observed", "estimated"]
    recovery_potential: float | None


class ScanReport(_Strict):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    scan_id: str
    model: ModelInfo
    estimate: Estimate
    status: Status
    findings: list[Finding]
    input_warnings: list[str]
    condition: Literal[
        "dibanding model yang dilatih pada versi bersih dan dievaluasi pada data bersih"
    ] = CONDITION


# --- status (BR-05, BR-30 sampai BR-34) ---


def materiality_threshold(noise_floor: float) -> float:
    """BR-05: `T = max(0,01; noise floor)`."""
    return max(MIN_THRESHOLD, float(noise_floor))


def decide_status(
    lo: float, hi: float, threshold: float, *, ood_high: bool, leakage_flagged: bool
) -> tuple[StatusValue, list[str]]:
    """Tepat satu status per scan (BR-30), dengan alasannya.

    OOD dan kebocoran target memaksa `tidak_yakin` sebelum interval dibaca (BR-33, BR-15).
    `material` hanya bila `lo > T` (BR-31); `tidak_material` hanya bila `hi < T` (BR-32);
    interval yang menyentuh atau memotong `T` tidak pernah dibulatkan (BR-33, BR-34).
    """
    if lo > hi:
        raise ValueError("interval tidak sah: lo > hi")
    reasons = [r for r, on in (("ood_high", ood_high), ("target_leakage", leakage_flagged)) if on]
    if reasons:
        return "tidak_yakin", reasons
    if lo > threshold:
        return "material", ["interval_above_threshold"]
    if hi < threshold:
        return "tidak_material", ["interval_below_threshold"]
    return "tidak_yakin", ["interval_crosses_threshold"]


# --- orkestrasi scan (F-S13) ---


def scan(
    data: pd.DataFrame, target: str, artifact: Artifact, scan_id: str | None = None
) -> ScanReport:
    """Scan satu dataset kotor dengan artefak yang sudah dimuat.

    Pelanggaran kontrak input menghentikan scan dengan `InputContractError` tanpa estimasi
    parsial (BR-10, BR-11). Profil dihitung dengan seed tetap (BR-12, AC-12) dan dicocokkan
    dengan versi artefak (BR-23).
    """
    profile = compute_profile(data, target, learner=artifact.learner, seed=PROFILE_SEED)
    artifact.check_profile(profile.schema_version)
    meta = artifact.metadata
    delta = artifact.predict(profile.features)
    lo, hi = artifact.interval(delta)
    ood_score = artifact.ood_score(profile.features)
    aucs = estimate_noise_floor(
        data, target, learner=artifact.learner, seeds=noise_floor_seeds(meta.noise_floor_seeds)
    )
    noise_floor = noise_floor_value(aucs, meta.noise_floor_statistic)
    threshold = materiality_threshold(noise_floor)
    value, reasons = decide_status(
        lo,
        hi,
        threshold,
        ood_high=artifact.ood_high(ood_score),
        leakage_flagged=profile.leakage.flagged,
    )
    return ScanReport(
        scan_id=scan_id or f"scn_{uuid.uuid4().hex}",
        model=ModelInfo(
            version=meta.version,
            experimental=meta.experimental,
            profile_schema_version=meta.profile_schema_version,
        ),
        estimate=Estimate(
            delta=delta,
            delta_relative=artifact.predict_relative(profile.features),
            interval_90=(lo, hi),
            ood_score=ood_score,
        ),
        status=Status(
            value=value, threshold=threshold, noise_floor_estimated=noise_floor, reasons=reasons
        ),
        findings=findings_for(data, target, profile.features, artifact),
        input_warnings=list(profile.input_warnings),
        condition=CONDITION,
    )


def findings_for(
    data: pd.DataFrame, target: str, features: dict[str, float], artifact: Artifact
) -> list[Finding]:
    """Temuan dan potensi pemulihan ideal (F-S12); volume missing dari data pasca kontrak input."""
    prepared = prepare_input(data, target, ProfileConfig()).frame
    ranked = ranked_findings(features, missing_row_frac(prepared, target), artifact.predict)
    if artifact.metadata.finding_order == "volume":  # fallback H2b (ADR 0006 butir 1)
        ranked = sorted(ranked, key=lambda f: (-f.rows_affected_pct, f.issue_type))
    return [
        Finding(
            issue_type=f.issue_type,
            column=None,
            rows_affected_pct=f.rows_affected_pct,
            observed_or_estimated=f.observed_or_estimated,
            recovery_potential=displayed_potential(f.recovery_potential),
        )
        for f in ranked
    ]


def read_table(path: Path) -> pd.DataFrame:
    """BR-10: hanya CSV atau Parquet."""
    suffix = Path(path).suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    raise InputContractError([f"BR-10 format_unsupported: {suffix or 'tanpa ekstensi'}"])


def scan_file(
    path: Path, target: str, artifact_path: Path, scan_id: str | None = None
) -> ScanReport:
    """Python API: baca berkas, muat artefak, dan jalankan scan."""
    return scan(read_table(path), target, load_artifact(artifact_path), scan_id)


# --- CLI ---

app = typer.Typer(add_completion=False, help="Ceteris: estimasi dampak kekotoran data.")


@app.callback()
def _main() -> None:
    """Ceteris CLI."""


@app.command("scan")
def scan_command(
    path: Annotated[Path, typer.Argument(help="Data latih kotor (CSV atau Parquet).")],
    target: Annotated[str, typer.Option("--target", help="Nama kolom target.")],
    artifact: Annotated[Path, typer.Option("--artifact", help="Folder artefak model.")],
    out: Annotated[Path | None, typer.Option("--out", help="Tulis ScanReport ke berkas.")] = None,
) -> None:
    """Scan satu dataset dan tulis `ScanReport` (JSON)."""
    try:
        report = scan_file(path, target, artifact)
    except InputContractError as err:
        error = {"code": "input_contract", "message": str(err), "details": err.reasons}
        typer.echo(json.dumps({"error": error}, ensure_ascii=False), err=True)
        raise typer.Exit(code=2) from err
    except ArtifactError as err:
        error = {"code": "artifact", "message": str(err), "details": []}
        typer.echo(json.dumps({"error": error}, ensure_ascii=False), err=True)
        raise typer.Exit(code=3) from err
    payload = report.model_dump_json(indent=2)
    if out is None:
        sys.stdout.write(payload + "\n")
    else:
        Path(out).write_text(payload + "\n", encoding="utf-8")
