"""ceteris.evaluate: ringkasan pilot E0 dan evaluasi LODO pilot.

Fitur: F-S11 (versi pilot; LODO bersarang penuh di Phase 4), F-S06. Jalur: riset saja (AC-3).
Aturan: BR-04, BR-05, BR-81, BR-85 (unit analisis dataset).

Semua angka laporan E0 dibaca dari run store (AGENTS.md bagian 5), bukan diketik manual.
Perintah: `python -m ceteris.evaluate e0 --store runs/e0 --out runs/e0/report.json`.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, get_args

import numpy as np
import pandas as pd

from ceteris.dqprofile import NoiseFloorStatistic, noise_floor_value
from ceteris.metamodel import lodo_predictions, pilot_methods
from ceteris.scan import materiality_threshold
from ceteris.store import RunStore

STATISTICS: tuple[NoiseFloorStatistic, ...] = get_args(NoiseFloorStatistic)
SEED_COUNTS = (2, 3, 5, 10)


def corruption_family(kinds: str) -> str:
    """Satu label per run: jenis tunggal, atau `mixture` untuk campuran."""
    parts = kinds.split(",")
    return parts[0] if len(parts) == 1 else "mixture"


def noise_floor_frame(store: RunStore) -> pd.DataFrame:
    frame = store.read("noise_floor")
    return frame.sort_values(
        ["dataset_id", "kind", "source_run_id", "seed_index"], na_position="first"
    )


def noise_floor_summary(nf: pd.DataFrame) -> pd.DataFrame:
    """Nilai noise floor per kelompok (dataset untuk terukur, run untuk estimasi).

    Untuk setiap statistik kandidat dan jumlah seed k, k seed pertama dipakai (awalan), sesuai
    cara `noise_floor_seeds` dan seed terukur diturunkan.
    """
    rows: list[dict[str, Any]] = []
    keys = ["dataset_id", "kind", "source_run_id"]
    for key, group in nf.fillna({"source_run_id": ""}).groupby(keys, sort=True):
        aucs = group.sort_values("seed_index")["auc"].to_numpy("float64")
        for k in SEED_COUNTS:
            if k > aucs.size:
                continue
            for statistic in STATISTICS:
                rows.append(
                    {
                        "dataset_id": int(key[0]),
                        "kind": key[1],
                        "source_run_id": key[2] or None,
                        "n_seeds": k,
                        "statistic": statistic,
                        "value": noise_floor_value(aucs[:k], statistic),
                    }
                )
    return pd.DataFrame(rows)


def noise_floor_comparison(summary: pd.DataFrame) -> pd.DataFrame:
    """Estimasi (per run) dibanding terukur (per dataset): bias dan selisih absolut (H5, pratinjau).

    Per dataset dihitung median selisih atas run-nya (BR-85), lalu diringkas antar-dataset.
    """
    measured = summary[summary["kind"] == "measured"].set_index(
        ["dataset_id", "statistic", "n_seeds"]
    )["value"]
    estimated = summary[summary["kind"] == "estimated"].copy()
    estimated["measured"] = [
        measured.get((d, s, k), np.nan)
        for d, s, k in estimated[["dataset_id", "statistic", "n_seeds"]].itertuples(index=False)
    ]
    estimated["bias"] = estimated["value"] - estimated["measured"]
    per_dataset = (
        estimated.groupby(["statistic", "n_seeds", "dataset_id"])
        .agg(bias=("bias", "median"), abs_diff=("bias", lambda b: float(np.median(np.abs(b)))))
        .reset_index()
    )
    return (
        per_dataset.groupby(["statistic", "n_seeds"])
        .agg(
            bias_median=("bias", "median"),
            abs_diff_median=("abs_diff", "median"),
            abs_diff_max=("abs_diff", "max"),
        )
        .reset_index()
    )


def measured_floor(summary: pd.DataFrame, statistic: str, n_seeds: int) -> dict[int, float]:
    sel = summary[
        (summary["kind"] == "measured")
        & (summary["statistic"] == statistic)
        & (summary["n_seeds"] == n_seeds)
    ]
    return {int(d): float(v) for d, v in zip(sel["dataset_id"], sel["value"], strict=True)}


def share_above_threshold(runs: pd.DataFrame, floors: dict[int, float]) -> pd.DataFrame:
    """Proporsi run dengan ΔAUC > T = max(0,01; noise floor terukur), per jenis korupsi.

    Kriteria pilot (rencana skripsi): ≥ 30% run tiap jenis di atas noise floor. Proporsi dihitung
    per dataset lalu diambil mediannya (BR-85), dan juga atas seluruh run.
    """
    frame = runs.assign(
        family=runs["kinds"].map(corruption_family),
        threshold=runs["dataset_id"].map(lambda d: materiality_threshold(floors[int(d)])),
    )
    frame["above"] = frame["delta_auc"] > frame["threshold"]
    per_dataset = frame.groupby(["family", "dataset_id"])["above"].mean().reset_index()
    return (
        per_dataset.groupby("family")["above"]
        .agg(share_median="median", share_min="min")
        .join(frame.groupby("family")["above"].mean().rename("share_all_runs"))
        .reset_index()
    )


def delta_auc_by_level(runs: pd.DataFrame) -> pd.DataFrame:
    """Median ΔAUC per jenis tunggal dan level (median per dataset dulu, BR-85)."""
    singles = runs[runs["nominal_level"].notna()].assign(
        family=lambda f: f["kinds"].map(corruption_family)
    )
    per_dataset = (
        singles.groupby(["family", "nominal_level", "dataset_id"])["delta_auc"]
        .median()
        .reset_index()
    )
    return (
        per_dataset.groupby(["family", "nominal_level"])["delta_auc"]
        .agg(median="median", min="min", max="max")
        .reset_index()
    )


def run_seconds(store: RunStore) -> pd.DataFrame:
    """Durasi tiap run berhasil dari `run_log` (detik, waktu dinding per proses)."""
    log = store.read("run_log")
    log = log[log["status"] == "ok"].copy()
    started = pd.to_datetime(log["started_at"], utc=True, format="ISO8601")
    finished = pd.to_datetime(log["finished_at"], utc=True, format="ISO8601")
    log["seconds"] = (finished - started).dt.total_seconds()
    return log[["run_id", "dataset_id", "seconds"]]


def cost_proxy(n_rows: float, n_features: float, n_classes: float) -> float:
    """Proxy biaya per run: baris × kolom × jumlah model biner efektif (multikelas = K)."""
    return float(n_rows) * float(n_features) * (1.0 if n_classes == 2 else float(n_classes))


def project_compute(
    per_dataset: pd.DataFrame, corpus: pd.DataFrame, runs_per_dataset: int, nf_per_dataset: int
) -> dict[str, float]:
    """Proyeksi kasar CPU korpus penuh dari pilot: log(detik) = a + b·log(proxy).

    `per_dataset` berkolom dataset_id, run_seconds, nf_seconds, proxy (dari pilot);
    `corpus` berkolom n_rows, n_features, n_classes untuk seluruh korpus.
    """
    x = np.log(per_dataset["proxy"].to_numpy("float64"))
    out: dict[str, float] = {}
    for column, count in (("run_seconds", runs_per_dataset), ("nf_seconds", nf_per_dataset)):
        y = np.log(per_dataset[column].to_numpy("float64"))
        slope, intercept = np.polyfit(x, y, deg=1)
        proxies = np.log(
            [
                cost_proxy(r, f, k)
                for r, f, k in corpus[["n_rows", "n_features", "n_classes"]].to_numpy()
            ]
        )
        predicted = np.exp(intercept + slope * proxies)
        out[f"{column}_slope"] = float(slope)
        out[f"{column}_cpu_hours"] = float(predicted.sum() * count / 3600.0)
    out["cpu_hours_total"] = out["run_seconds_cpu_hours"] + out["nf_seconds_cpu_hours"]
    return out


def lodo_metrics(predictions: pd.DataFrame) -> pd.DataFrame:
    """MAE, RMSE, bias per (metode, dataset), lalu median antar-dataset (BR-85). Eksploratif."""
    err = predictions.assign(error=predictions["predicted"] - predictions["actual"])
    per_dataset = (
        err.groupby(["method", "dataset_id"])["error"]
        .agg(
            mae=lambda e: float(np.mean(np.abs(e))),
            rmse=lambda e: float(np.sqrt(np.mean(np.square(e)))),
            bias="mean",
        )
        .reset_index()
    )
    return per_dataset


def e0_report(store_root: Path, corpus_meta: pd.DataFrame | None = None) -> dict[str, Any]:
    """Ringkasan E0 dari run store, siap ditulis sebagai JSON (angka laporan G2)."""
    store = RunStore(store_root)
    runs = store.read("corruption_run")
    nf = noise_floor_frame(store)
    summary = noise_floor_summary(nf)
    comparison = noise_floor_comparison(summary)
    log = store.read("run_log")
    seconds = run_seconds(store)
    datasets = store.read("corpus_dataset")
    failed = log[(log["status"] == "failed") & ~log["run_id"].isin(runs["run_id"])]
    failed = failed.drop_duplicates("run_id")  # percobaan ulang tidak dihitung dua kali
    report: dict[str, Any] = {
        "n_runs": len(runs),
        "n_failed": len(failed),
        "failed_errors": failed["error"].value_counts().to_dict(),
        "git_commits": sorted(log["git_commit"].unique().tolist()),
        "git_dirty_runs": int(log["git_dirty"].sum()),
        "datasets": datasets[["dataset_id", "name", "n_rows", "n_features", "n_classes"]].to_dict(
            "records"
        ),
        "noise_floor_measured": _records(summary[summary["kind"] == "measured"]),
        "noise_floor_comparison": _records(comparison),
        "delta_auc_by_level": _records(delta_auc_by_level(runs)),
    }
    shares: dict[str, Any] = {}
    for statistic in STATISTICS:
        for k in SEED_COUNTS:
            floors = measured_floor(summary, statistic, k)
            if len(floors) == runs["dataset_id"].nunique():
                shares[f"{statistic}@{k}"] = _records(share_above_threshold(runs, floors))
    report["share_above_threshold"] = shares
    timing = seconds.groupby("dataset_id")["seconds"].median().rename("run_seconds")
    nf_time = (
        nf[nf["kind"] == "estimated"]
        .groupby(["dataset_id", "source_run_id"])["batch_seconds"]
        .first()
        .groupby("dataset_id")
        .median()
        .rename("nf_seconds")
    )
    per_dataset = (
        datasets.set_index("dataset_id")[["n_rows", "n_features", "n_classes"]]
        .join(timing)
        .join(nf_time)
        .reset_index()
    )
    per_dataset["proxy"] = [
        cost_proxy(r, f, k)
        for r, f, k in per_dataset[["n_rows", "n_features", "n_classes"]].to_numpy()
    ]
    report["timing_per_dataset"] = _records(per_dataset)
    if corpus_meta is not None:
        report["projection"] = project_compute(per_dataset, corpus_meta, 55 * 5, 55)
    predictions = lodo_predictions(runs, pilot_methods())
    report["lodo_pilot"] = _records(lodo_metrics(predictions))
    baseline = store.read("baseline_d_run")
    if len(baseline):
        report["baseline_d"] = baseline_d_comparison(baseline, runs, predictions)
    return report


def baseline_d_comparison(
    baseline: pd.DataFrame, runs: pd.DataFrame, predictions: pd.DataFrame
) -> dict[str, Any]:
    """Baseline (d) dibanding meta-model LODO pada subset run yang sama (pratinjau H1b).

    MAE per dataset (BR-85) dan detik per estimasi. Detik meta-model hanya prediksi; profil
    dibutuhkan kedua metode, sehingga tidak dihitung di sisi mana pun.
    """
    actual = runs.set_index("run_id")["delta_auc"]
    meta = predictions[predictions["method"] == "metamodel"].set_index("run_id")["predicted"]
    frame = baseline.set_index("run_id")
    frame = frame.assign(actual=actual.reindex(frame.index), meta=meta.reindex(frame.index))
    rows = []
    for dataset_id, group in frame.groupby("dataset_id"):
        rows.append(
            {
                "dataset_id": int(dataset_id),
                "n": len(group),
                "mae_d_linear": float((group["delta_linear"] - group["actual"]).abs().mean()),
                "mae_d_quadratic": float((group["delta_quadratic"] - group["actual"]).abs().mean()),
                "mae_metamodel": float((group["meta"] - group["actual"]).abs().mean()),
                "seconds_d_median": float(group["seconds"].median()),
            }
        )
    per_dataset = pd.DataFrame(rows)
    diff = per_dataset["mae_metamodel"] - per_dataset["mae_d_linear"]
    return {
        "per_dataset": _records(per_dataset),
        "median_mae_difference_meta_minus_d": float(diff.median()),
        "seconds_d_median": float(frame["seconds"].median()),
    }


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return json.loads(frame.to_json(orient="records"))  # type: ignore[no-any-return]


def corpus_meta_from_cache(
    corpus_dir: Path, dataset_ids: Sequence[int] | None = None
) -> pd.DataFrame:
    """n_rows, n_features, n_classes dataset korpus yang lolos saringan, dari `meta.json`."""
    rows = []
    for folder in sorted(Path(corpus_dir).iterdir()):
        meta_path = folder / "meta.json"
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta["passed"] and (dataset_ids is None or meta["dataset_id"] in dataset_ids):
            rows.append({k: meta[k] for k in ("dataset_id", "n_rows", "n_features", "n_classes")})
    return pd.DataFrame(rows)


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m ceteris.evaluate")
    sub = parser.add_subparsers(dest="command", required=True)
    e0 = sub.add_parser("e0", help="ringkasan pilot E0 dari run store")
    e0.add_argument("--store", type=Path, required=True)
    e0.add_argument("--corpus", type=Path, help="cache korpus penuh untuk proyeksi komputasi")
    e0.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    corpus = corpus_meta_from_cache(args.corpus) if args.corpus else None
    report = e0_report(args.store, corpus)
    args.out.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
