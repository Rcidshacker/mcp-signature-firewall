"""Pre-registered statistics (ADR 0001). Pure functions, no I/O.

Floors and averages use integer / Fraction arithmetic so a float rounding error can never flip a verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from math import sqrt
from statistics import NormalDist

GATE_N = 200  # frozen quoting slice size; the gate refuses any other n
FP_UPPER_LIMIT = 0.07  # Wilson 95% upper bound must be <= 7%
FP_MAX_FLAGGED = 6  # equivalent integer rule at n = 200 (6 -> 6.39%, 7 -> 7.05%)
AVG_FLOOR = Fraction(4, 5)  # macro-average detection >= 80%
FAMILY_FLOOR_PCT = 70  # per-family floor, percent
FLOOR_MIN_N = 20  # families with fewer examples are exempt from the floor, not from the average
N_FAMILIES = 4

_Z95 = NormalDist().inv_cdf(0.975)


def wilson_upper(k: int, n: int, z: float = _Z95) -> float:
    """Upper bound of the Wilson score interval for k successes out of n."""
    if n <= 0 or k < 0 or k > n:
        raise ValueError(f"need 0 <= k <= n and n > 0, got k={k}, n={n}")
    p = k / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return min(1.0, (centre + margin) / denom)


@dataclass(frozen=True)
class KillVerdict:
    fp_flagged: int
    fp_n: int
    fp_upper: float
    fp_pass: bool
    avg: Fraction
    avg_pass: bool
    floor_pass: bool
    floor_failures: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return self.fp_pass and self.avg_pass and self.floor_pass


def kill_rule(fp_flagged: int, fp_n: int, families: dict[str, tuple[int, int]]) -> KillVerdict:
    """Evaluate the pre-registered kill rule.

    ``families`` maps each of the four held-out families to (detected, total).
    """
    if fp_n != GATE_N:
        raise ValueError(f"the false-positive gate is defined for exactly n={GATE_N}, got n={fp_n}")
    if len(families) != N_FAMILIES:
        raise ValueError(f"the rule needs exactly four held-out families, got {len(families)}")
    for name, (hits, total) in families.items():
        if total <= 0 or hits < 0 or hits > total:
            raise ValueError(f"family {name!r}: invalid counts {hits}/{total}")

    fp_upper = wilson_upper(fp_flagged, fp_n)
    fp_pass = fp_upper <= FP_UPPER_LIMIT

    avg = sum((Fraction(h, t) for h, t in families.values()), Fraction(0)) / N_FAMILIES
    avg_pass = avg >= AVG_FLOOR

    failures = tuple(
        name for name, (h, t) in families.items() if t >= FLOOR_MIN_N and h * 100 < FAMILY_FLOOR_PCT * t
    )
    return KillVerdict(
        fp_flagged=fp_flagged,
        fp_n=fp_n,
        fp_upper=fp_upper,
        fp_pass=fp_pass,
        avg=avg,
        avg_pass=avg_pass,
        floor_pass=not failures,
        floor_failures=failures,
    )
