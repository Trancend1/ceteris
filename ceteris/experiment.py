"""ceteris.experiment: orkestrasi satu run riset (korpus → korupsi → ΔAUC → run store).

Fitur: F-S01, F-S02, F-S03, F-S07 (docs/product.md). Jalur: riset saja. Modul ini mengimpor
`corpus` dan `corrupt`, sehingga jalur scan tidak boleh mengimpornya (AC-3).
Aturan: BR-01, BR-80 (hash partisi uji sebelum dan sesudah), BR-82, BR-84.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from ceteris.corpus import CorpusError, PreparedDataset, frame_sha256
from ceteris.corrupt import AnySpec, corrupt
from ceteris.seeding import run_seed, sub_seed
from ceteris.store import (
    Provenance,
    RecordExistsError,
    RunStore,
    provenance,
    provenance_fields,
)
from ceteris.train import LearnerSpec, measure_delta_auc


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

    Mengubah parameter learner tanpa menaikkan versinya tetap menghasilkan `config_id` baru,
    sehingga hasil dari dua konfigurasi learner tidak pernah bercampur di satu run.
    """
    payload = json.dumps(
        {"corruption": json.loads(spec_json(specs)), "learner": learner_spec_sha256(learner)},
        sort_keys=True,
    )
    return "cfg_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def run_id_for(dataset_id: int, config_id: str, seed_index: int) -> str:
    return f"run_{int(dataset_id)}_{config_id}_{int(seed_index)}"


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
) -> dict[str, Any]:
    """Jalankan satu run dan tulis `corruption_run` serta `run_log`.

    Setiap percobaan, berhasil atau gagal, menghasilkan satu baris `run_log` dengan commit dan
    seed. Run yang sudah ada tidak dijalankan ulang (`RecordExistsError`).
    """
    if not prepared.passed:
        raise CorpusError(f"dataset {prepared.dataset_id} tidak lolos saringan korpus")
    config_id = config_id_for(specs, learner)
    seed = run_seed(prepared.dataset_id, config_id, seed_index)
    run_id = run_id_for(prepared.dataset_id, config_id, seed_index)
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
        row = _execute(prepared, specs, seed_index, learner, config_id, seed, run_id, specs_json)
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
    result = corrupt(train, target, specs, corruption_seed)
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
        "created_at": _now(),
    }
