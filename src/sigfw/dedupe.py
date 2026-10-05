"""Exact and near-duplicate removal (char-5-gram Jaccard 0.85). Held-out families win every conflict."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sigfw.items import HELD_OUT, Item
from sigfw.textsim import NEAR_DUP_THRESHOLD, jaccard, ngrams


@dataclass(frozen=True)
class Dropped:
    id: str
    family: str
    reason: str  # exact | near
    of: str  # id of the kept item it duplicates
    score: float


def _exact_key(text: str) -> str:
    return hashlib.sha256(" ".join(text.split()).casefold().encode("utf-8", "surrogatepass")).hexdigest()


def dedupe(items: list[Item], threshold: float = NEAR_DUP_THRESHOLD) -> tuple[list[Item], list[Dropped]]:
    """Process held-out items first, then the rest, each in id order, so the result does not depend on input order."""
    ordered = sorted(items, key=lambda i: (i.family not in HELD_OUT, i.id))
    kept: list[Item] = []
    kept_grams: list[frozenset[str]] = []
    exact: dict[str, str] = {}
    dropped: list[Dropped] = []
    for item in ordered:
        key = _exact_key(item.text)
        if key in exact:
            dropped.append(Dropped(item.id, item.family, "exact", exact[key], 1.0))
            continue
        grams = ngrams(item.text)
        match: tuple[str, float] | None = None
        for other, other_grams in zip(kept, kept_grams, strict=True):
            lo, hi = sorted((len(grams), len(other_grams)))
            if hi and lo / hi < threshold:  # Jaccard cannot reach the threshold when the sizes differ this much
                continue
            score = jaccard(grams, other_grams)
            if score >= threshold:
                match = (other.id, score)
                break
        if match:
            dropped.append(Dropped(item.id, item.family, "near", match[0], match[1]))
            continue
        kept.append(item)
        kept_grams.append(grams)
        exact[key] = item.id
    return kept, dropped
