"""Handlers for `sigfw data stats | split | leakage-check`. They print counts, ids and hashes, never dataset text."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from sigfw import quoting
from sigfw.dedupe import Dropped, dedupe
from sigfw.items import HELD_OUT, Item, LoaderError, canonicalize, load_all, load_third_party
from sigfw.owndata import CHANNEL, CLAUSE_POSITIONS, FAMILY, MIN_N, check_shadowing
from sigfw.split import build_manifest, find_leaks, verify_manifest

DEV_FLOOR = 30  # design aim: about 10 families with 30 or more examples each after dedupe
FROZEN_FLOOR = 20  # ADR 0001: held-out families under 20 are exempt from the 70% floor


def _build(raw: Path, shadowing: Path) -> tuple[list[Item], list[Dropped]]:
    return dedupe(canonicalize(load_all(raw, shadowing)))


def stats(raw: Path, shadowing: Path) -> int:
    """Per-family counts before and after dedupe. Works without the shadowing set and says so."""
    try:
        items = load_all(raw, shadowing)
        note = None
    except LoaderError as e:
        if "shadowing" not in str(e):
            print(f"ERROR {e}")
            return 1
        items, note = load_third_party(raw), f"shadowing set not usable ({e}); counts below exclude it"
    kept, dropped = dedupe(canonicalize(items))
    before, after = Counter(i.family for i in items), Counter(i.family for i in kept)
    for fam in sorted(before):
        side = "frozen" if fam in HELD_OUT else "dev"
        floor = FROZEN_FLOOR if side == "frozen" else DEV_FLOOR
        flag = f"  WARN under {floor}" if after[fam] < floor else ""
        print(f"{fam:28s} {side:6s} before={before[fam]:5d} after={after[fam]:5d}{flag}")
    reasons = Counter(d.reason for d in dropped)
    print(f"dropped exact={reasons['exact']} near={reasons['near']}")
    heldout = len({i.family for i in kept if i.family in HELD_OUT})
    print(f"STATS items={len(kept)} families={len(after)} heldout={heldout}")
    if note:
        print(f"NOTE {note}")
    return 0


def _ask(label: str, allowed: tuple[str, ...] | None = None) -> str:
    while True:
        answer = input(f"{label}: ").strip()
        if not answer:
            print(f"{label} must not be empty")
        elif allowed and answer not in allowed:
            print(f"{label} must be one of {'|'.join(allowed)}")
        else:
            return answer


def _ask_text() -> str:
    """Multi-line text, exactly as typed, ended by a line containing only a full stop."""
    while True:
        lines = [input("text (finish with a line containing only .): ")]
        while lines[-1] != ".":
            lines.append(input())
        text = "\n".join(lines[:-1])
        if text.strip():
            return text
        print("text must not be empty")


def add_own(path: Path) -> int:
    """Append one author=human row from typed answers. Never generates, suggests or edits text."""
    try:
        row = {
            "id": _ask("id"),
            "author": "human",
            "channel": CHANNEL,
            "family": FAMILY,
            "technique": _ask("technique"),
            "clause_position": _ask("clause_position", CLAUSE_POSITIONS),
            "host_tool": _ask("host_tool"),
            "target_tool": _ask("target_tool"),
            "text": _ask_text(),
        }
    except EOFError:
        print("cancelled: nothing written")
        return 1
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    prefix = "\n" if existing and not existing.endswith("\n") else ""
    line = json.dumps(row, ensure_ascii=False)
    report = check_shadowing(existing + prefix + line + "\n")
    blocking = [e for e in report.errors if not e.startswith("n=")]  # n below the minimum is expected while writing
    if blocking:
        for e in blocking:
            print(f"ERROR {e}")
        print("nothing written")
        return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(prefix + line + "\n")
    print(f"ADDED id={row['id']}")
    print(f"shadowing n={report.n}")
    if report.n < MIN_N:
        print(f"NOTE {MIN_N - report.n} more row(s) needed to reach {MIN_N}")
    return 0


def _dump(manifest: dict[str, Any]) -> str:
    return json.dumps(manifest, sort_keys=True, indent=1, ensure_ascii=False) + "\n"


def shadowing_info(shadowing: Path, kept: list[Item]) -> dict[str, Any]:
    """Author counts of the shadowing family, the pinned commit and the G-set source hash (when those files exist)."""
    info: dict[str, Any] = {"authors": dict(sorted(Counter(i.author for i in kept if i.family == "shadowing").items()))}
    commit_file = shadowing.with_name("shadowing.commit")
    if commit_file.is_file():
        commit = commit_file.read_text(encoding="utf-8").strip()
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise LoaderError(f"{commit_file} must hold a full 40-character commit hash")
        info["commit"] = commit
    gset = shadowing.parent / "sources" / "gset_v1.json"
    if gset.is_file():
        info["gset_v1_sha256"] = hashlib.sha256(gset.read_bytes()).hexdigest()
    return info


def split(raw: Path, shadowing: Path, manifest_path: Path, *, verify: bool) -> int:
    try:
        kept, dropped = _build(raw, shadowing)
        fresh = build_manifest(kept, dropped, shadowing_info(shadowing, kept))
    except LoaderError as e:
        print(f"ERROR {e}")
        return 1
    if not verify:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(_dump(fresh), encoding="utf-8", newline="\n")
        print(f"SPLIT_WRITTEN items={len(kept)} manifest={manifest_path}")
        return 0
    try:
        recorded = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"MANIFEST_FAIL {manifest_path} not found: run `sigfw data split` first")
        return 1
    ok, line = verify_manifest(recorded, kept)
    if ok and recorded != fresh:
        ok, line = False, "MANIFEST_FAIL the manifest differs from a fresh rebuild (dropped list, pins or parameters)"
    print(line)
    return 0 if ok else 1


def leakage(raw: Path, shadowing: Path, manifest_path: Path) -> int:
    try:
        kept, _ = _build(raw, shadowing)
        recorded = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (LoaderError, FileNotFoundError) as e:
        print(f"ERROR {e}")
        return 1
    ok, line = verify_manifest(recorded, kept)  # the check is only meaningful on the data the manifest describes
    if not ok:
        print(line)
        return 1
    leaks = find_leaks(kept, {r["id"]: r["split"] for r in recorded["items"]})
    for dev_id, frozen_id, score in leaks:
        print(f"LEAK {dev_id} ~ {frozen_id} jaccard={score:.2f}")
    print(f"LEAK={len(leaks)}")
    return 0 if not leaks else 1


def check_quoting(slice_name: str, own_dir: Path, raw: Path, shadowing: Path) -> int:
    """Validate one quoting slice. The held-out attack text is read only to look for shared 30-character stretches."""
    path = own_dir / f"quoting_{slice_name}.jsonl"
    if not path.is_file():
        print(f"quoting slice={slice_name} n=0")
        print(f"ERROR file not found: {path}")
        return 1
    try:
        items = load_all(raw, shadowing)  # the overlap check needs every held-out family
    except LoaderError as e:
        print(f"ERROR cannot check overlap with held-out attacks: {e}")
        return 1
    windows = quoting.attack_windows(quoting.heldout_attacks(items))
    raws = {s: quoting.read(own_dir / f"quoting_{s}.jsonl") for s in quoting.SLICES}
    report = quoting.check_slice(slice_name, raws, windows)
    print(f"quoting slice={slice_name} n={report.n}")
    for line in report.summary:
        print(line)
    for prefix, lines in (("NOTE", report.notes), ("WARN", report.warnings), ("ERROR", report.errors)):
        for line in lines:
            print(f"{prefix} {line}")
    if report.ok:
        print(f"QUOTING_OK slice={slice_name}")
    return 0 if report.ok else 1
