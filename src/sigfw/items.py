"""Canonical evaluation items and the loaders that build them from the raw dataset files and our own text."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from sigfw.owndata import TEMPLATE_TECHNIQUE, check_shadowing
from sigfw.textnorm import normalize

# Held-out families (ADR 0001): never in the dev set or the signature library. "bipia_text" is all 15 BIPIA text
# attack categories; the ADR's "goal-based text attacks" does not name a subset.
HELD_OUT = frozenset({"mcptox_t3", "bipia_code", "bipia_text", "shadowing"})
_PARADIGMS = {"Template-1": "mcptox_t1", "Template-2": "mcptox_t2", "Template-3": "mcptox_t3"}
_INJECAGENT_VARIANTS = ("dh_base", "dh_enhanced", "ds_base", "ds_enhanced")


class LoaderError(ValueError):
    pass


@dataclass(frozen=True)
class Item:
    id: str
    source: str
    family: str
    channel: str  # tool_description | tool_result
    label: str  # attack (benign items arrive with the quoting slices)
    text: str


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise LoaderError(f"{path} not found: run `sigfw data fetch`") from e
    except ValueError as e:
        raise LoaderError(f"{path} is not valid JSON") from e


def _load_mcptox(raw: Path) -> list[Item]:
    items: list[Item] = []
    for block in _read_json(raw / "mcptox" / "pure_tool.json"):
        for key, rec in block.items():
            paradigm = rec.get("paradigm")
            if paradigm not in _PARADIGMS:
                raise LoaderError(f"mcptox entry {key}: unknown paradigm {paradigm!r}")
            family = _PARADIGMS[paradigm]
            items.append(Item(f"mcptox/{key}", "mcptox", family, "tool_description", "attack", rec["tool_content"]))
    return items


def _load_bipia(raw: Path) -> list[Item]:
    items: list[Item] = []
    for kind in ("code", "text"):
        for split in ("train", "test"):
            data = _read_json(raw / "bipia" / f"{kind}_attack_{split}.json")
            for category, texts in data.items():
                for n, text in enumerate(texts):
                    item_id = f"bipia/{kind}/{split}/{category}/{n}"
                    items.append(Item(item_id, "bipia", f"bipia_{kind}", "tool_result", "attack", text))
    return items


def _load_injecagent(raw: Path) -> list[Item]:
    items: list[Item] = []
    for variant in _INJECAGENT_VARIANTS:
        for n, rec in enumerate(_read_json(raw / "injecagent" / f"test_cases_{variant}.json")):
            family = f"injecagent_{variant}"
            items.append(
                Item(f"injecagent/{variant}/{n}", "injecagent", family, "tool_result", "attack", rec["Tool Response"])
            )
    return items


def load_shadowing(path: Path) -> list[Item]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise LoaderError(f"shadowing set not found at {path}: the author writes it (data/own/README.md)") from e
    report = check_shadowing(raw)
    if not report.ok:
        raise LoaderError(f"shadowing set fails check-own: {report.errors[0]}")
    rows = [json.loads(line) for line in raw.split("\n") if line.strip()]
    return [
        Item(f"own/shadowing/{r['id']}", "own", "shadowing", "tool_description", "attack", r["text"])
        for r in rows
        if r["technique"].strip() != TEMPLATE_TECHNIQUE
    ]


def load_third_party(raw_dir: Path) -> list[Item]:
    return _load_mcptox(raw_dir) + _load_bipia(raw_dir) + _load_injecagent(raw_dir)


def load_all(raw_dir: Path, shadowing_path: Path) -> list[Item]:
    items = load_third_party(raw_dir) + load_shadowing(shadowing_path)
    if len({i.id for i in items}) != len(items):
        raise LoaderError("duplicate item ids across loaders")
    return items


def canonicalize(items: list[Item]) -> list[Item]:
    return [replace(i, text=normalize(i.text)) for i in items]
