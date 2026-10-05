"""Regenerate the 35 G-set texts of data/own/shadowing.jsonl from data/own/sources/gset_v1.json.

Composition rule (ADR 0001, Amendment 6): host description, then the clause, joined by one space. For rows with a
fenced block (the 7.x rows): description, blank line, fenced block, blank line, clause. Nothing is edited or
paraphrased; the script only joins the received fields.

    python scripts/compose_shadowing.py            # check: composed texts must equal the texts in shadowing.jsonl
    python scripts/compose_shadowing.py --emit     # print the composed texts as a JSON object {id: text}
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

SOURCE = Path("data/own/sources/gset_v1.json")
SHADOWING = Path("data/own/shadowing.jsonl")


def compose_text(rec: dict[str, Any]) -> str:
    if rec["fenced_block"]:
        return f"{rec['host_description']}\n\n{rec['fenced_block']}\n\n{rec['clause']}"
    return f"{rec['host_description']} {rec['clause']}"


def composed(source: Path = SOURCE) -> dict[str, str]:
    doc = json.loads(source.read_text(encoding="utf-8"))
    return {rec["id"]: compose_text(rec) for rec in doc["rows"]}


def check(source: Path = SOURCE, shadowing: Path = SHADOWING) -> list[str]:
    """Problems found comparing the composed texts with the gpt G-set rows in shadowing.jsonl (empty when equal)."""
    texts = composed(source)
    rows = [json.loads(ln) for ln in shadowing.read_text(encoding="utf-8").split("\n") if ln.strip()]
    # Only the ids present in the source are compared; C01, C02 and the human rows are not part of the G-set.
    by_id = {r["id"]: r for r in rows}
    problems = [f"{i}: missing from {shadowing}" for i in texts if i not in by_id]
    problems += [
        f"{i}: text differs from the composed text" for i, t in texts.items() if i in by_id and by_id[i]["text"] != t
    ]
    return problems


def main(argv: list[str]) -> int:
    if argv == ["--emit"]:
        print(json.dumps(composed(), ensure_ascii=False, indent=1))
        return 0
    if argv:
        print("usage: compose_shadowing.py [--emit]", file=sys.stderr)
        return 2
    problems = check()
    for p in problems:
        print(f"ERROR {p}")
    if problems:
        return 1
    digest = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    print(f"COMPOSE_OK rows={len(composed())} source_sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
