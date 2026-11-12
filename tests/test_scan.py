"""Uji status hasil, kontrak ScanReport, scan end-to-end, dan konsistensi jalur.

Fitur: F-S13, F-S14. Aturan: BR-05, BR-06, BR-10, BR-16, BR-30 sampai BR-35, BR-60; AC-12.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError
from typer.testing import CliRunner

from ceteris.artifact import load_artifact
from ceteris.corrupt import parse_spec
from ceteris.dqprofile import FEATURES, PROFILE_SEED, InputContractError, compute_profile
from ceteris.experiment import dirty_train
from ceteris.scan import (
    CONDITION,
    SCHEMA_VERSION,
    ScanReport,
    app,
    decide_status,
    materiality_threshold,
    read_table,
    scan,
)
from ceteris.seeding import run_seed
from tests.conftest import SmallPilot

CONTRACTS = Path(__file__).resolve().parent / "contracts"

# Contoh 2 business-rules.md: (estimasi, lo, hi, noise floor, OOD tinggi) → (T, status).
EXAMPLE_2 = {
    "A": ((0.012, 0.050), 0.004, False, 0.010, "material"),
    "B": ((0.006, 0.056), 0.004, False, 0.010, "tidak_yakin"),
    "C": ((0.012, 0.050), 0.015, False, 0.015, "tidak_yakin"),
    "D": ((0.000, 0.008), 0.004, False, 0.010, "tidak_material"),
    "E": ((0.012, 0.050), 0.004, True, 0.010, "tidak_yakin"),
}


@pytest.mark.parametrize("case", sorted(EXAMPLE_2))
def test_br31_br33_example_2_status_table(case: str) -> None:
    (lo, hi), noise_floor, ood_high, expected_t, expected = EXAMPLE_2[case]
    threshold = materiality_threshold(noise_floor)
    assert threshold == expected_t  # BR-05
    value, reasons = decide_status(lo, hi, threshold, ood_high=ood_high, leakage_flagged=False)
    assert value == expected
    if case == "E":
        assert reasons == ["ood_high"]  # OOD mengalahkan BR-31


def test_example_5_status_with_default_and_policy_threshold() -> None:
    """Contoh 5: [0,012; 0,050] material pada T = 0,010; tidak yakin pada T_gate = 0,020."""
    assert decide_status(0.012, 0.050, 0.010, ood_high=False, leakage_flagged=False)[0] == (
        "material"
    )
    t_gate = max(materiality_threshold(0.004), 0.020)
    assert decide_status(0.012, 0.050, t_gate, ood_high=False, leakage_flagged=False)[0] == (
        "tidak_yakin"
    )


def test_br15_leakage_forces_uncertain() -> None:
    value, reasons = decide_status(0.03, 0.05, 0.01, ood_high=False, leakage_flagged=True)
    assert (value, reasons) == ("tidak_yakin", ["target_leakage"])


def test_br33_interval_touching_threshold_is_uncertain() -> None:
    assert decide_status(0.010, 0.05, 0.010, ood_high=False, leakage_flagged=False)[0] == (
        "tidak_yakin"
    )
    assert decide_status(-0.02, 0.010, 0.010, ood_high=False, leakage_flagged=False)[0] == (
        "tidak_yakin"
    )


@given(
    st.floats(-0.2, 0.2, allow_nan=False),
    st.floats(0, 0.2, allow_nan=False),
    st.floats(0, 0.05, allow_nan=False),
    st.booleans(),
    st.booleans(),
)
def test_br30_br34_exactly_one_status_never_rounded(
    lo: float, width: float, noise_floor: float, ood: bool, leak: bool
) -> None:
    hi = lo + width
    threshold = materiality_threshold(noise_floor)
    value, reasons = decide_status(lo, hi, threshold, ood_high=ood, leakage_flagged=leak)
    assert value in {"material", "tidak_material", "tidak_yakin"}
    assert reasons
    if lo <= threshold <= hi or ood or leak:
        assert value == "tidak_yakin"  # BR-33, BR-34


def test_status_rejects_reversed_interval() -> None:
    with pytest.raises(ValueError, match="lo > hi"):
        decide_status(0.05, 0.01, 0.01, ood_high=False, leakage_flagged=False)


# --- kontrak ScanReport (BR-06, BR-60) ---


def test_br60_scan_report_schema_matches_versioned_snapshot() -> None:
    """Mengubah skema tanpa menaikkan `schema_version` membuat uji ini gagal (AC-10)."""
    snapshot = CONTRACTS / f"scan_report_{SCHEMA_VERSION}.schema.json"
    assert snapshot.exists(), f"buat snapshot kontrak untuk versi {SCHEMA_VERSION}"
    stored = json.loads(snapshot.read_text(encoding="utf-8"))
    assert ScanReport.model_json_schema() == stored


def _report_payload() -> dict[str, object]:
    return {
        "scan_id": "scn_test",
        "model": {"version": "0.1.0", "experimental": True, "profile_schema_version": "v1"},
        "estimate": {
            "delta": 0.031,
            "delta_relative": None,
            "interval_90": [0.012, 0.050],
            "ood_score": 0.4,
        },
        "status": {
            "value": "material",
            "threshold": 0.010,
            "noise_floor_estimated": 0.004,
            "reasons": ["interval_above_threshold"],
        },
        "findings": [],
        "input_warnings": [],
    }


def test_br06_condition_is_fixed_and_always_present() -> None:
    report = ScanReport.model_validate(_report_payload())
    assert report.condition == CONDITION
    assert json.loads(report.model_dump_json())["condition"] == CONDITION
    with pytest.raises(ValidationError):
        ScanReport.model_validate({**_report_payload(), "condition": "kalimat lain"})


def test_br60_contract_rejects_unknown_fields_and_bad_intervals() -> None:
    with pytest.raises(ValidationError):
        ScanReport.model_validate({**_report_payload(), "delta_f1": 0.1})  # BR-07
    payload = _report_payload()
    payload["estimate"] = {**payload["estimate"], "interval_90": [0.05, 0.01]}  # type: ignore[dict-item]
    with pytest.raises(ValidationError, match="lo <= hi"):
        ScanReport.model_validate(payload)


# --- scan end-to-end ---


def _dirty_frame(pilot: SmallPilot, row_index: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Bangun ulang data kotor sebuah run dari run store (jalur riset)."""
    row = pilot.runs.iloc[row_index]
    prepared = pilot.prepared[int(row["dataset_id"])]
    specs = [parse_spec(item) for item in json.loads(row["spec_json"])]
    seed = run_seed(prepared.dataset_id, row["config_id"], int(row["seed_index"]))
    _, result = dirty_train(prepared, specs, seed, pilot.learner)
    return result.frame, row.to_dict()


def test_br35_scan_report_is_experimental_and_valid(small_pilot: SmallPilot) -> None:
    artifact = load_artifact(small_pilot.artifact_dir)
    frame, _ = _dirty_frame(small_pilot, 0)
    report = scan(frame, "class", artifact, scan_id="scn_a")
    assert report.model.experimental is True
    assert report.schema_version == "1.0"
    assert report.estimate.delta_relative is None  # ADR 0011: null selama pilot
    assert report.findings == []
    assert report.status.threshold == materiality_threshold(report.status.noise_floor_estimated)
    lo, hi = report.estimate.interval_90
    assert lo <= report.estimate.delta <= hi
    ScanReport.model_validate_json(report.model_dump_json())


def test_ac12_same_data_gives_the_same_report(small_pilot: SmallPilot) -> None:
    artifact = load_artifact(small_pilot.artifact_dir)
    frame, _ = _dirty_frame(small_pilot, 3)
    first = scan(frame, "class", artifact, scan_id="scn_x")
    second = scan(frame, "class", artifact, scan_id="scn_x")
    assert first == second


def test_br16_research_and_scan_paths_agree(small_pilot: SmallPilot) -> None:
    """Uji konsistensi jalur: profil tersimpan = profil scan; prediksi selisih < 1e-9."""
    artifact = load_artifact(small_pilot.artifact_dir)
    for index in range(0, len(small_pilot.runs), 7):
        frame, row = _dirty_frame(small_pilot, index)
        stored = {name: float(row[f"p_{name}"]) for name in FEATURES}
        profile = compute_profile(frame, "class", learner=artifact.learner, seed=PROFILE_SEED)
        assert profile.features == stored
        report = scan(frame, "class", artifact, scan_id="scn_c")
        assert abs(report.estimate.delta - artifact.predict(stored)) < 1e-9


def test_br10_contract_rejection_stops_the_scan(small_pilot: SmallPilot) -> None:
    artifact = load_artifact(small_pilot.artifact_dir)
    frame, _ = _dirty_frame(small_pilot, 0)
    with pytest.raises(InputContractError, match="target_missing"):
        scan(frame, "nope", artifact)
    with pytest.raises(InputContractError, match="BR-10"):
        read_table(Path("data.xlsx"))


def test_cli_scan_writes_report_and_rejects_bad_input(
    small_pilot: SmallPilot, tmp_path: Path
) -> None:
    frame, _ = _dirty_frame(small_pilot, 0)
    data = tmp_path / "data.parquet"
    frame.to_parquet(data, index=False)
    out = tmp_path / "report.json"
    runner = CliRunner()
    args = ["scan", str(data), "--target", "class", "--artifact", str(small_pilot.artifact_dir)]
    result = runner.invoke(app, [*args, "--out", str(out)])
    assert result.exit_code == 0, result.output
    report = ScanReport.model_validate_json(out.read_text(encoding="utf-8"))
    assert report.model.experimental is True
    rejected = runner.invoke(app, [*args[:3], "nope", *args[4:]])
    assert rejected.exit_code == 2
    assert "input_contract" in rejected.output
