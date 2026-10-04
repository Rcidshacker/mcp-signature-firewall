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


def near_duplicate_pairs(texts: Sequence[str], threshold: float = NEAR_DUP_THRESHOLD) -> list[tuple[int, int, float]]:
    """Index pairs (i < j) whose n-gram Jaccard is at least the threshold. Exact duplicates score 1.0."""
    grams = [ngrams(t) for t in texts]
    pairs: list[tuple[int, int, float]] = []
    for i in range(len(grams)):
        for j in range(i + 1, len(grams)):
            score = jaccard(grams[i], grams[j])
            if score >= threshold:
                pairs.append((i, j, score))
    return pairs
