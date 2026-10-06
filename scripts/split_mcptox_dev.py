"""Key-based split of MCPTox into its dev part (author-authorised 2026-10-07).

Invariant: pure_tool.json loaded into memory by a key-based splitter; non-T1/T2 rows discarded before any inspection,
logging, writing, or model call.

The only field read from a row before the decision is `paradigm`. Rows of other paradigms are dropped unread, and only
row counts per paradigm are logged. The kept rows are also restricted to the ids the split manifest lists as dev, which
reproduces the corpus dedupe (held-out wins) from ids alone, with no text comparison.
Usage: split_mcptox_dev.py [SRC] [OUT] [MANIFEST] [LOG]
"""

import json
import sys
from collections import Counter
from pathlib import Path

KEEP = {"Template-1": "mcptox_t1", "Template-2": "mcptox_t2"}
INVARIANT = (
    "pure_tool.json loaded into memory by a key-based splitter; non-T1/T2 rows discarded before any inspection, "
    "logging, writing, or model call."
)


def split(src: Path, out: Path, manifest: Path, log: Path) -> dict[str, int]:
    dev_ids = {i["id"] for i in json.loads(manifest.read_text(encoding="utf-8"))["items"] if i["split"] == "dev"}
    data = json.loads(src.read_text(encoding="utf-8"))
    seen: Counter[str] = Counter()
    kept: list[dict[str, str]] = []
    for block in data:
        for key, rec in block.items():
            paradigm = rec.get("paradigm") if isinstance(rec, dict) else None
            if not isinstance(paradigm, str):
                raise SystemExit(f"stop: row {key!r} has no plain 'paradigm' field")
            seen[paradigm] += 1
            if paradigm not in KEEP or f"mcptox/{key}" not in dev_ids:
                continue  # dropped unread
            kept.append(
                {
                    "id": f"mcptox/{key}",
                    "family": KEEP[paradigm],
                    "channel": "tool_description",
                    "label": "attack",
                    "text": rec["tool_content"],
                }
            )
    del data
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in kept), encoding="utf-8", newline="\n")
    counts = {"kept_" + k: sum(r["family"] == k for r in kept) for k in KEEP.values()}
    counts.update({"seen_" + k: v for k, v in sorted(seen.items())})
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8", newline="\n") as f:
        f.write(f"{src.as_posix()}  ({INVARIANT})\n")
        f.write(f"  row counts by paradigm key: {json.dumps(counts, sort_keys=True)}\n")
        f.write(f"{manifest.as_posix()}  (ids only)\n{out.as_posix()}  (written)\n")
    return counts


if __name__ == "__main__":
    a = sys.argv[1:]
    paths = [Path(p) for p in (a + [""] * 4)[:4]]
    src = paths[0] if a else Path("data/raw/mcptox/pure_tool.json")
    dst = paths[1] if len(a) > 1 else Path("data/raw/mcptox/dev_t1_t2.jsonl")
    man = paths[2] if len(a) > 2 else Path("data/manifest/split_v1.json")
    lg = paths[3] if len(a) > 3 else Path("docs/ablation/run-log.txt")
    print(json.dumps(split(src, dst, man, lg), sort_keys=True))
