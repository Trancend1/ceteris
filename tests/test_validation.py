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
