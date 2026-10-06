"""scripts/split_mcptox_dev.py: key-based split, dropped rows never written, logged or printed."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("split_mcptox_dev", ROOT / "scripts" / "split_mcptox_dev.py")
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

T3_SENTINEL = "SENTINEL-HELD-OUT-ROW-TEXT-ZZZ"
DEDUPED_SENTINEL = "SENTINEL-DEV-ROW-DROPPED-BY-DEDUPE"


def rig(tmp_path: Path, rows: list[tuple[str, dict[str, object]]]) -> tuple[Path, Path, Path, Path]:
    src = tmp_path / "pure_tool.json"
    src.write_text(json.dumps([{key: rec} for key, rec in rows]), encoding="utf-8")
    manifest = tmp_path / "split.json"
    items = [{"id": f"mcptox/{k}", "split": "dev" if r.get("paradigm") != "Template-3" else "frozen"} for k, r in rows]
    items = [i for i in items if "dedupe" not in i["id"]]  # one dev row the corpus dedupe dropped
    manifest.write_text(json.dumps({"items": items}), encoding="utf-8")
    return src, tmp_path / "out" / "dev.jsonl", manifest, tmp_path / "run-log.txt"


ROWS: list[tuple[str, dict[str, object]]] = [
    ("A_1", {"paradigm": "Template-1", "tool_content": "dev one"}),
    ("B_2", {"paradigm": "Template-2", "tool_content": "dev two"}),
    ("C_3", {"paradigm": "Template-3", "tool_content": T3_SENTINEL}),
    ("D_3", {"paradigm": "Template-3", "tool_content": T3_SENTINEL + " again"}),
    ("dedupe_1", {"paradigm": "Template-1", "tool_content": DEDUPED_SENTINEL}),
]


def test_keeps_t1_and_t2_and_nothing_else(tmp_path: Path) -> None:
    src, out, manifest, log = rig(tmp_path, ROWS)
    counts = mod.split(src, out, manifest, log)
    rows = [json.loads(ln) for ln in out.read_text(encoding="utf-8").splitlines()]
    assert [(r["id"], r["family"], r["text"]) for r in rows] == [
        ("mcptox/A_1", "mcptox_t1", "dev one"),
        ("mcptox/B_2", "mcptox_t2", "dev two"),
    ]
    assert counts["kept_mcptox_t1"] == 1 and counts["kept_mcptox_t2"] == 1 and counts["seen_Template-3"] == 2


def test_dropped_text_is_in_no_output_log_or_stdout(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src, out, manifest, log = rig(tmp_path, ROWS)
    mod.split(src, out, manifest, log)
    everything = out.read_text(encoding="utf-8") + log.read_text(encoding="utf-8") + capsys.readouterr().out
    assert T3_SENTINEL not in everything and DEDUPED_SENTINEL not in everything
    assert mod.INVARIANT in log.read_text(encoding="utf-8")
    assert '"seen_Template-3": 2' in log.read_text(encoding="utf-8")  # counts per key only


def test_a_row_without_a_plain_paradigm_field_stops_the_split(tmp_path: Path) -> None:
    src, out, manifest, log = rig(tmp_path, [("A_1", {"tool_content": "no key here"})])
    with pytest.raises(SystemExit, match="paradigm"):
        mod.split(src, out, manifest, log)
    assert not out.exists()
