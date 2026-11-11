"""Uji loader korpus, protokol D₀, saringan, split tetap, dan idempotensi (F-S01, BR-80)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest

from ceteris import corpus
from ceteris.corpus import (
    TEST,
    TRAIN,
    CorpusError,
    CorpusFilter,
    OpenMLFetcher,
    RawDataset,
    SplitSpec,
    evaluate_filter,
    frame_sha256,
    list_suite_dataset_ids,
    load_experiment_config,
    make_split,
    missing_cell_frac,
    prepare_corpus,
    prepare_dataset,
    to_base_dataset,
)
from tests.conftest import CONFIGS, FakeFetcher, make_frame

SMALL = CorpusFilter(min_rows=100, max_rows=5000, min_class_count=5)


def _raw(frame: pd.DataFrame, dataset_id: int = 1) -> RawDataset:
    return RawDataset(dataset_id, "x", 1, "Public", "md5", "class", frame)


def test_d0_protocol_drops_missing_target_and_categorises_text() -> None:
    frame = make_frame(n=50)
    frame.loc[3, "class"] = None
    base = to_base_dataset(_raw(frame))
    assert len(base) == 49
    assert isinstance(base["c0"].dtype, pd.CategoricalDtype)
    assert isinstance(base["class"].dtype, pd.CategoricalDtype)
    assert list(base["class"].cat.categories) == sorted(base["class"].cat.categories)
    assert base["x2"].dtype == "int64"
    assert list(base.index) == list(range(49))


def test_d0_protocol_rejects_missing_target_column() -> None:
    with pytest.raises(CorpusError, match="target"):
        to_base_dataset(RawDataset(1, "x", 1, "", "", "nope", make_frame(n=10)))


def test_filter_reports_each_violated_criterion() -> None:
    base = to_base_dataset(_raw(make_frame(n=120, n_classes=3, missing_frac=0.5)))
    reasons = evaluate_filter(
        base,
        "class",
        CorpusFilter(
            min_rows=200,
            max_rows=100,
            max_missing_cell_frac=0.01,
            max_features=2,
            max_classes=2,
            min_class_count=100,
        ),
    )
    joined = " | ".join(reasons)
    for fragment in ["rows 120 < 200", "rows 120 > 100", "missing_cell_frac", "BR-10", "classes 3"]:
        assert fragment in joined
    assert "min_class_count" in joined


def test_filter_passes_conforming_dataset() -> None:
    base = to_base_dataset(_raw(make_frame(n=300)))
    assert evaluate_filter(base, "class", SMALL) == []


def test_missing_is_measured_per_feature_cell() -> None:
    frame = pd.DataFrame(
        {"a": [1.0, None, 3.0, 4.0], "b": [1.0, 2.0, 3.0, 4.0], "class": list("xyxy")}
    )
    assert missing_cell_frac(frame, "class") == pytest.approx(1 / 8)


def test_split_is_fixed_stratified_and_sized() -> None:
    base = to_base_dataset(_raw(make_frame(n=500, n_classes=3)))
    labels = make_split(base, "class", SplitSpec(test_frac=0.2), seed=7)
    again = make_split(base, "class", SplitSpec(test_frac=0.2), seed=7)
    assert np.array_equal(labels, again)
    assert (labels == TEST).sum() == 100
    test_share = base.loc[labels == TEST, "class"].value_counts(normalize=True).sort_index()
    all_share = base["class"].value_counts(normalize=True).sort_index()
    assert np.allclose(test_share.to_numpy(), all_share.to_numpy(), atol=0.03)


def test_prepare_is_idempotent_and_records_hash_and_licence(tmp_path: Path) -> None:
    fetcher = FakeFetcher({5: make_frame(n=400)})
    first = prepare_dataset(5, fetcher, tmp_path, SMALL)
    second = prepare_dataset(5, fetcher, tmp_path, SMALL)
    assert fetcher.calls == [5], "unduhan ulang tidak boleh menghubungi sumber lagi"
    assert first.passed and second.passed
    assert first.meta["licence"] == "Public"
    assert first.meta["source_checksum"] == "md5-5"
    assert second.meta["d0_sha256"] == frame_sha256(second.frame)  # type: ignore[arg-type]
    assert frame_sha256(first.test_frame()) == frame_sha256(second.test_frame())
    assert len(first.train_frame()) + len(first.test_frame()) == 400


def test_prepare_detects_tampered_storage(tmp_path: Path) -> None:
    prepare_dataset(6, FakeFetcher({6: make_frame(n=300)}), tmp_path, SMALL)
    stored = pd.read_parquet(tmp_path / "6" / "d0.parquet")
    stored.loc[0, "x0"] = 999.0
    stored.to_parquet(tmp_path / "6" / "d0.parquet", index=False)
    with pytest.raises(CorpusError, match="d0_sha256"):
        prepare_dataset(6, FakeFetcher({}), tmp_path, SMALL)


def test_prepare_rejects_changed_filter_for_existing_folder(tmp_path: Path) -> None:
    prepare_dataset(7, FakeFetcher({7: make_frame(n=300)}), tmp_path, SMALL)
    with pytest.raises(CorpusError, match="saringan"):
        prepare_dataset(7, FakeFetcher({}), tmp_path, CorpusFilter())


def test_failed_dataset_keeps_metadata_only(tmp_path: Path) -> None:
    fetcher = FakeFetcher({8: make_frame(n=50)})
    prepared = prepare_dataset(8, fetcher, tmp_path, SMALL)
    assert not prepared.passed
    assert not (tmp_path / "8" / "d0.parquet").exists()
    with pytest.raises(CorpusError):
        prepared.train_frame()
    again = prepare_dataset(8, fetcher, tmp_path, SMALL)
    assert fetcher.calls == [8]
    assert again.meta["reasons"] == prepared.meta["reasons"]


def test_prepare_corpus_handles_many(tmp_path: Path) -> None:
    fetcher = FakeFetcher({1: make_frame(n=300), 2: make_frame(n=60)})
    results = prepare_corpus([1, 2], fetcher, tmp_path, SMALL)
    assert [r.passed for r in results] == [True, False]


def test_partitions_cover_all_rows(tmp_path: Path) -> None:
    prepared = prepare_dataset(9, FakeFetcher({9: make_frame(n=250)}), tmp_path, SMALL)
    assert set(np.unique(prepared.partition)) == {TRAIN, TEST}  # type: ignore[arg-type]


def test_suite_listing_parses_study_payload() -> None:
    payload = {"study": {"data": {"data_id": ["31", "3", "1590"]}}}
    urls: list[str] = []

    def fake(url: str) -> dict[str, Any]:
        urls.append(url)
        return payload

    assert list_suite_dataset_ids(99, fake) == [3, 31, 1590]
    assert urls == ["https://www.openml.org/api/v1/json/study/99"]
    with pytest.raises(CorpusError):
        list_suite_dataset_ids(99, lambda _: {"study": {}})


def test_openml_fetcher_maps_sklearn_bunch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    frame = make_frame(n=20)
    captured: dict[str, Any] = {}

    def fake_fetch_openml(**kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)
        details = {
            "name": "credit",
            "version": "2",
            "licence": "CC0",
            "md5_checksum": "abc",
            "default_target_attribute": "class",
        }
        return SimpleNamespace(details=details, frame=frame)

    import sklearn.datasets

    monkeypatch.setattr(sklearn.datasets, "fetch_openml", fake_fetch_openml)
    raw = OpenMLFetcher(tmp_path).fetch(31)
    assert (raw.name, raw.version, raw.licence, raw.source_checksum) == ("credit", 2, "CC0", "abc")
    assert captured["data_id"] == 31 and captured["data_home"] == str(tmp_path)
    assert captured["parser"] == "liac-arff"

    def multi_target(**_: Any) -> SimpleNamespace:
        return SimpleNamespace(details={"default_target_attribute": "a,b"}, frame=frame)

    monkeypatch.setattr(sklearn.datasets, "fetch_openml", multi_target)
    with pytest.raises(CorpusError, match="tidak tunggal"):
        OpenMLFetcher(tmp_path).fetch(31)


def test_experiment_config_matches_adr_0008() -> None:
    config = load_experiment_config(CONFIGS / "experiment.yaml")
    assert config.suite_id == corpus.CC18_SUITE_ID
    assert (config.filter.min_rows, config.filter.max_rows) == (2000, 50000)
    assert config.filter.max_missing_cell_frac == 0.05
    assert (config.filter.max_features, config.filter.max_classes) == (500, 20)
    assert config.split.test_frac == 0.2


def test_meta_json_is_valid(tmp_path: Path) -> None:
    prepare_dataset(10, FakeFetcher({10: make_frame(n=300)}), tmp_path, SMALL)
    meta = json.loads((tmp_path / "10" / "meta.json").read_text(encoding="utf-8"))
    assert meta["passed"] is True and meta["split_seed"] is not None


def test_d0_protocol_converts_nullable_numeric_types() -> None:
    frame = pd.DataFrame(
        {
            "full": pd.array([1, 2, 3, 4], dtype="Int64"),
            "gap": pd.array([1, None, 3, 4], dtype="Int64"),
            "flt": pd.array([0.5, None, 1.5, 2.0], dtype="Float64"),
            "class": ["x", "y", "x", "y"],
        }
    )
    base = to_base_dataset(_raw(frame))
    assert str(base["full"].dtype) == "int64"
    assert str(base["gap"].dtype) == "float64" and np.isnan(base.loc[1, "gap"])
    assert str(base["flt"].dtype) == "float64"
    assert base["gap"].tolist()[::2] == [1.0, 3.0]


def test_br11_class_count_is_checked_on_train_partition(tmp_path: Path) -> None:
    """Kelas dengan 22 baris lolos di data penuh, tetapi hanya ~18 baris di partisi latih."""
    frame = make_frame(n=300)
    frame.loc[:21, "class"] = "rare"
    spec = CorpusFilter(min_rows=100, max_rows=5000, min_class_count=20)
    prepared = prepare_dataset(11, FakeFetcher({11: frame}), tmp_path, spec)
    assert not prepared.passed
    assert "BR-17" in prepared.meta["reasons"][0]
    assert not (tmp_path / "11" / "d0.parquet").exists()
