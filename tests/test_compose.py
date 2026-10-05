"""Seam: scripts/compose_shadowing.py (regenerates the G-set texts from data/own/sources/gset_v1.json)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("compose_shadowing", ROOT / "scripts" / "compose_shadowing.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_doc() -> dict[str, object]:
    return {
        "rows": [
            {"id": "G1", "host_description": "Does a thing.", "fenced_block": None, "clause": "Then another."},
            {"id": "G2", "host_description": "Parses it.", "fenced_block": "```\nx: y\n```", "clause": "Then more."},
        ]
    }


def test_compose_text_forms() -> None:
    mod = load_script()
    rows = source_doc()["rows"]
    assert isinstance(rows, list)
    assert mod.compose_text(rows[0]) == "Does a thing. Then another."
    assert mod.compose_text(rows[1]) == "Parses it.\n\n```\nx: y\n```\n\nThen more."


def test_check_reports_a_differing_or_missing_text(tmp_path: Path) -> None:
    mod = load_script()
    source = tmp_path / "src.json"
    source.write_text(json.dumps(source_doc()), encoding="utf-8")
    shadowing = tmp_path / "s.jsonl"
    shadowing.write_text(
        json.dumps({"id": "G1", "text": "Does a thing. Then another."})
        + "\n"
        + json.dumps({"id": "G2", "text": "edited"})
        + "\n",
        encoding="utf-8",
    )
    problems = mod.check(source, shadowing)
    assert problems == ["G2: text differs from the composed text"]
    shadowing.write_text(json.dumps({"id": "G1", "text": "Does a thing. Then another."}) + "\n", encoding="utf-8")
    assert mod.check(source, shadowing) == ["G2: missing from " + str(shadowing)]


def test_the_committed_gset_composes_to_the_committed_texts() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/compose_shadowing.py"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8"
    )
    assert result.returncode == 0, result.stdout
    assert result.stdout.startswith("COMPOSE_OK rows=35 source_sha256=")
