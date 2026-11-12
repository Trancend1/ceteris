"""ceteris.evaluate: ringkasan pilot E0 dan evaluasi LODO pilot.

Fitur: F-S11 (versi pilot; LODO bersarang penuh di Phase 4), F-S06. Jalur: riset saja (AC-3).
Aturan: BR-04, BR-05, BR-81, BR-85 (unit analisis dataset).

Semua angka laporan E0 dibaca dari run store (AGENTS.md bagian 5), bukan diketik manual.
Perintah: `python -m ceteris.evaluate e0 --store runs/e0 --out runs/e0/report.json`.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, get_args

import numpy as np
import pandas as pd

from ceteris.dqprofile import NoiseFloorStatistic, noise_floor_value
from ceteris.metamodel import lodo_predictions, pilot_methods, tune
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


# --- LODO bersarang (F-S11, analysis-plan.md bagian 2, BR-81) ---

CALIBRATION_FRAC = 0.2
OOD_K = 5
RELATIVE = "delta_auc_relative"


def inner_split(dataset_ids: Sequence[int], test_id: int) -> tuple[list[int], list[int]]:
    """Dataset latih fold dibagi per dataset: proper-train (≈ 80%) dan kalibrasi (≈ 20%).

    Seed tetap per fold (`derive_seed("lodo_inner", dataset uji)`). Dataset uji tidak pernah
    masuk ke salah satunya (BR-81).
    """
    from ceteris.seeding import derive_seed

    ids = sorted({int(d) for d in dataset_ids} - {int(test_id)})
    if len(ids) < 2:
        raise ValueError("LODO bersarang butuh minimal dua dataset latih per fold")
    n_cal = min(max(1, round(CALIBRATION_FRAC * len(ids))), len(ids) - 1)
    order = np.random.default_rng(derive_seed("lodo_inner", int(test_id))).permutation(len(ids))
    shuffled = [ids[i] for i in order]
    return sorted(shuffled[n_cal:]), sorted(shuffled[:n_cal])


@dataclass(frozen=True)
class FoldResult:
    """Hasil satu fold luar: prediksi (kolom `lodo_result`), potensi pemulihan, waktu prediksi."""

    predictions: pd.DataFrame
    recovery: pd.DataFrame
    predict_seconds_per_estimate: float


def _fold_methods(proper: pd.DataFrame) -> list[tuple[Any, dict[str, Any]]]:
    from ceteris.dqprofile import FEATURES
    from ceteris.metamodel import (
        CONTEXT_FEATURES,
        PROBE_FEATURES,
        CompositeScoreBaseline,
        LightGBMMethod,
        LinearMethod,
        MeanBaseline,
    )

    meta_params = tune(proper, FEATURES)
    c_features = CONTEXT_FEATURES + PROBE_FEATURES
    c_params = tune(proper, c_features)
    return [
        (LightGBMMethod("metamodel", FEATURES, params=meta_params), meta_params),
        (MeanBaseline(), {}),
        (CompositeScoreBaseline(), {}),
        (LightGBMMethod("baseline_c_metafeatures", c_features, params=c_params), c_params),
        (LinearMethod(), {}),
    ]


def nested_lodo_fold(runs: pd.DataFrame, test_id: int, relative: bool = True) -> FoldResult:
    """Satu fold luar LODO bersarang (analysis-plan.md bagian 2).

    Dataset uji tidak dipakai melatih, men-tuning, atau mengkalibrasi apa pun (BR-81): semua
    metode dilatih di proper-train, kuantil conformal berbobot dataset dari residu dataset
    kalibrasi (BR-22), dan skor OOD terhadap profil proper-train (BR-24).
    """
    import time
    from datetime import UTC, datetime

    from ceteris.dqprofile import FEATURES
    from ceteris.metamodel import LightGBMMethod, feature_frame
    from ceteris.recovery import recovery_potentials
    from ceteris.uncertainty import (
        conformal_interval,
        fit_ood_reference,
        weighted_conformal_quantile,
    )

    proper_ids, calib_ids = inner_split(runs["dataset_id"].unique().tolist(), test_id)
    test = runs[runs["dataset_id"] == test_id]
    proper = runs[runs["dataset_id"].isin(proper_ids)]
    calib = runs[runs["dataset_id"].isin(calib_ids)]
    if test.empty:
        raise ValueError(f"dataset uji {test_id} tidak punya run")
    reference = fit_ood_reference(feature_frame(proper, FEATURES), FEATURES, OOD_K)
    ood = reference.scores(feature_frame(test, FEATURES).to_numpy("float64"))
    now = datetime.now(UTC).isoformat()
    frames: list[pd.DataFrame] = []
    meta_method: Any = None
    predict_seconds = float("nan")

    def _frame(
        method: Any,
        params: dict[str, Any],
        target: str,
        subset_calib: pd.DataFrame,
        subset_test: pd.DataFrame,
        subset_ood: np.ndarray,
    ) -> pd.DataFrame:
        residual = np.abs(subset_calib[target].to_numpy("float64") - method.predict(subset_calib))
        q = weighted_conformal_quantile(residual.tolist(), subset_calib["dataset_id"].tolist())
        predicted = method.predict(subset_test)
        bounds = [conformal_interval(float(p), q) for p in predicted]
        return pd.DataFrame(
            {
                "run_id": subset_test["run_id"].to_numpy(),
                "dataset_id": int(test_id),
                "method": method.name,
                "actual": subset_test[target].to_numpy("float64"),
                "predicted": predicted.astype("float64"),
                "lo": [b[0] for b in bounds],
                "hi": [b[1] for b in bounds],
                "ood_score": subset_ood,
                "fold_params_json": json.dumps(params, sort_keys=True),
                "calibration_datasets_json": json.dumps(calib_ids),
                "created_at": now,
            }
        )

    for method, params in _fold_methods(proper):
        method.fit(proper)
        if method.name == "metamodel":
            meta_method = method
            start = time.perf_counter()
            for i in range(min(len(test), 50)):
                method.predict(test.iloc[[i]])
            predict_seconds = (time.perf_counter() - start) / min(len(test), 50)
        frames.append(_frame(method, params, "delta_auc", calib, test, ood))
    if relative:
        finite = runs[np.isfinite(runs[RELATIVE].to_numpy("float64"))]
        rel_proper = finite[finite["dataset_id"].isin(proper_ids)]
        rel_calib = finite[finite["dataset_id"].isin(calib_ids)]
        rel_test_mask = np.isfinite(test[RELATIVE].to_numpy("float64"))
        rel_params = tune(rel_proper, FEATURES, target=RELATIVE)
        rel = LightGBMMethod("metamodel_relative", FEATURES, params=rel_params, target=RELATIVE)
        rel.fit(rel_proper)
        frames.append(
            _frame(rel, rel_params, RELATIVE, rel_calib, test[rel_test_mask], ood[rel_test_mask])
        )
    recovery_rows: list[dict[str, Any]] = []
    mixtures = test[test["kinds"].str.contains(",")]
    if meta_method is not None and not mixtures.empty:
        booster = meta_method.booster

        def predict(features: Any) -> float:
            row = pd.DataFrame([{name: float(features[name]) for name in FEATURES}])
            return float(booster.predict(row)[0])

        for run in mixtures.itertuples(index=False):
            profile = {name: float(getattr(run, f"p_{name}")) for name in FEATURES}
            for finding, potential in recovery_potentials(profile, predict).items():
                recovery_rows.append(
                    {
                        "run_id": run.run_id,
                        "dataset_id": int(test_id),
                        "finding": finding,
                        "potential": potential,
                    }
                )
    return FoldResult(
        predictions=pd.concat(frames, ignore_index=True),
        recovery=pd.DataFrame(
            recovery_rows, columns=["run_id", "dataset_id", "finding", "potential"]
        ),
        predict_seconds_per_estimate=predict_seconds,
    )


def _fold_worker(args: tuple[str, int, bool]) -> tuple[int, FoldResult]:
    store_root, test_id, relative = args
    runs = load_runs(RunStore(Path(store_root)))
    return test_id, nested_lodo_fold(runs, test_id, relative)


def load_runs(store: RunStore) -> pd.DataFrame:
    """Run korupsi yang dievaluasi, terurut stabil (deterministik)."""
    runs = store.read("corruption_run")
    return runs.sort_values("run_id").reset_index(drop=True)


def run_nested_lodo(store_root: Path, workers: int = 1, relative: bool = True) -> pd.DataFrame:
    """Jalankan semua fold luar, tulis `lodo_result`, kembalikan ringkasan per fold.

    Potensi pemulihan LODO (H2b) ditulis ke `<store>/lodo_recovery.parquet`.
    """
    from concurrent.futures import ProcessPoolExecutor
    from multiprocessing import get_context

    store = RunStore(store_root)
    runs = load_runs(store)
    ids = sorted(int(d) for d in runs["dataset_id"].unique())
    jobs = [(str(store_root), d, relative) for d in ids]
    results: dict[int, FoldResult] = {}
    if workers > 1:
        with ProcessPoolExecutor(workers, mp_context=get_context("spawn")) as pool:
            for test_id, result in pool.map(_fold_worker, jobs):
                results[test_id] = result
                print(f"fold {test_id} selesai", flush=True)
    else:
        for job in jobs:
            test_id, result = _fold_worker(job)
            results[test_id] = result
            print(f"fold {test_id} selesai", flush=True)
    summary = []
    for test_id in ids:
        result = results[test_id]
        for method, group in result.predictions.groupby("method"):
            store.write_lodo_result(f"{method}__{test_id}", group.reset_index(drop=True))
        summary.append(
            {"dataset_id": test_id, "predict_seconds": result.predict_seconds_per_estimate}
        )
    recovery = pd.concat([results[d].recovery for d in ids], ignore_index=True)
    recovery.to_parquet(Path(store_root) / "lodo_recovery.parquet", index=False)
    frame = pd.DataFrame(summary)
    frame.to_parquet(Path(store_root) / "lodo_timing.parquet", index=False)
    return frame


# --- analisis hipotesis H1–H5 (analysis-plan.md bagian 4) ---

ALPHA = 0.05
N_BOOTSTRAP = 10_000
SINGLE_KINDS = (
    "label_uniform",
    "label_class_conditional",
    "duplicate_conflict",
    "missing_mcar",
    "missing_mar",
    "outlier",
    "duplicate_exact",
)


def bootstrap_ci(
    values: Sequence[float] | np.ndarray,
    statistic: Any = np.median,
    n: int = N_BOOTSTRAP,
) -> tuple[float, float]:
    """CI persentil 95%, resample atas dataset, seed `derive_seed("analysis", "bootstrap")`."""
    from ceteris.seeding import derive_seed

    data = np.asarray(values, dtype="float64")
    data = data[np.isfinite(data)]
    if data.size == 0:
        return float("nan"), float("nan")
    rng = np.random.default_rng(derive_seed("analysis", "bootstrap"))
    draws = rng.integers(0, data.size, size=(n, data.size))
    stats = np.apply_along_axis(statistic, 1, data[draws])
    return float(np.percentile(stats, 2.5)), float(np.percentile(stats, 97.5))


def per_dataset_metrics(pred: pd.DataFrame, threshold: float = 0.01) -> pd.DataFrame:
    """Ukuran per (metode, dataset): MAE, RMSE, bias, Spearman, coverage, lebar, MAE material."""
    from scipy.stats import spearmanr

    rows: list[dict[str, Any]] = []
    for (method, dataset_id), g in pred.groupby(["method", "dataset_id"]):
        err = g["predicted"] - g["actual"]
        material = g["actual"] > threshold
        rho = (
            float(spearmanr(g["predicted"], g["actual"]).statistic)
            if g["predicted"].nunique() > 1 and g["actual"].nunique() > 1
            else float("nan")
        )
        rows.append(
            {
                "method": method,
                "dataset_id": int(dataset_id),
                "n": len(g),
                "mae": float(err.abs().mean()),
                "rmse": float(np.sqrt(np.mean(np.square(err)))),
                "bias": float(err.mean()),
                "spearman": rho,
                "coverage": float(((g["actual"] >= g["lo"]) & (g["actual"] <= g["hi"])).mean()),
                "width": float((g["hi"] - g["lo"]).mean()),
                "mae_material": float(err[material].abs().mean()) if material.any() else np.nan,
            }
        )
    return pd.DataFrame(rows)


def _holm(pvalues: Sequence[float]) -> list[float]:
    from statsmodels.stats.multitest import multipletests

    return [float(p) for p in multipletests(list(pvalues), method="holm")[1]]


def h1a(per_ds: pd.DataFrame) -> dict[str, Any]:
    """H1a: Wilcoxon satu sisi MAE meta-model < MAE baseline (a)–(c), Holm atas 3 (P9)."""
    from scipy.stats import wilcoxon

    meta = per_ds[per_ds["method"] == "metamodel"].set_index("dataset_id")["mae"]
    baselines = ["baseline_a_mean", "baseline_b_composite", "baseline_c_metafeatures"]
    raw: list[float] = []
    out: dict[str, Any] = {"comparisons": []}
    for name in baselines:
        base = per_ds[per_ds["method"] == name].set_index("dataset_id")["mae"]
        diff = (meta - base.reindex(meta.index)).dropna()
        p = float(wilcoxon(diff, alternative="less").pvalue)
        raw.append(p)
        out["comparisons"].append(
            {
                "baseline": name,
                "n_datasets": int(diff.size),
                "median_diff": float(diff.median()),
                "ci95": bootstrap_ci(diff.to_numpy()),
                "wins": int((diff < 0).sum()),
                "p": p,
            }
        )
    for item, p_holm in zip(out["comparisons"], _holm(raw), strict=True):
        item["p_holm"] = p_holm
        item["passed"] = bool(p_holm < ALPHA and item["median_diff"] < 0 and item["ci95"][1] < 0)
    out["passed"] = all(item["passed"] for item in out["comparisons"])
    return out


def h1b(pred: pd.DataFrame, baseline_d: pd.DataFrame, predict_seconds: float) -> dict[str, Any]:
    """H1b: batas atas CI 95% median selisih MAE (meta − d) < 0,005 dan biaya ≥ 10× lebih murah."""
    meta = pred[pred["method"] == "metamodel"].set_index("run_id")
    frame = baseline_d.set_index("run_id").join(meta[["actual", "predicted"]], how="inner")
    rows = []
    for dataset_id, g in frame.groupby("dataset_id"):
        rows.append(
            {
                "dataset_id": int(dataset_id),
                "mae_meta": float((g["predicted"] - g["actual"]).abs().mean()),
                "mae_d": float((g["delta_linear"] - g["actual"]).abs().mean()),
                "mae_d_quadratic": float((g["delta_quadratic"] - g["actual"]).abs().mean()),
            }
        )
    per_ds = pd.DataFrame(rows)
    diff = per_ds["mae_meta"] - per_ds["mae_d"]
    ci = bootstrap_ci(diff.to_numpy())
    d_seconds = float(frame["seconds"].median())
    ratio = d_seconds / predict_seconds if predict_seconds > 0 else float("inf")
    return {
        "n_datasets": len(per_ds),
        "median_diff": float(diff.median()),
        "ci95": ci,
        "seconds_d_median": d_seconds,
        "seconds_meta_per_estimate": predict_seconds,
        "cost_ratio": ratio,
        "passed": bool(ci[1] < 0.005 and ratio >= 10.0),
        "per_dataset": _records(per_ds),
    }


def dose_response_at(runs: pd.DataFrame, at: float = 0.10) -> pd.DataFrame:
    """ΔAUC per (dataset, jenis tunggal) pada `affected_row_frac` = `at` (H2, BR-82).

    Kurva per varian: median antar-seed per level (titik (0, 0) = tanpa korupsi), lalu interpolasi
    linear; varian kolom missing (importance tinggi dan rendah) dirata-ratakan. Di luar rentang
    level yang diukur = NaN (tidak diekstrapolasi).
    """
    singles = runs[runs["nominal_level"].notna()].copy()
    singles["variant"] = singles["spec_json"].map(_variant_key)
    rows = []
    for (dataset_id, kind), group in singles.groupby(["dataset_id", "kinds"]):
        values = []
        for _, variant in group.groupby("variant"):
            curve = (
                variant.groupby("nominal_level")[["affected_row_frac", "delta_auc"]]
                .median()
                .sort_values("affected_row_frac")
            )
            x = np.concatenate([[0.0], curve["affected_row_frac"].to_numpy("float64")])
            y = np.concatenate([[0.0], curve["delta_auc"].to_numpy("float64")])
            values.append(float(np.interp(at, x, y)) if at <= x.max() else np.nan)
        rows.append(
            {
                "dataset_id": int(dataset_id),
                "kind": kind,
                "delta_at": float(np.nanmean(values)) if np.isfinite(values).any() else np.nan,
            }
        )
    return pd.DataFrame(rows)


def _variant_key(spec_json: str) -> str:
    spec = json.loads(spec_json)[0]
    return str(spec.get("columns", ""))


def h2(runs: pd.DataFrame) -> dict[str, Any]:
    """H2: Friedman antar-jenis (blok = dataset), post-hoc Wilcoxon berpasangan dengan Holm."""
    from itertools import combinations

    from scipy.stats import friedmanchisquare, wilcoxon

    table = dose_response_at(runs).pivot(index="dataset_id", columns="kind", values="delta_at")
    kinds = [k for k in SINGLE_KINDS if k in table.columns]
    complete = table[kinds].dropna()
    medians = complete.median().sort_values(ascending=False)
    stat = friedmanchisquare(*[complete[k] for k in kinds])
    pairs = list(combinations(kinds, 2))
    raw = []
    for a, b in pairs:
        diff = complete[a] - complete[b]
        raw.append(float(wilcoxon(diff).pvalue) if (diff != 0).any() else 1.0)
    holm = _holm(raw)
    posthoc: list[dict[str, Any]] = [
        {"a": a, "b": b, "p": p, "p_holm": q} for (a, b), p, q in zip(pairs, raw, holm, strict=True)
    ]
    top, bottom = str(medians.index[0]), str(medians.index[-1])
    key = next((item for item in posthoc if {item["a"], item["b"]} == {top, "missing_mcar"}), None)
    passed = bool(
        top.startswith("label")
        and bottom == "missing_mcar"
        and key is not None
        and float(key["p_holm"]) < ALPHA
    )
    return {
        "n_datasets": len(complete),
        "excluded_datasets": sorted(int(d) for d in set(table.index) - set(complete.index)),
        "median_delta_at_0_10": {k: float(v) for k, v in medians.items()},
        "friedman_statistic": float(stat.statistic),
        "friedman_p": float(stat.pvalue),
        "posthoc": posthoc,
        "top": top,
        "bottom": bottom,
        "passed": passed,
    }


def h2b(recovery: pd.DataFrame, ablation: pd.DataFrame, runs: pd.DataFrame) -> dict[str, Any]:
    """H2b (eksploratif): τ urutan potensi vs τ urutan volume terhadap keuntungan AUC nyata."""
    from scipy.stats import kendalltau, wilcoxon

    from ceteris.dqprofile import FEATURES
    from ceteris.recovery import finding_volumes

    profiles = runs.set_index("run_id")
    potentials = recovery.set_index(["run_id", "finding"])["potential"]
    rows = []
    for run_id, group in ablation.groupby("run_id"):
        if run_id not in profiles.index:
            continue
        profile = {name: float(profiles.at[run_id, f"p_{name}"]) for name in FEATURES}
        volumes = finding_volumes(profile, float(group["missing_row_frac_full"].iloc[0]))
        gains = group.set_index("finding")["gain"]
        pot = [float(potentials.get((run_id, f), 0.0)) for f in gains.index]
        vol = [volumes[f] for f in gains.index]
        tau_p = kendalltau(pot, gains.to_numpy()).statistic
        tau_v = kendalltau(vol, gains.to_numpy()).statistic
        rows.append(
            {
                "run_id": run_id,
                "dataset_id": int(group["dataset_id"].iloc[0]),
                "tau_potential": float(tau_p),
                "tau_volume": float(tau_v),
            }
        )
    frame = pd.DataFrame(rows)
    per_ds = frame.groupby("dataset_id")[["tau_potential", "tau_volume"]].mean().dropna()
    diff = per_ds["tau_potential"] - per_ds["tau_volume"]
    p = float(wilcoxon(diff, alternative="greater").pvalue) if (diff != 0).any() else 1.0
    return {
        "label": "eksploratif",
        "n_runs": len(frame),
        "n_datasets": len(per_ds),
        "tau_potential_median": float(per_ds["tau_potential"].median()),
        "tau_volume_median": float(per_ds["tau_volume"].median()),
        "median_diff": float(diff.median()),
        "ci95": bootstrap_ci(diff.to_numpy()),
        "p": p,
        "passed": bool(p < ALPHA and diff.median() > 0),
    }


def h3(per_ds: pd.DataFrame, method: str = "metamodel") -> dict[str, Any]:
    """H3: proporsi dataset dengan coverage 85–95%, CI Clopper–Pearson; kriteria ≥ 80%."""
    from statsmodels.stats.proportion import proportion_confint

    sel = per_ds[per_ds["method"] == method]
    inside = sel["coverage"].between(0.85, 0.95)
    k, n = int(inside.sum()), len(sel)
    lo, hi = proportion_confint(k, n, alpha=ALPHA, method="beta")
    return {
        "n_datasets": n,
        "in_range": k,
        "share": k / n if n else float("nan"),
        "ci95": (float(lo), float(hi)),
        "coverage_median": float(sel["coverage"].median()),
        "coverage_min": float(sel["coverage"].min()),
        "coverage_max": float(sel["coverage"].max()),
        "width_median": float(sel["width"].median()),
        "below_range": sorted(int(d) for d in sel.loc[sel["coverage"] < 0.85, "dataset_id"]),
        "above_range": sorted(int(d) for d in sel.loc[sel["coverage"] > 0.95, "dataset_id"]),
        "passed": bool(n and k / n >= 0.80),
    }


def h4(pred: pd.DataFrame, method: str = "metamodel") -> dict[str, Any]:
    """H4: Spearman skor OOD vs galat absolut; CI 95% bootstrap dengan resample dataset."""
    from scipy.stats import spearmanr

    from ceteris.seeding import derive_seed

    sel = pred[pred["method"] == method].assign(
        abs_error=lambda f: (f["predicted"] - f["actual"]).abs()
    )
    rho = float(spearmanr(sel["ood_score"], sel["abs_error"]).statistic)
    groups = [g for _, g in sel.groupby("dataset_id")]
    rng = np.random.default_rng(derive_seed("analysis", "bootstrap"))
    stats = []
    for _ in range(N_BOOTSTRAP // 10):  # resample dataset; 1.000 cukup untuk CI rho gabungan
        pick = rng.integers(0, len(groups), size=len(groups))
        sample = pd.concat([groups[i] for i in pick])
        stats.append(spearmanr(sample["ood_score"], sample["abs_error"]).statistic)
    lo, hi = float(np.nanpercentile(stats, 2.5)), float(np.nanpercentile(stats, 97.5))
    return {
        "n_predictions": len(sel),
        "spearman": rho,
        "ci95": (lo, hi),
        "n_bootstrap": len(stats),
        "passed": bool(lo > 0),
    }


def noise_floors(nf: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Noise floor terukur per dataset (10 seed) dan estimasi per run (5 seed), statistik G2-1."""
    from ceteris.dqprofile import noise_floor_value

    measured = (
        nf[nf["kind"] == "measured"]
        .sort_values("seed_index")
        .groupby("dataset_id")["auc"]
        .apply(lambda a: noise_floor_value(a.to_numpy("float64")[:10], "pairwise_mean"))
    )
    estimated = (
        nf[nf["kind"] == "estimated"]
        .sort_values("seed_index")
        .groupby("source_run_id")["auc"]
        .apply(lambda a: noise_floor_value(a.to_numpy("float64")[:5], "pairwise_mean"))
    )
    return measured, estimated


def _status(lo: float, hi: float, threshold: float) -> str:
    if lo > threshold:
        return "material"
    if hi < threshold:
        return "tidak_material"
    return "tidak_yakin"


def h5(nf: pd.DataFrame, pred: pd.DataFrame, runs: pd.DataFrame) -> dict[str, Any]:
    """H5: selisih dan bias noise floor estimasi vs terukur; kappa status (semua dan subset P5)."""
    from sklearn.metrics import cohen_kappa_score

    measured, estimated = noise_floors(nf)
    dataset_of = runs.set_index("run_id")["dataset_id"]
    est = estimated.to_frame("estimated")
    est["dataset_id"] = dataset_of.reindex(est.index).to_numpy()
    est = est.dropna(subset=["dataset_id"])
    est["measured"] = est["dataset_id"].map(measured)
    est["bias"] = est["estimated"] - est["measured"]
    per_ds = est.groupby("dataset_id").agg(
        bias=("bias", "median"), abs_diff=("bias", lambda b: float(np.median(np.abs(b))))
    )
    meta = pred[pred["method"] == "metamodel"].set_index("run_id")
    status = est.join(meta[["lo", "hi"]], how="inner")
    status["s_est"] = [
        _status(lo, hi, max(0.01, e)) for lo, hi, e in status[["lo", "hi", "estimated"]].to_numpy()
    ]
    status["s_meas"] = [
        _status(lo, hi, max(0.01, m)) for lo, hi, m in status[["lo", "hi", "measured"]].to_numpy()
    ]
    n_subset = max(8, int(np.ceil(len(measured) / 4)))
    subset = set(measured.sort_values(ascending=False).index[:n_subset].tolist())

    def _block(ids: set[int] | None) -> dict[str, Any]:
        d = per_ds if ids is None else per_ds[per_ds.index.isin(ids)]
        s = status if ids is None else status[status["dataset_id"].isin(ids)]
        agree = float((s["s_est"] == s["s_meas"]).mean()) if len(s) else float("nan")
        kappa = (
            float(cohen_kappa_score(s["s_est"], s["s_meas"]))
            if len(set(s["s_est"]) | set(s["s_meas"])) > 1
            else float("nan")
        )
        abs_med = float(d["abs_diff"].median())
        ci = bootstrap_ci(d["abs_diff"].to_numpy())
        return {
            "n_datasets": len(d),
            "n_runs": len(s),
            "abs_diff_median": abs_med,
            "abs_diff_ci95": ci,
            "bias_median": float(d["bias"].median()),
            "bias_ci95": bootstrap_ci(d["bias"].to_numpy()),
            "status_agreement": agree,
            "kappa": kappa,
            "passed": bool(abs_med <= 0.005 and np.isfinite(kappa) and kappa >= 0.6),
        }

    whole, near = _block(None), _block(subset)
    return {
        "all": whole,
        "near_0_01": {**near, "datasets": sorted(int(d) for d in subset)},
        "measured_max": float(measured.max()),
        "measured_above_0_01": sorted(int(d) for d in measured[measured > 0.01].index),
        "passed": bool(whole["passed"] and near["passed"]),
    }


def accuracy_by_kind(
    pred: pd.DataFrame, runs: pd.DataFrame, method: str = "metamodel"
) -> pd.DataFrame:
    """Laporan akurasi per jenis korupsi: MAE, coverage, Spearman (median per dataset, BR-85)."""
    from scipy.stats import spearmanr

    family = runs.set_index("run_id")["kinds"].map(corruption_family)
    sel = pred[pred["method"] == method].assign(family=lambda f: f["run_id"].map(family))
    rows = []
    for (fam, dataset_id), g in sel.groupby(["family", "dataset_id"]):
        rows.append(
            {
                "family": fam,
                "dataset_id": int(dataset_id),
                "mae": float((g["predicted"] - g["actual"]).abs().mean()),
                "coverage": float(((g["actual"] >= g["lo"]) & (g["actual"] <= g["hi"])).mean()),
                "spearman": float(spearmanr(g["predicted"], g["actual"]).statistic)
                if g["actual"].nunique() > 1 and g["predicted"].nunique() > 1
                else np.nan,
            }
        )
    frame = pd.DataFrame(rows)
    return (
        frame.groupby("family")
        .agg(
            mae_median=("mae", "median"),
            coverage_median=("coverage", "median"),
            coverage_min=("coverage", "min"),
            spearman_median=("spearman", "median"),
            n_datasets=("dataset_id", "nunique"),
        )
        .reset_index()
    )


def ood_bins(pred: pd.DataFrame, method: str = "metamodel") -> pd.DataFrame:
    """Galat dan coverage per desil skor OOD LODO: dasar keputusan ambang OOD (hal terbuka #3)."""
    sel = pred[pred["method"] == method].copy()
    sel["abs_error"] = (sel["predicted"] - sel["actual"]).abs()
    sel["covered"] = (sel["actual"] >= sel["lo"]) & (sel["actual"] <= sel["hi"])
    sel["decile"] = pd.qcut(sel["ood_score"], 10, labels=False, duplicates="drop")
    return (
        sel.groupby("decile")
        .agg(
            ood_min=("ood_score", "min"),
            ood_max=("ood_score", "max"),
            mae=("abs_error", "mean"),
            coverage=("covered", "mean"),
            n=("run_id", "size"),
        )
        .reset_index()
    )


def status_quality(pred: pd.DataFrame, threshold: float = 0.01) -> dict[str, Any]:
    """Precision dan recall status material (T = 0,01, OOD tidak diperhitungkan)."""
    sel = pred[pred["method"] == "metamodel"]
    predicted = sel["lo"] > threshold
    actual = sel["actual"] > threshold
    tp = int((predicted & actual).sum())
    return {
        "precision_material": tp / int(predicted.sum()) if predicted.any() else float("nan"),
        "recall_material": tp / int(actual.sum()) if actual.any() else float("nan"),
        "share_tidak_yakin": float(((sel["lo"] <= threshold) & (sel["hi"] >= threshold)).mean()),
    }


def e1_report(store_root: Path) -> dict[str, Any]:
    """Laporan E1: provenance, H1–H5, laporan akurasi, dan dasar keputusan G3 (dari run store)."""
    store = RunStore(store_root)
    runs = load_runs(store)
    pred = store.read("lodo_result")
    log = store.read("run_log")
    nf = store.read("noise_floor")
    timing = pd.read_parquet(Path(store_root) / "lodo_timing.parquet")
    recovery = pd.read_parquet(Path(store_root) / "lodo_recovery.parquet")
    ablation = store.read("ablation_run")
    baseline = store.read("baseline_d_run")
    measured_nf, _ = noise_floors(nf)
    per_ds = per_dataset_metrics(pred[pred["method"] != "metamodel_relative"])
    failed = log[(log["status"] == "failed") & ~log["run_id"].isin(runs["run_id"])]
    ablation_check = ablation.merge(runs[["run_id", "auc_dirty"]], on="run_id")
    method_summary = (
        per_ds.groupby("method")[["mae", "rmse", "bias", "spearman", "coverage", "width"]]
        .median()
        .reset_index()
    )
    relative = per_dataset_metrics(pred[pred["method"] == "metamodel_relative"])
    return {
        "label": "eksperimental (BR-35): angka mode learned sebelum G3",
        "n_runs": len(runs),
        "n_datasets": int(runs["dataset_id"].nunique()),
        "n_failed_runs": int(failed["run_id"].nunique()),
        "failed_errors": failed.drop_duplicates("run_id")["error"].value_counts().to_dict(),
        "git_commits": sorted(log["git_commit"].unique().tolist()),
        "git_dirty_rows": int(log["git_dirty"].sum()),
        "ablation_auc_full_max_mismatch": float(
            (ablation_check["auc_full"] - ablation_check["auc_dirty"]).abs().max()
        )
        if len(ablation_check)
        else None,
        "methods": _records(method_summary),
        "relative_metamodel": _records(
            relative[["mae", "spearman", "coverage", "width"]].median().to_frame().T
        ),
        "h1a": h1a(per_ds),
        "h1b": h1b(pred, baseline, float(timing["predict_seconds"].median())),
        "h2": h2(runs),
        "h2b": h2b(recovery, ablation, runs) if len(ablation) else None,
        "h3": h3(per_ds),
        "h4": h4(pred),
        "h5": h5(nf, pred, runs),
        "accuracy_by_kind": _records(accuracy_by_kind(pred, runs)),
        "ood_bins": _records(ood_bins(pred)),
        "status_quality": status_quality(pred),
        "noise_floor_measured": {str(k): float(v) for k, v in measured_nf.items()},
        "per_dataset": _records(per_ds[per_ds["method"] == "metamodel"]),
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
    lodo = sub.add_parser("lodo", help="LODO bersarang (F-S11) pada run store, tulis lodo_result")
    lodo.add_argument("--store", type=Path, required=True)
    lodo.add_argument("--workers", type=int, default=1)
    e1 = sub.add_parser("e1", help="laporan E1: H1–H5 dan laporan akurasi dari run store")
    e1.add_argument("--store", type=Path, required=True)
    e1.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "lodo":
        print(run_nested_lodo(args.store, args.workers).to_string(), flush=True)
        return 0
    if args.command == "e1":
        report = e1_report(args.store)
    else:
        corpus = corpus_meta_from_cache(args.corpus) if args.corpus else None
        report = e0_report(args.store, corpus)
    args.out.write_text(
        json.dumps(report, indent=1, ensure_ascii=False, default=float), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
