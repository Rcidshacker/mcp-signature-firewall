"""Seam: the committed classifier prompt file (prompts/classifier_v1.txt).

Independence guard (ADR 0001, Amendment 7): no 30-character stretch of any shadowing text may appear in the prompt.
This is a mechanical check, not proof of independence; the amendment states that limitation.
"""

from __future__ import annotations

import json
from pathlib import Path

from sigfw.classifier import CLOSE_TAG, OPEN_TAG, load_prompt, parse_verdict

ROOT = Path(__file__).resolve().parents[1]
PROMPT = ROOT / "prompts" / "classifier_v1.txt"
WINDOW = 30


def squash(text: str) -> str:
    return " ".join(text.split()).casefold()


def test_prompt_has_lf_endings_and_loads() -> None:
    raw = PROMPT.read_bytes()
    assert b"\r" not in raw and raw.endswith(b"\n")
    prompt = load_prompt(PROMPT)
    assert len(prompt.sha256) == 64 and prompt.text.startswith("You are a security classifier")


def test_prompt_names_the_fence_and_the_strict_reply_format() -> None:
    text = PROMPT.read_text(encoding="utf-8")
    assert OPEN_TAG in text and CLOSE_TAG in text
    for key in ('"verdict"', '"family"', '"span"'):
        assert key in text
    assert "ONE JSON object" in text


def test_the_prompts_own_example_reply_shapes_parse_under_the_strict_parser() -> None:
    # the two shapes the prompt asks for, written out by hand
    assert parse_verdict('{"verdict": "benign", "family": null, "span": null}').verdict == "benign"
    assert parse_verdict('{"verdict": "attack", "family": "tool_misuse", "span": "quoted"}').verdict == "attack"


def test_no_shadowing_text_appears_in_the_prompt() -> None:
    shadowing = ROOT / "data" / "own" / "shadowing.jsonl"
    prompt = squash(PROMPT.read_text(encoding="utf-8"))
    rows = [json.loads(ln) for ln in shadowing.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(rows) >= 35
    for row in rows:
        text = squash(row["text"])
        hits = [text[i : i + WINDOW] for i in range(max(1, len(text) - WINDOW + 1)) if text[i : i + WINDOW] in prompt]
        assert not hits, f"{row['id']} shares a {WINDOW}-character stretch with the prompt: {hits[0]!r}"


def test_the_guard_can_fail() -> None:
    # positive control: a prompt that embeds a stretch of a shadowing text must be caught
    shadowing = ROOT / "data" / "own" / "shadowing.jsonl"
    first = json.loads(shadowing.read_text(encoding="utf-8").splitlines()[0])
    leaked = squash("some rules. " + first["text"] + " more rules.")
    text = squash(first["text"])
    assert any(text[i : i + WINDOW] in leaked for i in range(max(1, len(text) - WINDOW + 1)))
