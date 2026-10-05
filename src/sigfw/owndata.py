"""Validation of the own-data files. Currently only the tool-shadowing set (data/own/shadowing.jsonl).

The set has two authorship slices (ADR 0001, Amendment 5): author=gpt (model-authored) and author=human. Rows whose
technique is TEMPLATE are schema-checked but never counted, so a forgotten placeholder cannot inflate n or form a
duplicate pair. word_count and length_bucket are computed from the text and must never be stored in the file.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field

from sigfw.textsim import NEAR_DUP_THRESHOLD, pair_scores

CHANNEL = "tool_description"
FAMILY = "shadowing"
FIELDS = frozenset(
    {"id", "author", "channel", "family", "technique", "clause_position", "host_tool", "target_tool", "text"}
)
AUTHORS = ("human", "gpt")
CLAUSE_POSITIONS = ("start", "middle", "end")
LENGTH_BUCKETS = ("short", "medium", "long")
SHORT_MAX_WORDS = 25  # short <= 25 words, medium 26-45, long >= 46
MEDIUM_MAX_WORDS = 45
TEMPLATE_TECHNIQUE = "TEMPLATE"
MIN_N = 35  # Amendment 2: at least 35 rows so that 30 or more survive dedupe
MIN_TECHNIQUES = 5  # technique-spread warnings, never failures
MAX_TECHNIQUE_SHARE = 0.30
CLOSEST_PAIRS = 5


def length_bucket(text: str) -> str:
    words = len(text.split())
    if words <= SHORT_MAX_WORDS:
        return "short"
    return "medium" if words <= MEDIUM_MAX_WORDS else "long"


@dataclass
class Report:
    n: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    summary: list[str] = field(default_factory=list)

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
    for name in ("id", "text", "technique", "host_tool", "target_tool"):
        if not row[name].strip():
            problems.append(f"{name} must not be empty")
    if row["author"] not in AUTHORS:
        problems.append(f"author must be one of {'|'.join(AUTHORS)}")
    if row["channel"] != CHANNEL:
        problems.append(f"channel must be {CHANNEL!r}")
    if row["family"] != FAMILY:
        problems.append(f"family must be {FAMILY!r}")
    if row["clause_position"] not in CLAUSE_POSITIONS:
        problems.append(f"clause_position must be one of {'|'.join(CLAUSE_POSITIONS)}")
    return (None, problems) if problems else (row, [])


def _technique_warnings(rows: list[dict[str, str]]) -> list[str]:
    out: list[str] = []
    techniques = Counter(r["technique"].strip().casefold() for r in rows)
    if len(techniques) < MIN_TECHNIQUES:
        out.append(f"only {len(techniques)} distinct technique values (want at least {MIN_TECHNIQUES})")
    name, count = techniques.most_common(1)[0]
    if count / len(rows) > MAX_TECHNIQUE_SHARE:
        out.append(f"technique {name!r} is {count}/{len(rows)} rows (want at most {MAX_TECHNIQUE_SHARE:.0%})")
    return out


def _counts_line(label: str, counts: Counter[str], order: tuple[str, ...] | None = None) -> str:
    keys = list(order) if order else sorted(counts)
    return f"{label}: " + " ".join(f"{k}={counts[k]}" for k in keys)


def _summary(rows: list[dict[str, str]], scores: list[tuple[int, int, float]]) -> list[str]:
    buckets = [length_bucket(r["text"]) for r in rows]
    out = [
        _counts_line("author", Counter(r["author"] for r in rows), AUTHORS),
        _counts_line("technique", Counter(r["technique"].strip().casefold() for r in rows)),
        _counts_line("length_bucket", Counter(buckets), LENGTH_BUCKETS),
        _counts_line("clause_position", Counter(r["clause_position"] for r in rows), CLAUSE_POSITIONS),
        "length_bucket x clause_position:",
    ]
    cross = Counter(zip(buckets, (r["clause_position"] for r in rows), strict=True))
    for bucket in LENGTH_BUCKETS:
        out.append(f"  {bucket}: " + " ".join(f"{pos}={cross[(bucket, pos)]}" for pos in CLAUSE_POSITIONS))
    ranked = sorted(scores, key=lambda s: (-s[2], s[0], s[1]))[:CLOSEST_PAIRS]
    out.append(f"max_jaccard={ranked[0][2] if ranked else 0.0:.2f}")
    closest = "; ".join(f"{rows[i]['id']} {rows[j]['id']} {score:.2f}" for i, j, score in ranked)
    out.append(f"closest: {closest or 'none'}")
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
        if row["technique"].strip() == TEMPLATE_TECHNIQUE:
            templates += 1
        else:
            rows.append((no, row))
    if templates:
        report.notes.append(f"{templates} {TEMPLATE_TECHNIQUE} row(s) ignored")

    seen: dict[str, int] = {}
    for no, row in rows:
        if row["id"] in seen:
            report.errors.append(f"line {no}: duplicate id {row['id']!r} (first on line {seen[row['id']]})")
        seen.setdefault(row["id"], no)
    # Rows with a duplicated id are not counted again, so n reflects distinct valid rows.
    unique = [row for no, row in rows if seen[row["id"]] == no]
    report.n = len(unique)

    scores = pair_scores([row["text"] for row in unique])  # across all rows, whatever the author
    for i, j, score in scores:
        if score >= NEAR_DUP_THRESHOLD:
            kind = "exact duplicate" if score == 1.0 else "near-duplicate"
            report.errors.append(f"{kind}: {unique[i]['id']} and {unique[j]['id']} (char-5-gram Jaccard {score:.2f})")
    if report.n < MIN_N:
        report.errors.append(f"n={report.n} is below the required {MIN_N}")
    if unique:
        report.summary = _summary(unique, scores)
        report.warnings = _technique_warnings(unique)
    return report
