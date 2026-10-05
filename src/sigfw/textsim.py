"""Character n-gram similarity, shared by the own-data checks and the dataset dedupe."""

from __future__ import annotations

from collections.abc import Sequence

NGRAM = 5
NEAR_DUP_THRESHOLD = 0.85


def ngrams(text: str, n: int = NGRAM) -> frozenset[str]:
    """Character n-grams of the case-folded, whitespace-collapsed text. Text shorter than n is one gram."""
    t = " ".join(text.split()).casefold()
    if len(t) < n:
        return frozenset({t}) if t else frozenset()
    return frozenset(t[i : i + n] for i in range(len(t) - n + 1))


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def pair_scores(texts: Sequence[str]) -> list[tuple[int, int, float]]:
    """Jaccard score of every index pair (i < j). Exact duplicates score 1.0."""
    grams = [ngrams(t) for t in texts]
    return [(i, j, jaccard(grams[i], grams[j])) for i in range(len(grams)) for j in range(i + 1, len(grams))]
