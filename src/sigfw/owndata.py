"""Validation of the hand-written own-data files. Currently only the tool-shadowing set (data/own/shadowing.jsonl).

Rows whose id starts with TEMPLATE are schema-checked but never counted, so a forgotten placeholder cannot
inflate n or form a duplicate pair.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field

from sigfw.textsim import near_duplicate_pairs

CHANNEL = "tool_description"
FAMILY = "shadowing"
FIELDS = frozenset({"id", "channel", "family", "text", "technique", "placement", "length_bucket"})
PLACEMENTS = ("start", "middle", "end")
LENGTH_BUCKETS = ("short", "medium", "long")
TEMPLATE_PREFIX = "TEMPLATE"
MIN_N = 35  # Amendment 2: 35 written so that 30 or more survive dedupe
MIN_TECHNIQUES = 5  # spread warnings, never failures
MIN_PER_BUCKET = 5
MAX_TECHNIQUE_SHARE = 0.30


@dataclass
class Report:
    n: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _validate(row: object) -> tuple[dict[str, str] | None, list[str]]:
    if not isinstance(row, dict):
        return None, ["row is not a JSON object"]
    problems = [f"missing field {k!r}" for k in sorted(FIELDS - row.keys())]
    problems += [f"unknown field {k!r}" for k in sorted(row.keys() - FIELDS)]
    problems += [f"{k} must be a string" for k in sorted(FIELDS & row.keys()) if not isinstance(row[k], str)]
    if problems:
        return None, problems
    if not row["id"].strip():
        problems.append("id must not be empty")
    if not row["text"].strip():
        problems.append("text must not be empty")
    if not row["technique"].strip():
        problems.append("technique must not be empty")
    if row["channel"] != CHANNEL:
        problems.append(f"channel must be {CHANNEL!r}")
    if row["family"] != FAMILY:
        problems.append(f"family must be {FAMILY!r}")
    if row["placement"] not in PLACEMENTS:
        problems.append(f"placement must be one of {'|'.join(PLACEMENTS)}")
    if row["length_bucket"] not in LENGTH_BUCKETS:
        problems.append(f"length_bucket must be one of {'|'.join(LENGTH_BUCKETS)}")
    return (None, problems) if problems else (row, [])


def _spread_warnings(rows: list[dict[str, str]]) -> list[str]:
    out: list[str] = []
    techniques = Counter(r["technique"].strip().casefold() for r in rows)
    if len(techniques) < MIN_TECHNIQUES:
        out.append(f"only {len(techniques)} distinct technique values (want at least {MIN_TECHNIQUES})")
    name, count = techniques.most_common(1)[0]
    if count / len(rows) > MAX_TECHNIQUE_SHARE:
        out.append(f"technique {name!r} is {count}/{len(rows)} rows (want at most {MAX_TECHNIQUE_SHARE:.0%})")
    for key, values in (("placement", PLACEMENTS), ("length_bucket", LENGTH_BUCKETS)):
        counts = Counter(r[key] for r in rows)
        thin = [f"{v}={counts[v]}" for v in values if counts[v] < MIN_PER_BUCKET]
        if thin:
            out.append(f"thin {key} spread: {', '.join(thin)} (want at least {MIN_PER_BUCKET} each)")
    return out


def check_shadowing(raw: str) -> Report:
    report = Report()
    rows: list[tuple[int, dict[str, str]]] = []
    templates = 0
    for no, line in enumerate(raw.split("\n"), start=1):
        line = line.rstrip("\r")
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except ValueError as e:
            report.errors.append(f"line {no}: invalid JSON ({e})")
            continue
        row, problems = _validate(parsed)
        report.errors += [f"line {no}: {p}" for p in problems]
        if row is None:
            continue
        if row["id"].startswith(TEMPLATE_PREFIX):
            templates += 1
        else:
            rows.append((no, row))
    if templates:
        report.notes.append(f"{templates} {TEMPLATE_PREFIX} row(s) ignored")

    seen: dict[str, int] = {}
    for no, row in rows:
        if row["id"] in seen:
            report.errors.append(f"line {no}: duplicate id {row['id']!r} (first on line {seen[row['id']]})")
        seen.setdefault(row["id"], no)
    # Rows with a duplicated id are not counted again, so n reflects distinct valid rows.
    unique = [(no, row) for no, row in rows if seen[row["id"]] == no]
    report.n = len(unique)

    for i, j, score in near_duplicate_pairs([row["text"] for _, row in unique]):
        kind = "exact duplicate" if score == 1.0 else "near-duplicate"
        a, b = unique[i][1]["id"], unique[j][1]["id"]
        report.errors.append(f"{kind}: {a} and {b} (char-5-gram Jaccard {score:.2f})")
    if report.n < MIN_N:
        report.errors.append(f"n={report.n} is below the required {MIN_N}")
    if unique:
        report.warnings = _spread_warnings([row for _, row in unique])
    return report
