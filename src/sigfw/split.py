"""Split manifest, its verification and the leakage check. Held-out families are the frozen set; the rest is dev."""

from __future__ import annotations

import hashlib
from collections import Counter
from typing import Any

from sigfw.dedupe import Dropped
from sigfw.items import HELD_OUT, Item
from sigfw.sources import PINS
from sigfw.textnorm import NORMALIZER_VERSION
from sigfw.textsim import NEAR_DUP_THRESHOLD, NGRAM, jaccard, ngrams

MANIFEST_VERSION = 1


def split_of(item: Item) -> str:
    return "frozen" if item.family in HELD_OUT else "dev"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def build_manifest(kept: list[Item], dropped: list[Dropped]) -> dict[str, Any]:
    """Ids, families, splits and hashes only: no third-party text. Same input gives the same manifest."""
    counts = Counter(i.family for i in kept)
    return {
        "manifest_version": MANIFEST_VERSION,
        "normalizer_version": NORMALIZER_VERSION,
        "ngram": NGRAM,
        "near_dup_threshold": NEAR_DUP_THRESHOLD,
        "heldout_families": sorted(HELD_OUT),
        "source_pins": [
            {"source": p.source, "repo": p.repo, "commit": p.commit, "path": p.path, "blob_sha": p.blob_sha}
            for p in PINS
        ],
        "families": {
            fam: {"split": "frozen" if fam in HELD_OUT else "dev", "count": counts[fam]} for fam in sorted(counts)
        },
        "items": [
            {
                "id": i.id,
                "source": i.source,
                "family": i.family,
                "channel": i.channel,
                "label": i.label,
                "split": split_of(i),
                "sha256": _sha(i.text),
            }
            for i in sorted(kept, key=lambda i: i.id)
        ],
        "dropped": [
            {"id": d.id, "family": d.family, "reason": d.reason, "of": d.of, "score": round(d.score, 4)}
            for d in sorted(dropped, key=lambda d: d.id)
        ],
    }


def verify_manifest(manifest: dict[str, Any], kept: list[Item]) -> tuple[bool, str]:
    recorded = {r["id"]: r for r in manifest["items"]}
    actual = {i.id: i for i in kept}
    problems = [f"{i} is in the manifest but not in the data" for i in sorted(recorded.keys() - actual.keys())]
    problems += [f"{i} is in the data but not in the manifest" for i in sorted(actual.keys() - recorded.keys())]
    for i in sorted(recorded.keys() & actual.keys()):
        item, rec = actual[i], recorded[i]
        if _sha(item.text) != rec["sha256"]:
            problems.append(f"{i}: text hash differs from the manifest")
        elif (item.family, item.channel, item.label, split_of(item)) != (
            rec["family"],
            rec["channel"],
            rec["label"],
            rec["split"],
        ):
            problems.append(f"{i}: family, channel, label or split differs from the manifest")
    heldout = len({r["family"] for r in manifest["items"] if r["family"] in HELD_OUT})
    if heldout != len(HELD_OUT):
        problems.append(f"heldout={heldout}, expected {len(HELD_OUT)}")
    if problems:
        more = f" (+{len(problems) - 5} more)" if len(problems) > 5 else ""
        return False, "MANIFEST_FAIL " + "; ".join(problems[:5]) + more
    families = len({r["family"] for r in manifest["items"]})
    return True, f"MANIFEST_OK items={len(recorded)} families={families} heldout={heldout}"


def find_leaks(items: list[Item], split_by_id: dict[str, str]) -> list[tuple[str, str, float]]:
    """Every (dev id, frozen id, score) pair that is an exact or near duplicate. Independent of the dedupe pass."""
    dev = [(i.id, ngrams(i.text)) for i in items if split_by_id[i.id] == "dev"]
    frozen = [(i.id, ngrams(i.text)) for i in items if split_by_id[i.id] == "frozen"]
    leaks = []
    for d_id, d_grams in dev:
        for f_id, f_grams in frozen:
            score = jaccard(d_grams, f_grams)
            if score >= NEAR_DUP_THRESHOLD:
                leaks.append((d_id, f_id, score))
    return sorted(leaks)
