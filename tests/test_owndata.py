"""Seam: `sigfw data check-own` (argv in, exit code and stdout out) and sigfw.textsim.jaccard.

All fixture rows are meaningless filler words, never attack text.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from sigfw.cli import main
from sigfw.textsim import jaccard, ngrams

WORDS = [
    "amber",
    "basil",
    "cedar",
    "dune",
    "ember",
    "fjord",
    "glade",
    "harbor",
    "iris",
    "juniper",
    "kelp",
    "lagoon",
    "meadow",
    "nectar",
    "orchid",
    "pebble",
    "quartz",
    "ripple",
    "sable",
    "thistle",
    "umber",
    "velvet",
    "willow",
    "xenon",
    "yarrow",
    "zephyr",
    "anchor",
    "bridge",
    "candle",
    "drift",
    "easel",
    "feather",
    "garnet",
    "hollow",
    "island",
    "jasper",
    "kettle",
    "lantern",
    "marble",
    "nutmeg",
    "oyster",
    "paddle",
    "quiver",
    "rafter",
    "saddle",
    "timber",
    "upland",
    "vessel",
    "walnut",
    "yonder",
    "zenith",
    "acorn",
    "beacon",
    "cobble",
    "dapple",
    "fennel",
    "gravel",
    "hickory",
    "indigo",
    "jostle",
]
PLACEMENTS = ("start", "middle", "end")
LENGTHS = ("short", "medium", "long")


def make_row(i: int, **over: object) -> dict[str, object]:
    rng = random.Random(i)
    row: dict[str, object] = {
        "id": f"s{i:03d}",
        "channel": "tool_description",
        "family": "shadowing",
        "text": " ".join(rng.choice(WORDS) for _ in range(25)),
        "technique": f"tech{i % 7}",
        "placement": PLACEMENTS[i % 3],
        "length_bucket": LENGTHS[i % 3],
    }
    row.update(over)
    return row


def write(path: Path, rows: list[dict[str, object]]) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8", newline="\n")
    return path


def run(path: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = main(["data", "check-own", "--path", str(path)], env={})
    return code, capsys.readouterr().out


def test_jaccard_hand_computed() -> None:
    # 5-grams: {abcde, bcdef} vs {abcde, bcdeg}: intersection 1, union 3
    assert jaccard(ngrams("abcdef"), ngrams("abcdeg")) == pytest.approx(1 / 3)
    assert jaccard(ngrams("same text here"), ngrams("SAME  text\nhere")) == 1.0  # case and whitespace ignored
    assert jaccard(ngrams("abc"), ngrams("abd")) == 0.0  # shorter than 5 chars: whole text is one gram


def test_thirty_five_distinct_rows_pass(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(write(tmp_path / "s.jsonl", [make_row(i) for i in range(35)]), capsys)
    assert code == 0
    assert out.splitlines()[0] == "shadowing n=35"


def test_fewer_than_thirty_five_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(write(tmp_path / "s.jsonl", [make_row(i) for i in range(34)]), capsys)
    assert code == 1
    assert out.splitlines()[0] == "shadowing n=34"
    assert "35" in out


def test_exact_duplicate_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rows = [make_row(i) for i in range(35)]
    rows.append(make_row(99, text=str(rows[3]["text"]).upper()))  # same text, different case
    code, out = run(write(tmp_path / "s.jsonl", rows), capsys)
    assert code == 1
    assert "s003" in out and "s099" in out and "duplicate" in out.lower()


def test_near_duplicate_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rows = [make_row(i) for i in range(35)]
    rows.append(make_row(98, text=str(rows[5]["text"]) + " extra"))  # one added word on a ~150 char text
    code, out = run(write(tmp_path / "s.jsonl", rows), capsys)
    assert code == 1
    assert "s005" in out and "s098" in out and "near-duplicate" in out.lower()


def test_template_rows_are_never_counted(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rows = [make_row(i) for i in range(35)]
    rows += [make_row(500, id="TEMPLATE-1", text="TEMPLATE"), make_row(501, id="TEMPLATE-2", text="TEMPLATE")]
    code, out = run(write(tmp_path / "s.jsonl", rows), capsys)
    assert code == 0  # two identical placeholder texts are not a duplicate pair
    assert out.splitlines()[0] == "shadowing n=35"
    assert "TEMPLATE" in out  # ignored rows are mentioned


def test_template_only_file_has_n_zero_and_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rows = [make_row(500, id="TEMPLATE-1", text="TEMPLATE")]
    code, out = run(write(tmp_path / "s.jsonl", rows), capsys)
    assert code == 1
    assert out.splitlines()[0] == "shadowing n=0"


@pytest.mark.parametrize(
    ("over", "needle"),
    [
        ({"placement": "top"}, "placement"),
        ({"length_bucket": "tiny"}, "length_bucket"),
        ({"channel": "tool_result"}, "channel"),
        ({"family": "other"}, "family"),
        ({"text": "   "}, "text"),
        ({"technique": ""}, "technique"),
        ({"id": ""}, "id"),
        ({"text": 5}, "text"),
    ],
)
def test_bad_field_values_fail_with_the_field_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], over: dict[str, object], needle: str
) -> None:
    rows = [make_row(i) for i in range(35)]
    rows[7] = make_row(7, **over)
    code, out = run(write(tmp_path / "s.jsonl", rows), capsys)
    assert code == 1
    assert "line 8" in out and needle in out
    assert out.splitlines()[0] == "shadowing n=34"  # the bad row is not counted


def test_missing_and_unknown_fields_fail(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rows = [make_row(i) for i in range(35)]
    del rows[1]["technique"]
    rows[2]["placment"] = "start"  # typo'd extra key
    code, out = run(write(tmp_path / "s.jsonl", rows), capsys)
    assert code == 1
    assert "line 2" in out and "technique" in out
    assert "line 3" in out and "placment" in out


def test_duplicate_ids_fail(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rows = [make_row(i) for i in range(35)]
    rows[9]["id"] = "s000"
    code, out = run(write(tmp_path / "s.jsonl", rows), capsys)
    assert code == 1 and "duplicate id" in out.lower()


def test_invalid_json_and_blank_lines(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    p = tmp_path / "s.jsonl"
    lines = [json.dumps(make_row(i)) for i in range(35)]
    lines.insert(4, "")  # blank lines are ignored
    lines.insert(10, "{not json")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    code, out = run(p, capsys)
    assert code == 1
    assert "line 11" in out and "json" in out.lower()
    assert out.splitlines()[0] == "shadowing n=35"


def test_missing_file_fails_cleanly(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(tmp_path / "nope.jsonl", capsys)
    assert code == 1
    assert out.splitlines()[0] == "shadowing n=0" and "not found" in out.lower()


def test_thin_spread_warns_but_does_not_fail(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rows = [make_row(i, technique="one", placement="start", length_bucket="short") for i in range(35)]
    code, out = run(write(tmp_path / "s.jsonl", rows), capsys)
    assert code == 0
    warns = [ln for ln in out.splitlines() if ln.startswith("WARN")]
    text = "\n".join(warns)
    assert "technique" in text and "placement" in text and "length_bucket" in text


def test_balanced_spread_has_no_warnings(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _, out = run(write(tmp_path / "s.jsonl", [make_row(i) for i in range(35)]), capsys)
    assert not [ln for ln in out.splitlines() if ln.startswith("WARN")]


def test_committed_template_is_valid_but_never_counts(capsys: pytest.CaptureFixture[str]) -> None:
    template = Path(__file__).resolve().parents[1] / "data" / "own" / "shadowing.template.jsonl"
    rows = [json.loads(ln) for ln in template.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(rows) == 2
    assert all(str(r["id"]).startswith("TEMPLATE") and str(r["text"]).startswith("TEMPLATE") for r in rows)
    code, out = run(template, capsys)
    assert code == 1
    assert out.splitlines()[0] == "shadowing n=0"
    assert "ERROR line" not in out  # the placeholders are schema-valid, only the count fails
