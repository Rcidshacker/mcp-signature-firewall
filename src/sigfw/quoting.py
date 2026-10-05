"""Quoting-slice files and their validator (ADR 0001, Amendment 8).

The quoting slice is benign text that quotes or discusses attacks. The frozen slice (exactly 200 items) is the only
slice that gates the kill rule; the dev slice (about 50) is for tuning. Rows whose id starts with TEMPLATE are
schema-checked but ignored. The validator reports ids only, never the text of an overlapping attack.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from sigfw.items import HELD_OUT, Item
from sigfw.textnorm import normalize
from sigfw.textsim import NEAR_DUP_THRESHOLD, pair_scores

FIELDS = frozenset({"id", "author", "slice", "source_type", "form", "channel", "reviewed", "text"})
AUTHORS = ("human", "nemotron-super")
SLICES = ("frozen", "dev")
SOURCE_TYPES = (
    "security_blog",
    "github_issue",
    "docs",
    "ctf_writeup",
    "test_fixture",
    "readme_warning",
    "postmortem",
    "code_comment",
    "tool_description_warning",
    "forum_post",
)
FORMS = ("verbatim_quote", "discussion")
CHANNELS = ("tool_description", "tool_result", "other")
TEMPLATE_PREFIX = "TEMPLATE"
FROZEN_N = 200
DEV_RANGE = (40, 60)
OVERLAP_WINDOW = 30
MAX_SOURCE_SHARE = 0.20
VERBATIM_RANGE = (0.40, 0.60)
CLOSEST_PAIRS = 5


@dataclass
class Row:
    id: str
    slice: str
    author: str
    source_type: str
    form: str
    channel: str
    reviewed: bool
    text: str


@dataclass
class Report:
    slice: str
    n: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    summary: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _validate(row: object) -> tuple[Row | None, list[str]]:
    if not isinstance(row, dict):
        return None, ["row is not a JSON object"]
    problems = [f"missing field {k!r}" for k in sorted(FIELDS - row.keys())]
    problems += [f"unknown field {k!r}" for k in sorted(row.keys() - FIELDS)]
    if problems:
        return None, problems
    for name in ("id", "author", "slice", "source_type", "form", "channel", "text"):
        if not isinstance(row[name], str):
            problems.append(f"{name} must be a string")
    if not isinstance(row["reviewed"], bool):
        problems.append("reviewed must be true or false")
    if problems:
        return None, problems
    if not row["id"].strip():
        problems.append("id must not be empty")
    if not row["text"].strip():
        problems.append("text must not be empty")
    for name, allowed in (
        ("author", AUTHORS),
        ("slice", SLICES),
        ("source_type", SOURCE_TYPES),
        ("form", FORMS),
        ("channel", CHANNELS),
    ):
        if row[name] not in allowed:
            problems.append(f"{name} must be one of {'|'.join(allowed)}")
    if problems:
        return None, problems
    return Row(**{k: row[k] for k in FIELDS}), []


def parse(raw: str, expected_slice: str, errors: list[str]) -> tuple[list[tuple[int, Row]], int]:
    """Rows (with line numbers) and the count of ignored TEMPLATE rows. Problems are appended to errors."""
    rows: list[tuple[int, Row]] = []
    templates = 0
    for no, line in enumerate(raw.split("\n"), start=1):
        line = line.rstrip("\r")
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except ValueError as e:
            errors.append(f"line {no}: invalid JSON ({e})")
            continue
        row, problems = _validate(parsed)
        errors.extend(f"line {no}: {p}" for p in problems)
        if row is None:
            continue
        if row.slice != expected_slice:
            errors.append(f"line {no}: slice must be {expected_slice!r} in this file")
            continue
        if row.id.startswith(TEMPLATE_PREFIX):
            templates += 1
        else:
            rows.append((no, row))
    return rows, templates


def _squash(text: str) -> str:
    return " ".join(normalize(text).split()).casefold()


def attack_windows(attacks: list[Item]) -> dict[str, str]:
    """Every OVERLAP_WINDOW-character stretch of every attack text, mapped to the id of the item it came from."""
    windows: dict[str, str] = {}
    for item in attacks:
        text = _squash(item.text)
        for i in range(max(1, len(text) - OVERLAP_WINDOW + 1)):
            windows.setdefault(text[i : i + OVERLAP_WINDOW], item.id)
    return windows


def heldout_attacks(items: list[Item]) -> list[Item]:
    return [i for i in items if i.family in HELD_OUT]


def _counts(label: str, counts: Counter[str], order: tuple[str, ...]) -> str:
    return f"{label}: " + " ".join(f"{k}={counts[k]}" for k in order)


def check_slice(
    slice_name: str,
    raws: dict[str, str],
    windows: dict[str, str],
) -> Report:
    """Validate one slice. raws maps each slice name to its file text (a missing file is an empty string); the other
    slice is read only for the cross-slice duplicate check."""
    report = Report(slice_name)
    parsed: dict[str, list[tuple[int, Row]]] = {}
    for name in SLICES:
        errors: list[str] = []
        parsed[name], templates = parse(raws.get(name, ""), name, errors)
        if name == slice_name:
            report.errors += errors
            if templates:
                report.notes.append(f"{templates} {TEMPLATE_PREFIX} row(s) ignored")
    seen: dict[str, int] = {}
    for no, row in parsed[slice_name]:
        if row.id in seen:
            report.errors.append(f"line {no}: duplicate id {row.id!r} (first on line {seen[row.id]})")
        seen.setdefault(row.id, no)
    mine = [row for no, row in parsed[slice_name] if seen[row.id] == no]
    report.n = len(mine)

    # duplicates within and across both slices; a pair fails this slice when it involves one of this slice's rows
    everyone = mine + [row for _, row in parsed[next(s for s in SLICES if s != slice_name)]]
    scores = pair_scores([r.text for r in everyone])
    mine_ids = {r.id for r in mine}
    for i, j, score in scores:
        a, b = everyone[i], everyone[j]
        if score >= NEAR_DUP_THRESHOLD and (a.id in mine_ids or b.id in mine_ids):
            kind = "exact duplicate" if score == 1.0 else "near-duplicate"
            report.errors.append(f"{kind}: {a.id} ({a.slice}) and {b.id} ({b.slice}) (Jaccard {score:.2f})")

    for row in mine:  # ids only: the overlapping attack text is never printed
        text = _squash(row.text)
        for k in range(max(1, len(text) - OVERLAP_WINDOW + 1)):
            hit = windows.get(text[k : k + OVERLAP_WINDOW])
            if hit:
                report.errors.append(f"overlap: {row.id} shares a {OVERLAP_WINDOW}-character stretch with {hit}")
                break

    if slice_name == "frozen":
        if report.n != FROZEN_N:
            report.errors.append(f"n={report.n}: the frozen slice must have exactly {FROZEN_N} rows")
        unreviewed = [r.id for r in mine if not r.reviewed]
        if unreviewed:
            shown = ", ".join(unreviewed[:5]) + (" ..." if len(unreviewed) > 5 else "")
            report.errors.append(f"{len(unreviewed)} row(s) not reviewed: {shown}")
    elif not DEV_RANGE[0] <= report.n <= DEV_RANGE[1]:
        report.errors.append(f"n={report.n}: the dev slice must have {DEV_RANGE[0]} to {DEV_RANGE[1]} rows")

    if mine:
        report.summary = _summary(mine, scores, everyone)
        report.warnings = _warnings(mine)
    return report


def _warnings(rows: list[Row]) -> list[str]:
    out: list[str] = []
    n = len(rows)
    for name, count in Counter(r.source_type for r in rows).items():
        if count / n > MAX_SOURCE_SHARE:
            out.append(f"source_type {name} is {count}/{n} rows (want at most {MAX_SOURCE_SHARE:.0%})")
    verbatim = sum(r.form == "verbatim_quote" for r in rows) / n
    if not VERBATIM_RANGE[0] <= verbatim <= VERBATIM_RANGE[1]:
        out.append(f"verbatim_quote share is {verbatim:.0%} (want {VERBATIM_RANGE[0]:.0%} to {VERBATIM_RANGE[1]:.0%})")
    human = sum(r.author == "human" for r in rows)
    if human * 3 < n:
        out.append(f"human share is {human}/{n} (want at least one third)")
    return out


def _summary(rows: list[Row], scores: list[tuple[int, int, float]], everyone: list[Row]) -> list[str]:
    out = [
        _counts("author", Counter(r.author for r in rows), AUTHORS),
        _counts("source_type", Counter(r.source_type for r in rows), SOURCE_TYPES),
        _counts("form", Counter(r.form for r in rows), FORMS),
        _counts("channel", Counter(r.channel for r in rows), CHANNELS),
        f"reviewed: true={sum(r.reviewed for r in rows)} false={sum(not r.reviewed for r in rows)}",
    ]
    ranked = sorted(scores, key=lambda s: (-s[2], s[0], s[1]))[:CLOSEST_PAIRS]
    out.append(f"max_jaccard={ranked[0][2] if ranked else 0.0:.2f}")
    closest = "; ".join(f"{everyone[i].id} {everyone[j].id} {score:.2f}" for i, j, score in ranked)
    out.append(f"closest: {closest or 'none'}")
    return out


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
