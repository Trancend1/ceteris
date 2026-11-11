"""Uji turunan seed (BR-84)."""

from __future__ import annotations

import pytest

from ceteris.seeding import MAX_SEED, derive_seed, run_seed, split_seed, sub_seed


def test_br84_run_seed_is_deterministic_and_input_sensitive() -> None:
    base = run_seed(31, "cfg_abc", 0)
    assert base == run_seed(31, "cfg_abc", 0)
    variants = {run_seed(32, "cfg_abc", 0), run_seed(31, "cfg_abd", 0), run_seed(31, "cfg_abc", 1)}
    assert base not in variants
    assert len(variants) == 3


def test_br84_seeds_stay_in_int31_range() -> None:
    seeds = [run_seed(d, "cfg", i) for d in range(20) for i in range(5)]
    assert all(0 <= s < MAX_SEED for s in seeds)


def test_br84_sub_and_split_seeds_are_separate_streams() -> None:
    seed = run_seed(3, "cfg_x", 0)
    assert sub_seed(seed, "corrupt") != sub_seed(seed, "learner")
    assert split_seed(3) == split_seed(3)
    assert split_seed(3) != split_seed(4)


def test_br84_derive_seed_does_not_confuse_types() -> None:
    assert derive_seed("1") != derive_seed(1)


@pytest.mark.parametrize(
    ("call", "message"),
    [
        (lambda: run_seed(1, "cfg", -1), "seed_index"),
        (lambda: run_seed(1, "", 0), "config_id"),
        (lambda: sub_seed(1, ""), "purpose"),
        (lambda: derive_seed(), "minimal"),
    ],
)
def test_br84_invalid_inputs_are_rejected(call: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        call()  # type: ignore[operator]
