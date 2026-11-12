"""ceteris.experiment: orkestrasi satu run riset (korpus → korupsi → profil → ΔAUC → run store).

Fitur: F-S01–F-S05, F-S07 (docs/product.md). Jalur: riset saja. Modul ini mengimpor `corpus`
dan `corrupt`, sehingga jalur scan tidak boleh mengimpornya (AC-3).
Aturan: BR-01, BR-20 (profil dari data kotor saja), BR-80 (hash partisi uji sebelum dan
sesudah), BR-82, BR-84; AC-11 (profil dan ΔAUC di satu tabel `corruption_run`).
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field

from ceteris.corpus import CorpusError, PreparedDataset, frame_sha256
from ceteris.corrupt import (
    AnySpec,
    CorruptionContext,
    CorruptionResult,
    LabelUniform,
    build_context,
    corrupt,
    parse_spec,
)
from ceteris.dqprofile import (
    FEATURES,
    PROFILE_SCHEMA_VERSION,
    PROFILE_SEED,
    ProfileConfig,
    compute_profile,
    estimate_noise_floor,
    label_noise_rate,
    noise_floor_seeds,
    prepare_input,
    single_feature_aucs,
)
from ceteris.seeding import derive_seed, run_seed, sub_seed
from ceteris.store import (
    REPO_ROOT,
    Provenance,
    RecordExistsError,
    RunStore,
    provenance,
    provenance_fields,
)
from ceteris.train import LearnerSpec, measure_delta_auc, measure_noise_floor, oof_predict_proba


class PartitionChangedError(RuntimeError):
    """Partisi uji berubah selama run (pelanggaran BR-80)."""


def spec_json(specs: Sequence[AnySpec]) -> str:
    """Serialisasi kanonik daftar korupsi; urutan masukan tidak berpengaruh (BR-83)."""
    dumped = [s.model_dump() for s in specs]
    dumped.sort(key=lambda d: json.dumps(d, sort_keys=True))
    return json.dumps(dumped, sort_keys=True)


def learner_spec_sha256(learner: LearnerSpec) -> str:
    """Hash seluruh isi spesifikasi learner (versi, ronde, dan parameter)."""
    payload = json.dumps(learner.model_dump(), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def config_id_for(specs: Sequence[AnySpec], learner: LearnerSpec) -> str:
    """`config_id` deterministik dari isi korupsi dan seluruh isi spesifikasi learner.

    `config_id` menurunkan seed run (BR-84), jadi hanya korupsi dan learner yang masuk: mengubah
    konfigurasi profil tidak boleh mengacak ulang korupsi dan ΔAUC.
    """
    payload = json.dumps(
        {"corruption": json.loads(spec_json(specs)), "learner": learner_spec_sha256(learner)},
        sort_keys=True,
    )
    return "cfg_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def profile_config_id(config: ProfileConfig) -> str:
    """ID konfigurasi profil (skema dan parameter), dicatat terpisah dari `config_id`."""
    payload = json.dumps(
        {"schema": PROFILE_SCHEMA_VERSION, "config": config.model_dump()}, sort_keys=True
    )
    return "prf_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


_CONTEXTS: dict[tuple[int, str, str], CorruptionContext] = {}


def context_for(prepared: PreparedDataset, learner: LearnerSpec) -> CorruptionContext:
    """Konteks korupsi dari partisi latih D₀, dihitung sekali per dataset dan learner (ADR 0009)."""
    key = (prepared.dataset_id, str(prepared.meta["train_sha256"]), learner_spec_sha256(learner))
    if key not in _CONTEXTS:
        seed = derive_seed("context", prepared.dataset_id)
        _CONTEXTS[key] = build_context(prepared.train_frame(), prepared.target, learner, seed)
    return _CONTEXTS[key]


def run_id_for(dataset_id: int, config_id: str, profile_id: str, seed_index: int) -> str:
    return f"run_{int(dataset_id)}_{config_id}_{profile_id}_{int(seed_index)}"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def corpus_row(prepared: PreparedDataset) -> dict[str, Any]:
    """Baris `corpus_dataset` dari metadata dataset yang sudah disiapkan."""
    meta = prepared.meta
    return {
        "dataset_id": int(meta["dataset_id"]),
        "name": meta["name"],
        "version": int(meta["version"]),
        "licence": meta["licence"],
        "source_checksum": meta["source_checksum"],
        "target": meta["target"],
        "n_rows": int(meta["n_rows"]),
        "n_features": int(meta["n_features"]),
        "n_classes": int(meta["n_classes"]),
        "missing_cell_frac": float(meta["missing_cell_frac"]),
        "passed": bool(meta["passed"]),
        "reasons": json.dumps(meta["reasons"]),
        "split_seed": meta["split_seed"],
        "test_frac": float(meta["split"]["test_frac"]),
        "d0_sha256": meta["d0_sha256"],
        "train_sha256": meta["train_sha256"],
        "test_sha256": meta["test_sha256"],
        "prepared_at": meta["prepared_at"],
    }


def run_corruption(
    prepared: PreparedDataset,
    specs: Sequence[AnySpec],
    seed_index: int,
    learner: LearnerSpec,
    store: RunStore,
    provenance_fn: Callable[[], Provenance] = provenance,
    profile_config: ProfileConfig | None = None,
) -> dict[str, Any]:
    """Jalankan satu run dan tulis `corruption_run` serta `run_log`.

    Setiap percobaan, berhasil atau gagal, menghasilkan satu baris `run_log` dengan commit dan
    seed. Run yang sudah ada tidak dijalankan ulang (`RecordExistsError`).
    """
    if not prepared.passed:
        raise CorpusError(f"dataset {prepared.dataset_id} tidak lolos saringan korpus")
    profile_cfg = profile_config or ProfileConfig()
    config_id = config_id_for(specs, learner)
    profile_id = profile_config_id(profile_cfg)
    seed = run_seed(prepared.dataset_id, config_id, seed_index)
    run_id = run_id_for(prepared.dataset_id, config_id, profile_id, seed_index)
    if store.has_run(run_id):
        raise RecordExistsError(f"run {run_id} sudah ada")
    prov = provenance_fn()
    specs_json = spec_json(specs)
    store.register_config(
        {
            "config_id": config_id,
            "kind": "corruption",
            "spec_json": specs_json,
            "learner_spec_version": learner.version,
            "learner_spec_sha256": learner_spec_sha256(learner),
            "registered_at": _now(),
        }
    )
    store.register_config(
        {
            "config_id": profile_id,
            "kind": "profile",
            "spec_json": json.dumps(
                {"schema": PROFILE_SCHEMA_VERSION, "config": profile_cfg.model_dump()},
                sort_keys=True,
            ),
            "learner_spec_version": learner.version,
            "learner_spec_sha256": learner_spec_sha256(learner),
            "registered_at": _now(),
        }
    )
    started_at = _now()
    log: dict[str, Any] = {
        "log_id": f"{run_id}__{uuid.uuid4().hex}",
        "run_id": run_id,
        "kind": "corruption_run",
        "dataset_id": prepared.dataset_id,
        "config_id": config_id,
        "seed_index": int(seed_index),
        "seed": seed,
        **provenance_fields(prov),
        "started_at": started_at,
    }
    try:
        row = _execute(
            prepared, specs, seed_index, learner, profile_cfg, config_id, seed, run_id, specs_json
        )
        row["profile_config_id"] = profile_id
        store.write_corruption_run(row)
    except Exception as exc:
        store.write_run_log({**log, "finished_at": _now(), "status": "failed", "error": repr(exc)})
        raise
    store.write_run_log({**log, "finished_at": _now(), "status": "ok", "error": None})
    return row


def dirty_train(
    prepared: PreparedDataset, specs: Sequence[AnySpec], seed: int, learner: LearnerSpec
) -> tuple[pd.DataFrame, CorruptionResult]:
    """Partisi latih bersih dan hasil korupsinya untuk seed run `seed` (deterministik, BR-84).

    Satu-satunya cara membangun data kotor sebuah run, sehingga run dan noise floor estimasinya
    memakai data kotor yang sama.
    """
    train = prepared.train_frame()
    result = corrupt(
        train, prepared.target, specs, sub_seed(seed, "corrupt"), context_for(prepared, learner)
    )
    return train, result


def _execute(
    prepared: PreparedDataset,
    specs: Sequence[AnySpec],
    seed_index: int,
    learner: LearnerSpec,
    profile_cfg: ProfileConfig,
    config_id: str,
    seed: int,
    run_id: str,
    specs_json: str,
) -> dict[str, Any]:
    target = prepared.target
    test = prepared.test_frame()
    test_hash = frame_sha256(test)
    if test_hash != prepared.meta["test_sha256"]:
        raise PartitionChangedError("partisi uji berbeda dari yang dicatat saat disiapkan (BR-80)")
    corruption_seed = sub_seed(seed, "corrupt")
    learner_seed = sub_seed(seed, "learner")
    train, result = dirty_train(prepared, specs, seed, learner)
    # BR-20: profil hanya melihat partisi latih kotor, bukan versi bersih atau spesifikasi korupsi.
    profile = compute_profile(
        result.frame, target, learner=learner, seed=PROFILE_SEED, config=profile_cfg
    )
    measured = measure_delta_auc(learner, train, result.frame, test, target, learner_seed)
    if frame_sha256(test) != test_hash:
        raise PartitionChangedError("partisi uji berubah selama run (BR-80)")
    return {
        "run_id": run_id,
        "dataset_id": prepared.dataset_id,
        "config_id": config_id,
        "seed_index": int(seed_index),
        "seed": seed,
        "corruption_seed": corruption_seed,
        "learner_seed": learner_seed,
        "spec_json": specs_json,
        "kinds": ",".join(step.kind for step in result.steps),
        "nominal_level": float(specs[0].level) if len(specs) == 1 else None,
        "affected_row_frac": result.affected_row_frac,
        "n_affected": result.n_affected,
        "n_train_clean": len(train),
        "n_train_dirty": len(result.frame),
        "steps_json": json.dumps([asdict(step) for step in result.steps], sort_keys=True),
        "auc_clean": measured.auc_clean,
        "auc_dirty": measured.auc_dirty,
        "delta_auc": measured.delta_auc,
        "delta_auc_relative": measured.delta_auc_relative,
        "test_sha256": test_hash,
        "learner_spec_version": learner.version,
        "learner_spec_sha256": learner_spec_sha256(learner),
        "profile_schema_version": profile.schema_version,
        "profile_sample_size": profile.sample_size,
        "profile_input_warnings": json.dumps(profile.input_warnings),
        "leakage_flagged": profile.leakage.flagged,
        "leakage_feature": profile.leakage.feature,
        "leakage_auc": profile.leakage.auc,
        "leakage_threshold": profile.leakage.threshold,
        **{f"p_{name}": profile.features[name] for name in FEATURES},
        "created_at": _now(),
    }


LEAK_COLUMN = "__synthetic_leak__"


def calibrate_leakage(
    prepared: PreparedDataset,
    learner: LearnerSpec,
    epsilons: Sequence[float],
    probes: Sequence[tuple[int, float]],
    seed: int,
) -> list[dict[str, Any]]:
    """Kalibrasi probe kebocoran (ADR 0005, 0007) dan validasi estimator label noise (ADR 0009 K2).

    Untuk tiap level label noise ε pada partisi latih D₀: sisipkan fitur bocor sintetis (salinan
    label bersih), ukur AUC satu fitur untuk fitur bocor (daya deteksi) dan untuk fitur asli
    (false flag) pada tiap pasangan (`max_depth`, `min_samples_leaf`) di `probes`, serta taksiran
    label noise dengan dan tanpa fitur bocor. Hanya untuk riset; tidak dipakai jalur scan.
    """
    from sklearn.model_selection import StratifiedKFold

    if not prepared.passed:
        raise CorpusError(f"dataset {prepared.dataset_id} tidak lolos saringan korpus")
    target = prepared.target
    train = prepared.train_frame()
    clean_codes = train[target].cat.codes.to_numpy().astype("float64")
    configs = [
        ProfileConfig(leakage_max_depth=depth, leakage_min_samples_leaf=leaf)
        for depth, leaf in probes
    ]
    rows: list[dict[str, Any]] = []
    for eps in epsilons:
        step_seed = sub_seed(seed, f"eps={eps}")
        noisy = (
            train
            if eps == 0
            else corrupt(train, target, [LabelUniform(level=eps)], step_seed).frame
        )
        dirty = prepare_input(noisy, target, ProfileConfig()).frame.copy()
        with_leak = dirty.assign(**{LEAK_COLUMN: clean_codes})
        # Kebocoran kategorikal: tiap label bersih dipecah ke 10 kategori murni.
        buckets = np.random.default_rng(step_seed).integers(0, 10, size=len(clean_codes))
        leak_cat = pd.Series([f"{int(c)}_{b}" for c, b in zip(clean_codes, buckets, strict=True)])
        y = dirty[target].cat.codes.to_numpy()
        eps_hat = label_noise_rate(y, oof_predict_proba(learner, dirty, target, step_seed))
        eps_hat_leak = label_noise_rate(y, oof_predict_proba(learner, with_leak, target, step_seed))
        folds = list(
            StratifiedKFold(n_splits=5, shuffle=True, random_state=step_seed).split(
                np.zeros(len(y)), y
            )
        )
        features = [c for c in dirty.columns if c != target]
        leak = single_feature_aucs(with_leak[LEAK_COLUMN], y, folds, configs, step_seed)
        leak_cat_aucs = single_feature_aucs(leak_cat, y, folds, configs, step_seed)
        # Baris: fitur asli; kolom: konfigurasi probe.
        matrix = np.array(
            [single_feature_aucs(dirty[c], y, folds, configs, step_seed) for c in features]
        )
        for j, (depth, leaf) in enumerate(probes):
            best = int(np.argmax(matrix[:, j]))
            rows.append(
                {
                    "dataset_id": prepared.dataset_id,
                    "epsilon": float(eps),
                    "max_depth": int(depth),
                    "min_samples_leaf": float(leaf),
                    "eps_hat": eps_hat,
                    "eps_hat_with_leak": eps_hat_leak,
                    "leak_auc": leak[j],
                    "leak_cat_auc": leak_cat_aucs[j],
                    "max_feature_auc": float(matrix[best, j]),
                    "max_feature": str(features[best]),
                }
            )
    return rows


# --- noise floor (BR-04, F-S06) ---


def _nf_row(
    nf_id: str,
    prepared: PreparedDataset,
    kind: str,
    source_run_id: str | None,
    index: int,
    seed: int,
    auc: float,
    n_seeds: int,
    seconds: float,
    learner: LearnerSpec,
    profile_id: str | None,
    prov: Provenance,
) -> dict[str, Any]:
    return {
        "nf_id": nf_id,
        "dataset_id": prepared.dataset_id,
        "kind": kind,
        "source_run_id": source_run_id,
        "seed_index": int(index),
        "seed": int(seed),
        "auc": float(auc),
        "n_seeds": int(n_seeds),
        "batch_seconds": float(seconds),
        "learner_spec_version": learner.version,
        "learner_spec_sha256": learner_spec_sha256(learner),
        "profile_config_id": profile_id,
        "git_commit": prov.git_commit,
        "git_dirty": prov.git_dirty,
        "created_at": _now(),
    }


def measure_dataset_noise_floor(
    prepared: PreparedDataset,
    learner: LearnerSpec,
    store: RunStore,
    n_seeds: int,
    provenance_fn: Callable[[], Provenance] = provenance,
) -> list[float]:
    """Noise floor terukur (BR-04): AUC model versi bersih untuk `n_seeds` seed pada split tetap.

    Ditulis ke tabel `noise_floor` satu baris per seed; statistik ringkasnya masih terbuka sampai
    G2 (`business-rules.md` hal terbuka #1).
    """
    if not prepared.passed:
        raise CorpusError(f"dataset {prepared.dataset_id} tidak lolos saringan korpus")
    tag = learner_spec_sha256(learner)[:12]
    ids = [f"nfm_{prepared.dataset_id}_{tag}_{i}" for i in range(n_seeds)]
    if all(store.has_noise_floor(nf_id) for nf_id in ids):
        raise RecordExistsError(f"noise floor terukur dataset {prepared.dataset_id} sudah ada")
    seeds = [derive_seed("noise_floor_measured", prepared.dataset_id, i) for i in range(n_seeds)]
    start = time.perf_counter()
    aucs = measure_noise_floor(
        learner, prepared.train_frame(), prepared.test_frame(), prepared.target, seeds
    )
    seconds = time.perf_counter() - start
    prov = provenance_fn()
    for i, (nf_id, seed, auc) in enumerate(zip(ids, seeds, aucs, strict=True)):
        if not store.has_noise_floor(nf_id):
            store.write_noise_floor(
                _nf_row(
                    nf_id,
                    prepared,
                    "measured",
                    None,
                    i,
                    seed,
                    auc,
                    n_seeds,
                    seconds,
                    learner,
                    None,
                    prov,
                )
            )
    return aucs


def estimate_run_noise_floor(
    prepared: PreparedDataset,
    specs: Sequence[AnySpec],
    seed_index: int,
    learner: LearnerSpec,
    store: RunStore,
    n_seeds: int,
    provenance_fn: Callable[[], Provenance] = provenance,
    profile_config: ProfileConfig | None = None,
) -> list[float]:
    """Noise floor estimasi (BR-04) pada data kotor sebuah run, dengan seed probe jalur scan.

    Data kotor dibangun ulang dengan `dirty_train` dan seed run yang sama, sehingga identik
    dengan data kotor run tersebut. Seed probe berasal dari `noise_floor_seeds` (sama dengan scan).
    """
    if not prepared.passed:
        raise CorpusError(f"dataset {prepared.dataset_id} tidak lolos saringan korpus")
    profile_cfg = profile_config or ProfileConfig()
    config_id = config_id_for(specs, learner)
    profile_id = profile_config_id(profile_cfg)
    seed = run_seed(prepared.dataset_id, config_id, seed_index)
    run_id = run_id_for(prepared.dataset_id, config_id, profile_id, seed_index)
    ids = [f"nfe_{run_id}_{i}" for i in range(n_seeds)]
    if all(store.has_noise_floor(nf_id) for nf_id in ids):
        raise RecordExistsError(f"noise floor estimasi {run_id} sudah ada")
    _, result = dirty_train(prepared, specs, seed, learner)
    seeds = noise_floor_seeds(n_seeds)
    start = time.perf_counter()
    aucs = estimate_noise_floor(
        result.frame, prepared.target, learner=learner, seeds=seeds, config=profile_cfg
    )
    seconds = time.perf_counter() - start
    prov = provenance_fn()
    for i, (nf_id, probe_seed, auc) in enumerate(zip(ids, seeds, aucs, strict=True)):
        if not store.has_noise_floor(nf_id):
            store.write_noise_floor(
                _nf_row(
                    nf_id,
                    prepared,
                    "estimated",
                    run_id,
                    i,
                    probe_seed,
                    auc,
                    n_seeds,
                    seconds,
                    learner,
                    profile_id,
                    prov,
                )
            )
    return aucs


def run_baseline_d(
    prepared: PreparedDataset,
    specs: Sequence[AnySpec],
    seed_index: int,
    learner: LearnerSpec,
    store: RunStore,
    provenance_fn: Callable[[], Provenance] = provenance,
    profile_config: ProfileConfig | None = None,
) -> dict[str, Any]:
    """Baseline (d) pada data kotor sebuah run yang sudah ada (F-S09, ADR 0011 G2-7).

    Data kotor dibangun ulang dengan `dirty_train` dan seed run yang sama; profilnya diambil dari
    `corruption_run` (dihitung hanya dari data kotor, BR-20).
    """
    from ceteris.metamodel import baseline_d

    profile_cfg = profile_config or ProfileConfig()
    config_id = config_id_for(specs, learner)
    run_id = run_id_for(prepared.dataset_id, config_id, profile_config_id(profile_cfg), seed_index)
    if store.has_baseline_d(run_id):
        raise RecordExistsError(f"baseline (d) {run_id} sudah ada")
    stored = store.read_run(run_id)
    profile = {name: float(stored[f"p_{name}"]) for name in FEATURES}
    seed = run_seed(prepared.dataset_id, config_id, seed_index)
    _, result = dirty_train(prepared, specs, seed, learner)
    out = baseline_d(result.frame, prepared.target, profile, learner, sub_seed(seed, "baseline_d"))
    prov = provenance_fn()
    row = {
        "run_id": run_id,
        "dataset_id": prepared.dataset_id,
        "delta_linear": out.delta_linear,
        "delta_quadratic": out.delta_quadratic,
        "auc_current": out.auc_current,
        "p0_total": out.p0_total,
        "detected_json": json.dumps(out.detected, sort_keys=True),
        "points_json": json.dumps(out.points),
        "seconds": out.seconds,
        "n_train": out.n_train,
        "n_holdout": out.n_holdout,
        "git_commit": prov.git_commit,
        "git_dirty": prov.git_dirty,
        "created_at": _now(),
    }
    store.write_baseline_d(row)
    return row


# --- pilot E0 (Phase 3) ---


class E0Protocol(BaseModel):
    """Isi `configs/e0.yaml`: dataset pilot, jumlah seed, dan kandidat campuran."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str
    datasets: list[int] = Field(min_length=1)
    seeds_per_config: int = Field(ge=1)
    measured_seeds: int = Field(ge=2)
    estimated_seeds: int = Field(ge=2)
    estimated_seed_indices: list[int]
    baseline_d_seed_indices: list[int] = Field(default_factory=list)
    mixture_candidates: list[list[dict[str, Any]]]

    def mixtures(self) -> list[tuple[AnySpec, ...]]:
        return [tuple(parse_spec(item) for item in mix) for mix in self.mixture_candidates]


def load_e0_protocol(path: Path) -> E0Protocol:
    return E0Protocol.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


@dataclass(frozen=True)
class Task:
    """Satu pekerjaan E0: run korupsi, noise floor terukur, atau noise floor estimasi."""

    kind: Literal["run", "nf_measured", "nf_estimated", "baseline_d"]
    dataset_id: int
    specs_json: str | None = None
    seed_index: int = 0


def e0_tasks(protocol: E0Protocol, singles: Sequence[AnySpec]) -> list[Task]:
    """Semua pekerjaan E0: konfigurasi tunggal dan kandidat campuran × seed × dataset."""
    configs: list[tuple[AnySpec, ...]] = [(spec,) for spec in singles] + protocol.mixtures()
    tasks: list[Task] = []
    for dataset_id in protocol.datasets:
        tasks.append(Task("nf_measured", dataset_id))
        for specs in configs:
            payload = spec_json(specs)
            tasks.extend(
                Task("run", dataset_id, payload, i) for i in range(protocol.seeds_per_config)
            )
            tasks.extend(
                Task("nf_estimated", dataset_id, payload, i)
                for i in protocol.estimated_seed_indices
            )
            tasks.extend(
                Task("baseline_d", dataset_id, payload, i) for i in protocol.baseline_d_seed_indices
            )
    return tasks


_WORKER: dict[str, Any] = {}


def _init_worker(
    learner_path: str, experiment_path: str, corpus_dir: str, store_root: str, protocol_path: str
) -> None:
    import warnings

    warnings.filterwarnings("ignore", category=UserWarning)
    from ceteris.corpus import OpenMLFetcher, load_experiment_config
    from ceteris.train import load_learner_spec

    _WORKER.update(
        learner=load_learner_spec(Path(learner_path)),
        cfg=load_experiment_config(Path(experiment_path)),
        corpus=Path(corpus_dir),
        fetcher=OpenMLFetcher(Path(corpus_dir) / "_openml"),
        store=RunStore(Path(store_root)),
        protocol=load_e0_protocol(Path(protocol_path)),
        prepared={},
    )


def _prepared(dataset_id: int) -> PreparedDataset:
    from ceteris.corpus import prepare_dataset

    cache: dict[int, PreparedDataset] = _WORKER["prepared"]
    if dataset_id not in cache:
        cfg = _WORKER["cfg"]
        cache[dataset_id] = prepare_dataset(
            dataset_id, _WORKER["fetcher"], _WORKER["corpus"], cfg.filter, cfg.split
        )
    return cache[dataset_id]


def _run_task(task: Task) -> tuple[Task, str, float, str | None]:
    start = time.perf_counter()
    learner: LearnerSpec = _WORKER["learner"]
    store: RunStore = _WORKER["store"]
    protocol: E0Protocol = _WORKER["protocol"]
    try:
        prepared = _prepared(task.dataset_id)
        specs = (
            [parse_spec(item) for item in json.loads(task.specs_json)] if task.specs_json else []
        )
        if task.kind == "nf_measured":
            measure_dataset_noise_floor(prepared, learner, store, protocol.measured_seeds)
        elif task.kind == "nf_estimated":
            estimate_run_noise_floor(
                prepared, specs, task.seed_index, learner, store, protocol.estimated_seeds
            )
        elif task.kind == "baseline_d":
            run_baseline_d(prepared, specs, task.seed_index, learner, store)
        else:
            run_corruption(prepared, specs, task.seed_index, learner, store)
    except RecordExistsError:
        return task, "exists", time.perf_counter() - start, None
    except Exception as exc:  # run_corruption sudah mencatatnya di run_log
        return task, "failed", time.perf_counter() - start, repr(exc)
    return task, "ok", time.perf_counter() - start, None


def run_e0(
    protocol_path: Path,
    corpus_dir: Path,
    store_root: Path,
    workers: int,
    repo_root: Path = REPO_ROOT,
    kinds: Sequence[str] | None = None,
) -> dict[str, int]:
    """Jalankan pekerjaan E0 secara paralel; pekerjaan yang sudah ada dilewati (resume).

    `kinds` membatasi jenis pekerjaan, misalnya hanya `baseline_d`.
    """
    from multiprocessing import get_context

    from ceteris.corrupt import load_corruption_grid

    protocol = load_e0_protocol(protocol_path)
    grid = load_corruption_grid(repo_root / "configs" / "corruption.yaml")
    tasks = e0_tasks(protocol, grid.singles)
    if kinds:
        tasks = [t for t in tasks if t.kind in set(kinds)]
    # Noise floor terukur dulu (murah), lalu urutan dataset di protokol (terbesar di depan).
    rank = {d: i for i, d in enumerate(protocol.datasets)}
    tasks.sort(key=lambda t: (t.kind != "nf_measured", rank[t.dataset_id]))
    init_args = (
        str(repo_root / "configs" / "learner.yaml"),
        str(repo_root / "configs" / "experiment.yaml"),
        str(corpus_dir),
        str(store_root),
        str(protocol_path),
    )
    _init_worker(*init_args)
    store: RunStore = _WORKER["store"]
    for dataset_id in protocol.datasets:
        store.write_corpus_dataset(corpus_row(_prepared(dataset_id)))
    counts = {"ok": 0, "exists": 0, "failed": 0}
    started = time.perf_counter()
    with get_context("spawn").Pool(workers, _init_worker, init_args) as pool:
        for n, (task, status, seconds, error) in enumerate(
            pool.imap_unordered(_run_task, tasks, chunksize=1), 1
        ):
            counts[status] += 1
            detail = f" {error}" if error else ""
            print(
                f"[{n}/{len(tasks)}] {status} {task.kind} {task.dataset_id} s{task.seed_index} "
                f"{seconds:.1f}s (total {time.perf_counter() - started:.0f}s){detail}",
                flush=True,
            )
    return counts


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m ceteris.experiment")
    sub = parser.add_subparsers(dest="command", required=True)
    e0 = sub.add_parser("e0", help="jalankan pilot E0 (Phase 3)")
    e0.add_argument("--protocol", type=Path, default=REPO_ROOT / "configs" / "e0.yaml")
    e0.add_argument("--corpus", type=Path, default=REPO_ROOT / "data" / "corpus")
    e0.add_argument("--store", type=Path, default=REPO_ROOT / "runs" / "e0")
    e0.add_argument("--workers", type=int, default=4)
    e0.add_argument("--kinds", nargs="*", help="hanya jenis pekerjaan ini, misalnya baseline_d")
    args = parser.parse_args(argv)
    counts = run_e0(args.protocol, args.corpus, args.store, args.workers, kinds=args.kinds)
    print(json.dumps(counts), flush=True)
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
