"""ceteris.experiment: orkestrasi satu run riset (korpus → korupsi → profil → ΔAUC → run store).

Fitur: F-S01–F-S05, F-S07 (docs/product.md). Jalur: riset saja. Modul ini mengimpor `corpus`
dan `corrupt`, sehingga jalur scan tidak boleh mengimpornya (AC-3).
Aturan: BR-01, BR-20 (profil dari data kotor saja), BR-80 (hash partisi uji sebelum dan
sesudah), BR-82, BR-84; AC-11 (profil dan ΔAUC di satu tabel `corruption_run`).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from ceteris.corpus import CorpusError, PreparedDataset, frame_sha256
from ceteris.corrupt import AnySpec, CorruptionContext, LabelUniform, build_context, corrupt
from ceteris.dqprofile import (
    FEATURES,
    PROFILE_SCHEMA_VERSION,
    PROFILE_SEED,
    ProfileConfig,
    compute_profile,
    label_noise_rate,
    prepare_input,
    single_feature_aucs,
)
from ceteris.seeding import derive_seed, run_seed, sub_seed
from ceteris.store import (
    Provenance,
    RecordExistsError,
    RunStore,
    provenance,
    provenance_fields,
)
from ceteris.train import LearnerSpec, measure_delta_auc, oof_predict_proba


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
    train = prepared.train_frame()
    test = prepared.test_frame()
    test_hash = frame_sha256(test)
    if test_hash != prepared.meta["test_sha256"]:
        raise PartitionChangedError("partisi uji berbeda dari yang dicatat saat disiapkan (BR-80)")
    corruption_seed = sub_seed(seed, "corrupt")
    learner_seed = sub_seed(seed, "learner")
    result = corrupt(train, target, specs, corruption_seed, context_for(prepared, learner))
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
