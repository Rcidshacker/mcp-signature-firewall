"""Seam: `sigfw data check-own` (argv in, exit code and stdout out) and sigfw.textsim.jaccard.

All fixture rows are meaningless filler words, never attack text.
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

import pytest

from sigfw.cli import main
from sigfw.textsim import jaccard, ngrams

WORDS = [a + b for a in "bcdfghjklmnprstvwz" for b in ("ar", "el", "ix", "on", "um", "ope")]
CLAUSE_POSITIONS = ("start", "middle", "end")


def filler(seed: int, words: int = 25) -> str:
    rng = random.Random(seed)
    return " ".join(rng.choice(WORDS) for _ in range(words))


def make_row(i: int, **over: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": f"s{i:03d}",
        "author": "gpt" if i % 5 else "human",
        "channel": "tool_description",
        "family": "shadowing",
        "technique": f"tech{i % 7}",
        "clause_position": CLAUSE_POSITIONS[i % 3],
        "host_tool": f"host.tool{i}",
        "target_tool": f"target.tool{i}",
        "text": filler(i),
    }
    row.update(over)
    return row


def write(path: Path, rows: list[dict[str, object]]) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8", newline="\n")
    return path


def run(path: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = main(["data", "check-own", "--path", str(path)], env={})
    return code, capsys.readouterr().out


def line(out: str, prefix: str) -> str:
    matches = [ln for ln in out.splitlines() if ln.startswith(prefix)]
    assert len(matches) == 1, f"expected one {prefix!r} line in:\n{out}"
    return matches[0]


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


def test_both_authors_count_toward_the_total(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rows = [make_row(i, author="gpt") for i in range(35)] + [make_row(i, author="human") for i in range(40, 52)]
    code, out = run(write(tmp_path / "s.jsonl", rows), capsys)
    assert code == 0 and out.splitlines()[0] == "shadowing n=47"
    assert line(out, "author:") == "author: human=12 gpt=35"


def test_exact_duplicate_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rows = [make_row(i) for i in range(35)]
    rows.append(make_row(99, text=str(rows[3]["text"]).upper()))  # same text, different case
    code, out = run(write(tmp_path / "s.jsonl", rows), capsys)
    assert code == 1
    assert "s003" in out and "s099" in out and "duplicate" in out.lower()


def test_near_duplicate_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rows = [make_row(i) for i in range(35)]
    rows.append(make_row(98, text=str(rows[5]["text"]) + " extra"))  # one added word on a ~100 char text
    code, out = run(write(tmp_path / "s.jsonl", rows), capsys)
    assert code == 1
    assert "s005" in out and "s098" in out and "near-duplicate" in out.lower()


def test_near_duplicates_are_found_across_authors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rows = [make_row(i, author="gpt") for i in range(35)]
    rows.append(make_row(98, author="human", text=str(rows[5]["text"]) + " extra"))
    code, out = run(write(tmp_path / "s.jsonl", rows), capsys)
    assert code == 1 and "s005" in out and "s098" in out


def test_template_rows_are_never_counted(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rows = [make_row(i) for i in range(35)]
    rows += [
        make_row(500, id="TEMPLATE-1", technique="TEMPLATE", text="TEMPLATE"),
        make_row(501, id="TEMPLATE-2", technique="TEMPLATE", text="TEMPLATE"),
    ]
    code, out = run(write(tmp_path / "s.jsonl", rows), capsys)
    assert code == 0  # two identical placeholder texts are not a duplicate pair
    assert out.splitlines()[0] == "shadowing n=35"
    assert "TEMPLATE" in out  # ignored rows are mentioned
    assert "TEMPLATE" not in line(out, "technique:")


def test_template_only_file_has_n_zero_and_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rows = [make_row(500, id="TEMPLATE-1", technique="TEMPLATE", text="TEMPLATE")]
    code, out = run(write(tmp_path / "s.jsonl", rows), capsys)
    assert code == 1
    assert out.splitlines()[0] == "shadowing n=0"


@pytest.mark.parametrize(
    ("over", "needle"),
    [
        ({"clause_position": "top"}, "clause_position"),
        ({"author": "claude"}, "author"),
        ({"channel": "tool_result"}, "channel"),
        ({"family": "other"}, "family"),
        ({"text": "   "}, "text"),
        ({"technique": ""}, "technique"),
        ({"host_tool": ""}, "host_tool"),
        ({"target_tool": "  "}, "target_tool"),
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


@pytest.mark.parametrize("stored", ["length_bucket", "word_count", "length", "placement"])
def test_computed_or_retired_fields_must_not_be_stored(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], stored: str
) -> None:
    rows = [make_row(i) for i in range(35)]
    rows[2][stored] = "short"
    code, out = run(write(tmp_path / "s.jsonl", rows), capsys)
    assert code == 1 and "line 3" in out and stored in out


@pytest.mark.parametrize(
    "label", ["Argument Redirection", "has space", "camelCase", "trailing_", "_leading", "a__b", "x-y"]
)
def test_technique_must_be_lowercase_snake_case(tmp_path: Path, capsys: pytest.CaptureFixture[str], label: str) -> None:
    rows = [make_row(i) for i in range(35)]
    rows[4] = make_row(4, technique=label)
    code, out = run(write(tmp_path / "s.jsonl", rows), capsys)
    assert code == 1 and "line 5" in out and "snake_case" in out


def test_snake_case_technique_labels_are_accepted(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rows = [
        make_row(i, technique=["conditional_trigger", "compat_claim", "embedded_marker", "a1", "b_2"][i % 5])
        for i in range(35)
    ]
    code, _ = run(write(tmp_path / "s.jsonl", rows), capsys)
    assert code == 0


def test_committed_labels_follow_the_mapping_table() -> None:
    root = Path(__file__).resolve().parents[1] / "data" / "own"
    table = json.loads((root / "technique_labels.json").read_text(encoding="utf-8"))
    canonical = set(table.values())
    assert all(re.fullmatch(r"[a-z][a-z0-9]*(_[a-z0-9]+)*", c) for c in canonical)
    assert all(table[c] == c for c in canonical)  # every canonical label maps to itself
    shadowing = root / "shadowing.jsonl"
    if shadowing.exists():
        used = {json.loads(ln)["technique"] for ln in shadowing.read_text(encoding="utf-8").splitlines() if ln.strip()}
        assert used <= canonical, sorted(used - canonical)


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


# ---------------------------------------------------------------- length buckets and the printed summary


@pytest.mark.parametrize(
    ("words", "bucket"), [(1, "short"), (25, "short"), (26, "medium"), (45, "medium"), (46, "long"), (120, "long")]
)
def test_length_bucket_is_computed_from_the_word_count(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], words: int, bucket: str
) -> None:
    rows = [make_row(i) for i in range(1, 35)] + [make_row(0, text=filler(900 + words, words))]
    _, out = run(write(tmp_path / "s.jsonl", rows), capsys)
    assert f"{bucket}=" in line(out, "length_bucket:")
    # the 34 other rows are 25 words (short); the probe row lands in `bucket`
    expected = {"short": 35 if bucket == "short" else 34, "medium": 0, "long": 0}
    if bucket != "short":
        expected[bucket] = 1
    assert line(out, "length_bucket:") == "length_bucket: " + " ".join(f"{k}={v}" for k, v in expected.items())


def test_summary_counts_by_author_technique_position_and_crosstab(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rows = [make_row(i) for i in range(35)]
    _, out = run(write(tmp_path / "s.jsonl", rows), capsys)
    assert line(out, "author:") == "author: human=7 gpt=28"
    assert line(out, "technique:") == "technique: tech0=5 tech1=5 tech2=5 tech3=5 tech4=5 tech5=5 tech6=5"
    assert line(out, "clause_position:") == "clause_position: start=12 middle=12 end=11 only=0"
    assert out.count("length_bucket x clause_position:") == 1
    assert "  short: start=12 middle=12 end=11 only=0" in out  # all fixture rows are 25 words, so all are short
    assert "  medium: start=0 middle=0 end=0 only=0" in out


def test_closest_pairs_and_max_jaccard_are_printed_by_id_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rows = [make_row(i) for i in range(35)]
    # a pair that is similar but under the 0.85 threshold: share a long prefix, differ in the tail
    rows[10]["text"] = filler(10, 12) + " " + filler(77, 13)
    rows[11]["text"] = filler(10, 12) + " " + filler(78, 13)
    code, out = run(write(tmp_path / "s.jsonl", rows), capsys)
    assert code == 0
    closest = [ln for ln in out.splitlines() if ln.startswith("closest:")]
    assert len(closest) == 1
    pairs = closest[0].removeprefix("closest: ").split("; ")
    assert len(pairs) == 5
    assert pairs[0].startswith("s010 s011 ")  # the engineered pair is the closest
    scores = [float(p.rsplit(" ", 1)[1]) for p in pairs]
    assert scores == sorted(scores, reverse=True)
    assert line(out, "max_jaccard=") == f"max_jaccard={scores[0]:.2f}"
    for row in rows:  # only ids and scores, never text
        assert str(row["text"]) not in out


def test_thin_technique_spread_warns_but_does_not_fail(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rows = [make_row(i, technique="one") for i in range(35)]
    code, out = run(write(tmp_path / "s.jsonl", rows), capsys)
    assert code == 0
    assert any(ln.startswith("WARN") and "technique" in ln for ln in out.splitlines())


def test_unbalanced_positions_and_lengths_do_not_warn(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # clause_position is an annotation reported as annotated: no balance claim, so no balance warning
    rows = [make_row(i, clause_position="start") for i in range(35)]
    code, out = run(write(tmp_path / "s.jsonl", rows), capsys)
    assert code == 0 and not [ln for ln in out.splitlines() if ln.startswith("WARN")]


def test_committed_template_is_valid_but_never_counts(capsys: pytest.CaptureFixture[str]) -> None:
    template = Path(__file__).resolve().parents[1] / "data" / "own" / "shadowing.template.jsonl"
    rows = [json.loads(ln) for ln in template.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(rows) == 2
    assert all(
        r["technique"] == "TEMPLATE" and str(r["id"]).startswith("TEMPLATE") and str(r["text"]).startswith("TEMPLATE")
        for r in rows
    )
    code, out = run(template, capsys)
    assert code == 1
    assert out.splitlines()[0] == "shadowing n=0"
    assert "ERROR line" not in out  # the placeholders are schema-valid, only the count fails


def test_only_is_a_valid_literal_clause_position(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rows = [make_row(i, clause_position="only") for i in range(35)]
    code, out = run(write(tmp_path / "s.jsonl", rows), capsys)
    assert code == 0 and "clause_position: start=0 middle=0 end=0 only=35" in out


def test_source_placement_is_optional_and_checked(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rows = [make_row(i, source_placement=["start", "middle", "end"][i % 3]) for i in range(34)] + [make_row(34)]
    code, _ = run(write(tmp_path / "ok.jsonl", rows), capsys)
    assert code == 0  # present on some rows, absent on others
    for bad in ("only", "top", 5):
        rows[3] = make_row(3, source_placement=bad)
        code, out = run(write(tmp_path / "bad.jsonl", rows), capsys)
        assert code == 1 and "line 4" in out and "source_placement" in out


def test_committed_rows_follow_the_clause_position_decisions() -> None:
    path = Path(__file__).resolve().parents[1] / "data" / "own" / "shadowing.jsonl"
    if not path.exists():
        return
    rows = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    for r in rows:
        if r["author"] == "gpt":
            assert r["clause_position"] == "end", r["id"]  # texts are composed description-then-clause
        else:
            assert r["clause_position"] == ("end" if r["id"] == "H15" else "only"), r["id"]
        if "source_placement" in r:
            assert r["source_placement"] in ("start", "middle", "end")
