"""ceteris.validation: E4 (data kotor asli, RQ4) dan uji konsistensi jalur akhir (BR-16).

Fitur: F-S13, F-S14 (validasi Phase 5). Jalur: riset (boleh mengimpor jalur scan, tidak
sebaliknya; AC-3). Protokol: `docs/analysis-plan.md` bagian 11 dan ADR 0014, ditulis sebelum
data CleanML diunduh. Aturan: BR-01 (ΔAUC), BR-05 (T), BR-16 (profil identik), BR-80 (test set
tidak berubah), BR-84 (seed eksplisit), BR #12 (CSV hanya peringatan).

Data sumber tidak pernah ditulis (BR-70): pasangan dibaca dari folder ekstraksi CleanML, dan
semua turunannya ditulis ke folder keluaran.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ceteris.artifact import Artifact, load_artifact
from ceteris.corpus import (
    CC18_SUITE_ID,
    OPENML_API,
    OpenMLFetcher,
    RawDataset,
    SplitSpec,
    _http_get_json,
    frame_sha256,
    list_suite_dataset_ids,
    load_experiment_config,
    make_split,
    prepare_dataset,
    to_base_dataset,
)
from ceteris.corrupt import parse_spec
from ceteris.dqprofile import FEATURES, PROFILE_SEED, compute_profile, noise_floor_value
from ceteris.evaluate import bootstrap_ci
from ceteris.experiment import dirty_train
from ceteris.scan import materiality_threshold, read_table, scan_file
from ceteris.seeding import derive_seed, run_seed
from ceteris.store import REPO_ROOT, RunStore, provenance
from ceteris.train import LearnerSpec, load_learner_spec, measure_delta_auc, measure_noise_floor

E4_SEEDS = 5
E4_NOISE_FLOOR_SEEDS = 10
MAX_PAIRS = 5
PREDICTION_TOL = 1e-9


@dataclass(frozen=True)
class Candidate:
    """Kandidat E4 tetap (analysis-plan bagian 11), urutan sesuai rencana."""

    name: str
    error_type: str
    dirty: str
    clean: str | None
    label: str
    drop: tuple[str, ...] = ()


# Label dan `drop_variables` mengikuti skema CleanML (`schema/dataset.py`).
CANDIDATES: tuple[Candidate, ...] = (
    Candidate(
        "Company",
        "inconsistency",
        "Company/raw/raw.csv",
        "Company/raw/inconsistency_clean_raw.csv",
        "Sentiment",
        ("Date", "Unnamed: 0", "City"),
    ),
    Candidate(
        "University",
        "inconsistency",
        "University/raw/raw.csv",
        "University/raw/inconsistency_clean_raw.csv",
        "expenses thous$",
        ("university name", "academic-emphasis"),
    ),
    Candidate(
        "Movie",
        "inconsistency",
        "Movie/raw/raw.csv",
        "Movie/raw/inconsistency_clean_raw.csv",
        "genres",
    ),
    Candidate(
        "Restaurant",
        "inconsistency",
        "Restaurant/raw/raw.csv",
        "Restaurant/raw/inconsistency_clean_raw.csv",
        "priceRange",
        ("streetAddress", "telephone", "website"),
    ),
    Candidate("Clothing", "mislabel", "Clothing/raw/raw.csv", None, "label"),
    Candidate("Citation", "duplicates", "Citation/raw/raw.csv", None, "CS"),
)

# Makalah CleanML: inkonsistensi diperbaiki dengan OpenRefine (clustering lalu merge ke nilai
# terbanyak), bukan ground truth manual. Dicatat di ADR 0014 [F].
GROUND_TRUTH: dict[str, bool] = {c.name: False for c in CANDIDATES}


@dataclass(frozen=True)
class Pair:
    name: str
    target: str
    dirty_train: pd.DataFrame
    clean_train: pd.DataFrame
    clean_test: pd.DataFrame
    meta: dict[str, Any]


class IneligibleError(RuntimeError):
    """Pasangan tidak layak menurut kriteria struktural analysis-plan bagian 11."""


def _read(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, low_memory=False)
    frame.columns = [str(c).strip() for c in frame.columns]
    return frame


def load_pair(candidate: Candidate, root: Path, split: SplitSpec) -> Pair:
    """Bangun pasangan latih kotor, latih bersih, dan uji bersih; tolak bila tidak layak."""
    if candidate.clean is None:
        raise IneligibleError("tidak ada berkas versi bersih di arsip CleanML")
    dirty_path, clean_path = Path(root) / candidate.dirty, Path(root) / candidate.clean
    missing = [str(p) for p in (dirty_path, clean_path) if not p.exists()]
    if missing:
        raise IneligibleError(f"berkas tidak ada di arsip: {missing}")
    dirty, clean = _read(dirty_path), _read(clean_path)
    if list(dirty.columns) != list(clean.columns) or len(dirty) != len(clean):
        raise IneligibleError("baris atau kolom versi kotor dan bersih tidak selaras")
    keep = [c for c in dirty.columns if c not in candidate.drop]
    labelled = dirty[candidate.label].notna() & clean[candidate.label].notna()
    dirty = dirty.loc[labelled, keep].reset_index(drop=True)
    clean = clean.loc[labelled, keep].reset_index(drop=True)
    bases = [
        to_base_dataset(RawDataset(0, candidate.name, 0, "", "", candidate.label, frame))
        for frame in (dirty, clean)
    ]
    dirty_base, clean_base = bases
    target = candidate.label
    seed = derive_seed("e4", candidate.name)
    partition = make_split(clean_base, target, split, seed)
    train, test = partition == "train", partition == "test"
    if list(dirty_base[target].cat.categories) != list(clean_base[target].cat.categories):
        raise IneligibleError("kategori label versi kotor dan bersih berbeda")
    pair = Pair(
        candidate.name,
        target,
        dirty_base.loc[train].reset_index(drop=True),
        clean_base.loc[train].reset_index(drop=True),
        clean_base.loc[test].reset_index(drop=True),
        {
            "name": candidate.name,
            "error_type": candidate.error_type,
            "ground_truth": GROUND_TRUTH[candidate.name],
            "dirty_file": candidate.dirty,
            "clean_file": candidate.clean,
            "dropped_columns": list(candidate.drop),
            "split_seed": seed,
            "n_rows": int(len(clean_base)),
            "n_train": int(np.sum(train)),
            "n_test": int(np.sum(test)),
            "n_features": int(clean_base.shape[1] - 1),
            "n_classes": int(clean_base[target].nunique()),
            "changed_train_cells": changed_cells(
                dirty_base.loc[train].reset_index(drop=True),
                clean_base.loc[train].reset_index(drop=True),
            ),
        },
    )
    pair.meta["test_sha256"] = frame_sha256(pair.clean_test)
    return pair


def changed_cells(dirty: pd.DataFrame, clean: pd.DataFrame) -> int:
    """Jumlah sel yang berbeda; dua sel kosong dianggap sama (deskriptif, bukan kriteria)."""
    total = 0
    for name in dirty.columns:
        a, b = dirty[name].astype(object), clean[name].astype(object)
        total += int((~((a == b) | (a.isna() & b.isna()))).sum())
    return total


def _profile_check(
    frame: pd.DataFrame, target: str, parquet: Path, artifact: Artifact
) -> dict[str, Any]:
    """BR-16: profil jalur riset (frame di memori) vs jalur scan (berkas Parquet)."""
    research = compute_profile(frame, target, learner=artifact.learner, seed=PROFILE_SEED)
    scanned = compute_profile(
        read_table(parquet), target, learner=artifact.learner, seed=PROFILE_SEED
    )
    diffs = {
        name: abs(research.features[name] - scanned.features[name])
        for name in FEATURES
        if not _same(research.features[name], scanned.features[name])
    }
    return {"profile_identical": not diffs, "profile_diffs": diffs, "features": research.features}


def _same(a: float, b: float) -> bool:
    return (math.isnan(a) and math.isnan(b)) or a == b


def evaluate_pair(
    pair: Pair, artifact: Artifact, learner: LearnerSpec, out: Path
) -> dict[str, Any]:
    """Ukuran E4 satu pasangan (analysis-plan bagian 11)."""
    folder = Path(out) / "pairs" / pair.name
    folder.mkdir(parents=True, exist_ok=True)
    parquet, csv = folder / "dirty_train.parquet", folder / "dirty_train.csv"
    pair.dirty_train.to_parquet(parquet, index=False)
    pair.dirty_train.to_csv(csv, index=False)
    test_hash = frame_sha256(pair.clean_test)

    deltas = []
    for i in range(E4_SEEDS):
        seed = derive_seed("e4", pair.name, i)
        result = measure_delta_auc(
            learner, pair.clean_train, pair.dirty_train, pair.clean_test, pair.target, seed
        )
        deltas.append({"seed": seed, **asdict(result)})
    nf_seeds = [derive_seed("e4", pair.name, "noise_floor", i) for i in range(E4_NOISE_FLOOR_SEEDS)]
    aucs = measure_noise_floor(learner, pair.clean_train, pair.clean_test, pair.target, nf_seeds)
    if frame_sha256(pair.clean_test) != test_hash:
        raise RuntimeError("test set berubah selama E4 (BR-80)")
    noise_floor = noise_floor_value(aucs, artifact.metadata.noise_floor_statistic)
    threshold = materiality_threshold(noise_floor)
    actual = float(np.mean([d["delta_auc"] for d in deltas]))

    report = scan_file(parquet, pair.target, artifact.path, f"e4_{pair.name}")
    lo, hi = report.estimate.interval_90
    predicted = report.estimate.delta
    reference = "material" if actual > threshold else "tidak_material"
    check = _profile_check(pair.dirty_train, pair.target, parquet, artifact)
    research_prediction = artifact.predict(check.pop("features"))
    csv_report = scan_file(csv, pair.target, artifact.path, f"e4_{pair.name}_csv")
    return {
        **pair.meta,
        "delta_auc_actual": actual,
        "delta_auc_per_seed": deltas,
        "noise_floor_measured": noise_floor,
        "threshold_reference": threshold,
        "predicted": predicted,
        "interval_90": [lo, hi],
        "abs_error": abs(predicted - actual),
        "abs_error_per_seed": [abs(predicted - d["delta_auc"]) for d in deltas],
        "covered": bool(lo <= actual <= hi),
        "ood_score": report.estimate.ood_score,
        "ood_high": artifact.ood_high(report.estimate.ood_score),
        "status_scan": report.status.value,
        "status_reasons": report.status.reasons,
        "status_reference": reference,
        "status_agrees": report.status.value == reference,
        "noise_floor_estimated": report.status.noise_floor_estimated,
        "findings": [f.model_dump() for f in report.findings],
        "input_warnings": report.input_warnings,
        "br16": {
            **check,
            "prediction_diff": abs(research_prediction - predicted),
            "passed": check["profile_identical"]
            and abs(research_prediction - predicted) < PREDICTION_TOL,
        },
        "csv": {
            "predicted": csv_report.estimate.delta,
            "prediction_diff_vs_parquet": abs(csv_report.estimate.delta - predicted),
            "type_warnings": [w for w in csv_report.input_warnings if w.startswith("csv_")],
        },
    }


def e4_report(root: Path, artifact_path: Path, e1_report: Path, out: Path) -> dict[str, Any]:
    """Jalankan E4 pada kandidat tetap dan ringkas menurut kriteria bagian 4."""
    learner = load_learner_spec(REPO_ROOT / "configs" / "learner.yaml")
    artifact = load_artifact(artifact_path)
    split = load_experiment_config(REPO_ROOT / "configs" / "experiment.yaml").split
    mae_lodo = _mae_lodo(e1_report)
    eligible: list[Pair] = []
    ineligible: list[dict[str, str]] = []
    for candidate in CANDIDATES:
        try:
            eligible.append(load_pair(candidate, root, split))
        except IneligibleError as err:
            ineligible.append({"name": candidate.name, "reason": str(err)})
    if len(eligible) > MAX_PAIRS:
        rng = np.random.default_rng(derive_seed("e4", "pairs"))
        draws = rng.random(len(eligible))
        ranked = sorted(
            range(len(eligible)), key=lambda i: (not eligible[i].meta["ground_truth"], draws[i])
        )
        eligible = [eligible[i] for i in ranked[:MAX_PAIRS]]
    results = []
    for pair in eligible:
        try:
            results.append(evaluate_pair(pair, artifact, learner, out))
        except Exception as err:  # kontrak input (BR-10, BR-11) membuat pasangan tidak layak
            ineligible.append({"name": pair.name, "reason": f"{type(err).__name__}: {err}"})
    errors = [r["abs_error"] for r in results]
    median_error = float(np.median(errors)) if errors else float("nan")
    prov = provenance()
    payload = {
        "label": "eksperimental; E4 eksploratif (RQ4); tidak ada pasangan ground truth",
        "artifact": artifact.metadata.version,
        "git_commit": prov.git_commit,
        "git_dirty": prov.git_dirty,
        "mae_lodo": mae_lodo,
        "error_limit": 2 * mae_lodo,
        "pairs": results,
        "ineligible": ineligible,
        "summary": {
            "n_pairs": len(results),
            "n_ground_truth": sum(bool(r["ground_truth"]) for r in results),
            "median_abs_error": median_error,
            "median_abs_error_ci95": list(bootstrap_ci(errors)) if errors else None,
            "within_limit": [r["name"] for r in results if r["abs_error"] <= 2 * mae_lodo],
            "criterion_met": bool(errors) and median_error <= 2 * mae_lodo,
            "coverage": float(np.mean([r["covered"] for r in results])) if results else None,
            "status_counts": pd.Series([r["status_scan"] for r in results])
            .value_counts()
            .to_dict(),
            "br16_passed": all(r["br16"]["passed"] for r in results),
        },
    }
    Path(out).mkdir(parents=True, exist_ok=True)
    (Path(out) / "e4_report.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=_json), encoding="utf-8"
    )
    return payload


def _mae_lodo(e1_report: Path) -> float:
    """MAE LODO dibaca dari laporan E1 (`methods`, baris `metamodel`), bukan diketik ulang."""
    report = json.loads(Path(e1_report).read_text(encoding="utf-8"))
    row = next(m for m in report["methods"] if m["method"] == "metamodel")
    return float(row["mae"])


def paths_report(
    store_root: Path, corpus_root: Path, artifact_path: Path, out: Path
) -> dict[str, Any]:
    """BR-16 pada korpus: satu run per dataset (konfigurasi tunggal pertama, seed indeks 0)."""
    learner = load_learner_spec(REPO_ROOT / "configs" / "learner.yaml")
    artifact = load_artifact(artifact_path)
    cfg = load_experiment_config(REPO_ROOT / "configs" / "experiment.yaml")
    runs = RunStore(Path(store_root)).read("corruption_run")
    singles = runs[(runs["seed_index"] == 0) & (~runs["kinds"].str.contains(","))]
    chosen = singles.sort_values(["dataset_id", "config_id"]).groupby("dataset_id").head(1)
    rows = []
    folder = Path(out) / "paths"
    folder.mkdir(parents=True, exist_ok=True)
    for row in chosen.to_dict("records"):
        prepared = prepare_dataset(
            int(row["dataset_id"]), _NoFetch(), Path(corpus_root), cfg.filter, cfg.split
        )
        dataset_id = int(row["dataset_id"])
        specs = [parse_spec(item) for item in json.loads(row["spec_json"])]
        seed = run_seed(prepared.dataset_id, row["config_id"], int(row["seed_index"]))
        _, result = dirty_train(prepared, specs, seed, learner)
        parquet = folder / f"{dataset_id}.parquet"
        csv = folder / f"{dataset_id}.csv"
        result.frame.to_parquet(parquet, index=False)
        result.frame.to_csv(csv, index=False)
        stored = {name: float(row[f"p_{name}"]) for name in FEATURES}
        report = scan_file(parquet, prepared.target, artifact.path, f"br16_{dataset_id}")
        scanned = compute_profile(
            read_table(parquet), prepared.target, learner=artifact.learner, seed=PROFILE_SEED
        ).features
        diffs = {
            n: abs(stored[n] - scanned[n]) for n in FEATURES if not _same(stored[n], scanned[n])
        }
        prediction_diff = abs(artifact.predict(stored) - report.estimate.delta)
        csv_report = scan_file(csv, prepared.target, artifact.path, f"br16_{dataset_id}_csv")
        rows.append(
            {
                "dataset_id": dataset_id,
                "run_id": row["run_id"],
                "config_id": row["config_id"],
                "profile_identical": not diffs,
                "profile_diffs": diffs,
                "prediction_diff": prediction_diff,
                "passed": not diffs and prediction_diff < PREDICTION_TOL,
                "csv_prediction_diff": abs(csv_report.estimate.delta - report.estimate.delta),
                "csv_type_warnings": len(
                    [w for w in csv_report.input_warnings if w.startswith("csv_")]
                ),
            }
        )
    prov = provenance()
    payload = {
        "git_commit": prov.git_commit,
        "git_dirty": prov.git_dirty,
        "artifact": artifact.metadata.version,
        "n_datasets": len(rows),
        "passed": all(r["passed"] for r in rows),
        "n_csv_differs": sum(r["csv_prediction_diff"] > 0 for r in rows),
        "datasets": rows,
    }
    (Path(out) / "paths_report.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=_json), encoding="utf-8"
    )
    return payload


# --- dataset holdout epoch 1 (ADR 0013 butir 5, ADR 0014 butir 3) ---

HOLDOUT_STUDIES = (14, 218, 271)
HOLDOUT_TARGET = 15


def holdout_pool(
    corpus_names: Sequence[str], fetch_json: Callable[[str], dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Kandidat holdout yang lolos pra-saring kualitas OpenML; data tidak diunduh.

    Kumpulan = studi 14, 218, 271 − OpenML-CC18 − nama dataset korpus epoch 0.
    """
    getter = fetch_json or _http_get_json
    cfg = load_experiment_config(REPO_ROOT / "configs" / "experiment.yaml").filter
    pool: set[int] = set()
    for study in HOLDOUT_STUDIES:
        pool.update(list_suite_dataset_ids(study, getter))
    pool -= set(list_suite_dataset_ids(CC18_SUITE_ID, getter))
    excluded = {name.lower() for name in corpus_names}
    ids = ",".join(str(i) for i in sorted(pool))
    listing = getter(f"{OPENML_API}/data/list/data_id/{ids}/limit/1000")["data"]["dataset"]
    rows = []
    for item in listing:
        q = {d["name"]: float(d["value"]) for d in item.get("quality", []) if d.get("value")}
        n, f = q.get("NumberOfInstances", 0.0), q.get("NumberOfFeatures", 0.0) - 1
        k, minority = q.get("NumberOfClasses", 0.0), q.get("MinorityClassSize", 0.0)
        missing = q.get("NumberOfMissingValues", 0.0) / max(n * max(f, 1.0), 1.0)
        reasons = []
        if item.get("status") != "active":
            reasons.append(f"status {item.get('status')}")
        if str(item["name"]).lower() in excluded:
            reasons.append("nama sama dengan dataset korpus")
        if not cfg.min_rows <= n <= cfg.max_rows:
            reasons.append(f"rows {n:.0f}")
        if f > cfg.max_features:
            reasons.append(f"features {f:.0f}")
        if not cfg.min_classes <= k <= cfg.max_classes:
            reasons.append(f"classes {k:.0f}")
        if minority < cfg.min_class_count:
            reasons.append(f"minority {minority:.0f}")
        if missing > cfg.max_missing_cell_frac:
            reasons.append(f"missing {missing:.4f}")
        rows.append(
            {
                "dataset_id": int(item["did"]),
                "name": str(item["name"]),
                "version": int(item["version"]),
                "prescreen_passed": not reasons,
                "prescreen_reasons": reasons,
            }
        )
    return sorted(rows, key=lambda r: r["dataset_id"])


def seal_holdout(root: Path, corpus_root: Path, out: Path) -> dict[str, Any]:
    """Pilih dan segel holdout: undian berseed, lalu saringan penuh sampai 15 lolos.

    Yang dihitung hanya atribut saringan (`prepare_dataset`); tidak ada korupsi atau profil.
    """
    cfg = load_experiment_config(REPO_ROOT / "configs" / "experiment.yaml")
    corpus_names = [
        json.loads(p.read_text(encoding="utf-8"))["name"]
        for p in Path(corpus_root).glob("*/meta.json")
        if json.loads(p.read_text(encoding="utf-8"))["passed"]
    ]
    pool = holdout_pool(corpus_names)
    eligible = [r["dataset_id"] for r in pool if r["prescreen_passed"]]
    rng = np.random.default_rng(derive_seed("holdout", "epoch-1"))
    order = [int(i) for i in rng.permutation(sorted(eligible))]
    fetcher = OpenMLFetcher(Path(root) / "_openml")
    tried: list[dict[str, Any]] = []
    sealed: list[dict[str, Any]] = []
    for dataset_id in order:
        if len(sealed) == HOLDOUT_TARGET:
            break
        try:
            prepared = prepare_dataset(dataset_id, fetcher, Path(root), cfg.filter, cfg.split)
        except Exception as err:  # unduhan atau target tidak tunggal: dicatat, tidak dipakai
            tried.append({"dataset_id": dataset_id, "passed": False, "reasons": [repr(err)]})
            continue
        keys = ("name", "version", "passed", "reasons", "n_rows", "n_features", "n_classes")
        entry = {"dataset_id": dataset_id, **{k: prepared.meta[k] for k in keys}}
        tried.append(entry)
        if prepared.passed:
            hashes = ("source_checksum", "licence", "split_seed", "d0_sha256", "train_sha256")
            sealed.append({**entry, **{k: prepared.meta[k] for k in (*hashes, "test_sha256")}})
    payload = {
        "epoch": 1,
        "rule": "ADR 0013 butir 5; ADR 0014 butir 3",
        "seed": derive_seed("holdout", "epoch-1"),
        "studies": list(HOLDOUT_STUDIES),
        "target_count": HOLDOUT_TARGET,
        "sealed_count": len(sealed),
        "shortfall": max(0, HOLDOUT_TARGET - len(sealed)),
        "sealed": sealed,
        "tried": tried,
        "pool": pool,
    }
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


class _NoFetch:
    """Dataset korpus harus sudah disiapkan; tidak ada unduhan ulang."""

    def fetch(self, dataset_id: int) -> RawDataset:
        raise RuntimeError(f"dataset {dataset_id} belum disiapkan di folder korpus")


def _json(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(type(value).__name__)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ceteris.validation")
    sub = parser.add_subparsers(dest="command", required=True)
    e4 = sub.add_parser("e4", help="E4 pada pasangan CleanML (analysis-plan bagian 11)")
    e4.add_argument(
        "--root", type=Path, default=REPO_ROOT / "data" / "cleanml" / "extracted" / "data"
    )
    e4.add_argument("--artifact", type=Path, default=REPO_ROOT / "artifacts" / "metamodel-1.0.0")
    e4.add_argument("--e1-report", type=Path, default=REPO_ROOT / "runs" / "e1" / "report.json")
    e4.add_argument("--out", type=Path, default=REPO_ROOT / "runs" / "e4")
    hold = sub.add_parser("holdout", help="pilih dan segel holdout epoch 1 (ADR 0014)")
    hold.add_argument("--root", type=Path, default=REPO_ROOT / "data" / "holdout-epoch-1")
    hold.add_argument("--corpus", type=Path, default=REPO_ROOT / "data" / "corpus")
    hold.add_argument(
        "--out", type=Path, default=REPO_ROOT / "docs" / "epochs" / "epoch-0" / "holdout.json"
    )
    paths = sub.add_parser("paths", help="uji konsistensi jalur akhir pada korpus (BR-16)")
    paths.add_argument("--store", type=Path, default=REPO_ROOT / "runs" / "e1")
    paths.add_argument("--corpus", type=Path, default=REPO_ROOT / "data" / "corpus")
    paths.add_argument("--artifact", type=Path, default=REPO_ROOT / "artifacts" / "metamodel-1.0.0")
    paths.add_argument("--out", type=Path, default=REPO_ROOT / "runs" / "e4")
    args = parser.parse_args(argv)
    if args.command == "e4":
        payload = e4_report(args.root, args.artifact, args.e1_report, args.out)
    elif args.command == "holdout":
        payload = seal_holdout(args.root, args.corpus, args.out)
        payload = {k: v for k, v in payload.items() if k not in {"pool", "tried"}}
    else:
        payload = paths_report(args.store, args.corpus, args.artifact, args.out)
        payload = {k: v for k, v in payload.items() if k != "datasets"}
    summary = payload.get("summary", payload)
    print(json.dumps(summary, indent=1, ensure_ascii=False, default=_json), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
