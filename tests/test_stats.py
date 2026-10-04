"""Seam: sigfw.stats. Expected values are hand-computed, not recomputed with the code under test."""

from __future__ import annotations

import pytest

from sigfw.stats import FP_MAX_FLAGGED, FP_UPPER_LIMIT, GATE_N, kill_rule, wilson_upper


@pytest.mark.parametrize(
    ("k", "n", "expected_pct"),
    [(6, 200, 6.39), (7, 200, 7.05), (12, 300, 6.86), (13, 300, 7.27)],
)
def test_wilson_upper_matches_pre_registered_values(k: int, n: int, expected_pct: float) -> None:
    assert round(wilson_upper(k, n) * 100, 2) == expected_pct


def test_wilson_upper_edges() -> None:
    assert wilson_upper(200, 200) == pytest.approx(1.0)
    # k = 0: upper bound is z^2 / (n + z^2) = 3.8416 / 203.8416
    assert wilson_upper(0, 200) == pytest.approx(0.018846, abs=1e-5)


@pytest.mark.parametrize(("k", "n"), [(-1, 10), (11, 10), (0, 0)])
def test_wilson_upper_rejects_invalid_counts(k: int, n: int) -> None:
    with pytest.raises(ValueError):
        wilson_upper(k, n)


def _fams(*pairs: tuple[int, int]) -> dict[str, tuple[int, int]]:
    return dict(zip("ABCD", pairs, strict=True))


def test_integer_cap_agrees_with_the_wilson_bound_for_every_count() -> None:
    passing = [k for k in range(201) if wilson_upper(k, GATE_N) <= FP_UPPER_LIMIT]
    assert max(passing) == FP_MAX_FLAGGED == 6
    assert passing == list(range(FP_MAX_FLAGGED + 1))  # monotone: no gaps


def test_fp_gate_passes_at_6_of_200() -> None:
    v = kill_rule(fp_flagged=6, fp_n=200, families=_fams((10, 10), (10, 10), (10, 10), (10, 10)))
    assert v.fp_pass is True
    assert v.passed is True


def test_fp_gate_fails_at_7_of_200() -> None:
    v = kill_rule(fp_flagged=7, fp_n=200, families=_fams((10, 10), (10, 10), (10, 10), (10, 10)))
    assert v.fp_pass is False
    assert v.passed is False


@pytest.mark.parametrize("n", [199, 201, 300])
def test_gate_rejects_any_n_other_than_200(n: int) -> None:
    with pytest.raises(ValueError, match="200"):
        kill_rule(fp_flagged=0, fp_n=n, families=_fams((10, 10), (10, 10), (10, 10), (10, 10)))


def test_average_fails_even_though_small_families_are_exempt_from_the_floor() -> None:
    # A 9/10, B 7/10, C 10/10, D 6/19 -> macro-average 0.7289 (hand-computed): below 0.8.
    v = kill_rule(fp_flagged=0, fp_n=200, families=_fams((9, 10), (7, 10), (10, 10), (6, 19)))
    assert v.avg_pass is False
    assert v.floor_pass is True  # all four have n < 20
    assert v.passed is False


def test_floor_is_inclusive_at_exactly_70_percent() -> None:
    # B 14/20 is exactly 70%; average 0.8618 (hand-computed).
    v = kill_rule(fp_flagged=0, fp_n=200, families=_fams((8, 10), (14, 20), (10, 10), (18, 19)))
    assert v.avg_pass is True
    assert v.floor_pass is True
    assert v.passed is True


def test_floor_fails_below_70_percent_for_family_of_20() -> None:
    v = kill_rule(fp_flagged=0, fp_n=200, families=_fams((13, 20), (10, 10), (10, 10), (10, 10)))
    assert v.avg_pass is True  # (0.65 + 3) / 4 = 0.9125
    assert v.floor_pass is False
    assert v.passed is False


def test_small_family_is_averaged_but_exempt_from_floor() -> None:
    # A 8/19 = 42%: exempt from the floor, still averaged: (0.4211 + 3) / 4 = 0.8553.
    v = kill_rule(fp_flagged=0, fp_n=200, families=_fams((8, 19), (20, 20), (20, 20), (20, 20)))
    assert v.floor_pass is True
    assert v.avg_pass is True
    assert v.passed is True


def test_average_threshold_is_inclusive_at_80_percent() -> None:
    v = kill_rule(fp_flagged=0, fp_n=200, families=_fams((8, 10), (8, 10), (8, 10), (8, 10)))
    assert v.avg_pass is True


def test_requires_exactly_four_families_with_positive_n() -> None:
    with pytest.raises(ValueError, match="four"):
        kill_rule(fp_flagged=0, fp_n=200, families={"A": (1, 1)})
    with pytest.raises(ValueError):
        kill_rule(fp_flagged=0, fp_n=200, families=_fams((0, 0), (1, 1), (1, 1), (1, 1)))
