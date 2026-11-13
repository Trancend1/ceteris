"""Uji kelayakan dan split pasangan E4 (analysis-plan bagian 11; BR-80, BR-84)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from ceteris.corpus import SplitSpec
from ceteris.validation import CANDIDATES, Candidate, IneligibleError, load_pair


def _write(root: Path, name: str, frame: pd.DataFrame) -> str:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return name


def _frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    clean = pd.DataFrame(
        {
            "city": ["Jakarta", "Bandung"] * 50,
            "x": range(100),
            "drop_me": range(100),
            "y": [0, 1, 1, 0] * 25,
        }
    )
    dirty = clean.assign(city=["jkt", "Bandung"] * 50)
    return dirty, clean


def test_pair_split_keeps_rows_aligned_and_test_clean(tmp_path: Path) -> None:
    dirty, clean = _frames()
    cand = Candidate(
        "Toy",
        "inconsistency",
        _write(tmp_path, "d.csv", dirty),
        _write(tmp_path, "c.csv", clean),
        "y",
        ("drop_me",),
    )
    import ceteris.validation as validation

    validation.GROUND_TRUTH["Toy"] = False
    pair = load_pair(cand, tmp_path, SplitSpec())
    assert "drop_me" not in pair.dirty_train.columns
    assert len(pair.dirty_train) == len(pair.clean_train) == 80
    assert (pair.dirty_train["x"].to_numpy() == pair.clean_train["x"].to_numpy()).all()
    assert set(pair.clean_test["city"].astype(str)) <= {"Jakarta", "Bandung"}  # BR-80
    again = load_pair(cand, tmp_path, SplitSpec())  # BR-84: seed tetap
    assert pair.meta["test_sha256"] == again.meta["test_sha256"]


def test_pair_without_clean_version_or_alignment_is_ineligible(tmp_path: Path) -> None:
    dirty, clean = _frames()
    no_clean = Candidate("A", "duplicates", _write(tmp_path, "d.csv", dirty), None, "y")
    with pytest.raises(IneligibleError, match="versi bersih"):
        load_pair(no_clean, tmp_path, SplitSpec())
    short = Candidate(
        "B", "inconsistency", "d.csv", _write(tmp_path, "c2.csv", clean.iloc[:90]), "y"
    )
    with pytest.raises(IneligibleError, match="selaras"):
        load_pair(short, tmp_path, SplitSpec())


def test_candidates_follow_the_pre_registered_order() -> None:
    names = [c.name for c in CANDIDATES]
    assert names == ["Company", "University", "Movie", "Restaurant", "Clothing", "Citation"]


def test_changed_cells_treats_two_missing_cells_as_equal() -> None:
    from ceteris.validation import changed_cells

    dirty = pd.DataFrame({"a": ["x", None, "z"], "b": [1.0, float("nan"), 3.0]})
    clean = pd.DataFrame({"a": ["x", None, "Z"], "b": [1.0, float("nan"), 4.0]})
    assert changed_cells(dirty, clean) == 2


def test_holdout_pool_excludes_cc18_and_corpus_names_before_download() -> None:
    """ADR 0014 butir 3: pra-saring hanya dari kualitas OpenML."""
    from ceteris.validation import holdout_pool

    def quality(n: int, f: int, k: int, minority: int, missing: int) -> list[dict[str, str]]:
        values = {
            "NumberOfInstances": n,
            "NumberOfFeatures": f,
            "NumberOfClasses": k,
            "MinorityClassSize": minority,
            "NumberOfMissingValues": missing,
        }
        return [{"name": key, "value": str(v)} for key, v in values.items()]

    listing = [
        {
            "did": 1,
            "name": "ok",
            "version": 1,
            "status": "active",
            "quality": quality(3000, 11, 2, 900, 0),
        },
        {
            "did": 2,
            "name": "Small",
            "version": 1,
            "status": "active",
            "quality": quality(500, 11, 2, 200, 0),
        },
        {
            "did": 3,
            "name": "JM1",
            "version": 1,
            "status": "active",
            "quality": quality(3000, 11, 2, 900, 0),
        },
    ]

    def fake(url: str) -> dict:
        if url.endswith("/study/99"):
            return {"study": {"data": {"data_id": [4]}}}
        if "/study/" in url:
            return {"study": {"data": {"data_id": [1, 2, 3, 4]}}}
        assert "data_id/1,2,3" in url  # anggota CC18 (4) sudah dikeluarkan
        return {"data": {"dataset": listing}}

    rows = holdout_pool(["jm1"], fake)
    passed = {r["dataset_id"]: r["prescreen_passed"] for r in rows}
    assert passed == {1: True, 2: False, 3: False}
