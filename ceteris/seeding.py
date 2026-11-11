"""ceteris.seeding: turunan seed deterministik.

Fitur: F-S07 (docs/product.md). Jalur: riset dan scan. Aturan: BR-84.

Seed setiap run diturunkan dari (`dataset_id`, `config_id`, indeks seed). Seed untuk
keperluan lain di dalam run (korupsi, learner) diturunkan lagi dari seed run dengan
label tujuan, sehingga tiap keperluan punya aliran acak sendiri tetapi tetap bisa diulang.
Modul ini tidak mengimpor kode eksperimen, sehingga aman dipakai jalur scan (AC-3).
"""

from __future__ import annotations

import hashlib

# LightGBM menerima seed int32; batas ini juga aman untuk numpy dan scikit-learn.
MAX_SEED = 2**31 - 1


def derive_seed(*parts: object) -> int:
    """Seed deterministik dari bagian-bagian yang diberikan (SHA-256, dipotong ke int31)."""
    if not parts:
        raise ValueError("derive_seed butuh minimal satu bagian")
    payload = "\x1f".join(f"{type(p).__name__}:{p}" for p in parts).encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], "big") % MAX_SEED


def run_seed(dataset_id: int, config_id: str, seed_index: int) -> int:
    """Seed utama satu run dari (dataset_id, config_id, indeks seed) (BR-84)."""
    if seed_index < 0:
        raise ValueError(f"seed_index harus >= 0, didapat {seed_index}")
    if not config_id:
        raise ValueError("config_id tidak boleh kosong")
    return derive_seed("run", int(dataset_id), config_id, int(seed_index))


def sub_seed(seed: int, purpose: str) -> int:
    """Seed turunan untuk satu keperluan di dalam run (misalnya "corrupt", "learner")."""
    if not purpose:
        raise ValueError("purpose tidak boleh kosong")
    return derive_seed("sub", int(seed), purpose)


def split_seed(dataset_id: int) -> int:
    """Seed split latih/uji. Bergantung pada dataset saja, sehingga split tetap untuk semua run."""
    return derive_seed("split", int(dataset_id))
