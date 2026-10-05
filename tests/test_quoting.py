"""Seam: `sigfw data check-quoting --slice frozen|dev` on synthetic files (argv in, exit code and stdout out).

All fixture text is meaningless filler words. The held-out attack text it is compared with comes from test_datapipe's
synthetic raw files.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest
from test_datapipe import make_raw
from test_owndata import WORDS

from sigfw.cli import main
from sigfw.quoting import FORMS, SOURCE_TYPES


def filler(seed: int, words: int = 25) -> str:
    rng = random.Random(seed)
    return " ".join(rng.choice(WORDS) for _ in range(words))


def make_q(i: int, slice_name: str = "frozen", **over: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": f"{slice_name[0]}q{i:03d}",
        "author": "human" if i % 3 == 0 else "nemotron-super",
        "slice": slice_name,
        "source_type": SOURCE_TYPES[i % 10],
        "form": FORMS[i % 2],
        "channel": ("tool_description", "tool_result", "other")[i % 3],
        "reviewed": True,
        "text": filler(10_000 + i + (0 if slice_name == "frozen" else 5_000)),
    }
    row.update(over)
    return row


def write(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8", newline="\n")


class Rig:
    def __init__(self, tmp_path: Path, frozen: int = 200, dev: int = 50) -> None:
        self.raw, self.shadowing = make_raw(tmp_path)
        self.dir = tmp_path / "own_q"
        self.dir.mkdir()
        self.frozen_rows = [make_q(i) for i in range(frozen)]
        self.dev_rows = [make_q(i, "dev") for i in range(dev)]
        self.flush()

    def flush(self) -> None:
        write(self.dir / "quoting_frozen.jsonl", self.frozen_rows)
        write(self.dir / "quoting_dev.jsonl", self.dev_rows)

    def run(self, slice_name: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
        args = ["data", "check-quoting", "--slice", slice_name, "--dir", str(self.dir)]
        args += ["--raw", str(self.raw), "--shadowing", str(self.shadowing)]
        code = main(args, env={})
        return code, capsys.readouterr().out


def line(out: str, prefix: str) -> str:
    matches = [ln for ln in out.splitlines() if ln.startswith(prefix)]
    assert len(matches) == 1, f"expected one {prefix!r} line in:\n{out}"
    return matches[0]


def test_a_valid_frozen_slice_passes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = Rig(tmp_path).run("frozen", capsys)
    assert code == 0 and out.splitlines()[0] == "quoting slice=frozen n=200"
    assert out.strip().endswith("QUOTING_OK slice=frozen")
    assert not [ln for ln in out.splitlines() if ln.startswith(("ERROR", "WARN"))]


@pytest.mark.parametrize("n", [0, 199, 201])
def test_frozen_must_have_exactly_200_rows(tmp_path: Path, capsys: pytest.CaptureFixture[str], n: int) -> None:
    code, out = Rig(tmp_path, frozen=n).run("frozen", capsys)
    assert code == 1 and f"n={n}" in out and "exactly 200" in out


def test_every_frozen_row_must_be_reviewed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rig = Rig(tmp_path)
    rig.frozen_rows[5]["reviewed"] = False
    rig.frozen_rows[9]["reviewed"] = False
    rig.flush()
    code, out = rig.run("frozen", capsys)
    assert code == 1 and "2 row(s) not reviewed" in out and "fq005" in out


def test_reviewed_must_be_a_boolean(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rig = Rig(tmp_path)
    rig.frozen_rows[3]["reviewed"] = "true"
    rig.flush()
    code, out = rig.run("frozen", capsys)
    assert code == 1 and "line 4" in out and "reviewed must be true or false" in out


@pytest.mark.parametrize(("n", "ok"), [(39, False), (40, True), (50, True), (60, True), (61, False)])
def test_dev_slice_needs_40_to_60_rows_and_no_review(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], n: int, ok: bool
) -> None:
    rig = Rig(tmp_path, dev=n)
    for row in rig.dev_rows:
        row["reviewed"] = False  # not required for dev
    rig.flush()
    code, out = rig.run("dev", capsys)
    assert (code == 0) is ok
    assert out.splitlines()[0] == f"quoting slice=dev n={n}"


@pytest.mark.parametrize(
    ("over", "needle"),
    [
        ({"author": "claude"}, "author"),
        ({"slice": "dev"}, "slice must be 'frozen'"),
        ({"source_type": "tweet"}, "source_type"),
        ({"form": "paraphrase"}, "form"),
        ({"channel": "email"}, "channel"),
        ({"text": "  "}, "text"),
        ({"id": ""}, "id"),
        ({"text": 4}, "text"),
    ],
)
def test_bad_values_fail_with_the_field_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], over: dict[str, object], needle: str
) -> None:
    rig = Rig(tmp_path)
    rig.frozen_rows[7] = make_q(7, **over)
    rig.flush()
    code, out = rig.run("frozen", capsys)
    assert code == 1 and "line 8" in out and needle in out and "n=199" in out.splitlines()[0] + " " + out


def test_missing_and_unknown_fields_fail(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rig = Rig(tmp_path)
    del rig.frozen_rows[1]["form"]
    rig.frozen_rows[2]["extra"] = 1
    rig.flush()
    code, out = rig.run("frozen", capsys)
    assert code == 1 and "line 2" in out and "form" in out and "line 3" in out and "extra" in out


def test_duplicate_ids_fail(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rig = Rig(tmp_path)
    rig.frozen_rows[9]["id"] = "fq000"
    rig.flush()
    code, out = rig.run("frozen", capsys)
    assert code == 1 and "duplicate id" in out


def test_exact_and_near_duplicates_fail_within_a_slice(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rig = Rig(tmp_path)
    rig.frozen_rows[4]["text"] = str(rig.frozen_rows[3]["text"]).upper()
    rig.frozen_rows[6]["text"] = str(rig.frozen_rows[5]["text"]) + " extra"
    rig.flush()
    code, out = rig.run("frozen", capsys)
    assert code == 1
    assert "exact duplicate: fq003 (frozen) and fq004 (frozen)" in out
    assert "near-duplicate: fq005 (frozen) and fq006 (frozen)" in out


def test_a_duplicate_across_slices_fails_both_slices(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rig = Rig(tmp_path)
    rig.dev_rows[2]["text"] = rig.frozen_rows[8]["text"]
    rig.flush()
    for name in ("frozen", "dev"):
        code, out = rig.run(name, capsys)
        assert code == 1 and ("fq008 (frozen) and dq002 (dev)" in out or "dq002 (dev) and fq008 (frozen)" in out)


def test_template_rows_are_ignored(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rig = Rig(tmp_path)
    rig.frozen_rows += [make_q(900, id="TEMPLATE-1", text="TEMPLATE"), make_q(901, id="TEMPLATE-2", text="TEMPLATE")]
    rig.flush()
    code, out = rig.run("frozen", capsys)
    assert code == 0 and out.splitlines()[0] == "quoting slice=frozen n=200"
    assert "2 TEMPLATE row(s) ignored" in out


def held_out_text(rig: Rig) -> str:
    data = json.loads((rig.raw / "bipia" / "code_attack_train.json").read_text(encoding="utf-8"))
    return str(next(iter(data.values()))[0])


def test_a_30_character_overlap_with_a_held_out_attack_fails_and_prints_ids_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rig = Rig(tmp_path)
    attack = held_out_text(rig)
    rig.frozen_rows[11]["text"] = "some quoting prose before. " + attack[:40] + " and some after."
    rig.flush()
    code, out = rig.run("frozen", capsys)
    assert code == 1
    assert "overlap: fq011 shares a 30-character stretch with bipia/code/train/" in out
    assert attack[:30] not in out  # the attack text itself is never printed


def test_a_30_character_overlap_with_a_shadowing_row_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rig = Rig(tmp_path)
    shadow = json.loads(rig.shadowing.read_text(encoding="utf-8").splitlines()[3])["text"]
    rig.dev_rows[1]["text"] = "prefix words " + shadow[10:60]
    rig.flush()
    code, out = rig.run("dev", capsys)
    assert code == 1 and "overlap: dq001 shares a 30-character stretch with own/shadowing/" in out


def test_a_short_shared_stretch_is_not_an_overlap(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rig = Rig(tmp_path)
    attack = held_out_text(rig)
    rig.frozen_rows[11]["text"] = "words " + attack[:29] + " zzz"
    rig.flush()
    code, _ = rig.run("frozen", capsys)
    assert code == 0


def test_the_overlap_check_cannot_run_without_the_raw_data(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rig = Rig(tmp_path)
    (rig.raw / "bipia" / "code_attack_test.json").unlink()
    code, out = rig.run("frozen", capsys)
    assert code == 1 and "cannot check overlap" in out and "sigfw data fetch" in out


def test_a_missing_slice_file_fails_cleanly(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rig = Rig(tmp_path)
    (rig.dir / "quoting_frozen.jsonl").unlink()
    code, out = rig.run("frozen", capsys)
    assert code == 1 and "not found" in out


def test_summary_lines_and_closest_pairs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rig = Rig(tmp_path)
    rig.frozen_rows[20]["text"] = filler(777, 12) + " " + filler(778, 13)
    rig.frozen_rows[21]["text"] = filler(777, 12) + " " + filler(779, 13)
    rig.flush()
    code, out = rig.run("frozen", capsys)
    assert code == 0
    assert line(out, "author:") == "author: human=67 nemotron-super=133"
    assert "security_blog=20" in line(out, "source_type:") and "forum_post=20" in line(out, "source_type:")
    assert line(out, "form:") == "form: verbatim_quote=100 discussion=100"
    assert line(out, "channel:") == "channel: tool_description=67 tool_result=67 other=66"
    assert line(out, "reviewed:") == "reviewed: true=200 false=0"
    pairs = line(out, "closest:").removeprefix("closest: ").split("; ")
    assert len(pairs) == 5 and pairs[0].startswith("fq020 fq021 ")
    assert line(out, "max_jaccard=") == f"max_jaccard={float(pairs[0].rsplit(' ', 1)[1]):.2f}"
    for row in rig.frozen_rows:
        assert str(row["text"]) not in out


def test_warnings_do_not_fail(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rig = Rig(tmp_path)
    for i, row in enumerate(rig.frozen_rows):
        row["source_type"] = "docs" if i < 60 else row["source_type"]  # one type above 20%
        row["form"] = "discussion"  # verbatim share 0%, outside 40-60%
        row["author"] = "nemotron-super"  # human share 0, below a third
    rig.flush()
    code, out = rig.run("frozen", capsys)
    warns = [ln for ln in out.splitlines() if ln.startswith("WARN")]
    assert code == 0 and len(warns) == 3
    assert any("source_type docs" in w for w in warns)
    assert any("verbatim_quote share" in w for w in warns)
    assert any("human share" in w for w in warns)


def test_the_committed_template_files_are_valid_and_never_count() -> None:
    root = Path(__file__).resolve().parents[1] / "data" / "own"
    for name, slice_name in (("quoting_frozen.jsonl", "frozen"), ("quoting_dev.jsonl", "dev")):
        path = root / name
        if not path.exists():
            continue
        rows = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        template = [r for r in rows if str(r["id"]).startswith("TEMPLATE")]
        assert len(template) == 2 and all(
            r["slice"] == slice_name and r["text"].startswith("TEMPLATE") for r in template
        )


@pytest.mark.parametrize(("human", "warns"), [(66, True), (67, False)])
def test_human_share_warning_boundary_is_one_third(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], human: int, warns: bool
) -> None:
    rig = Rig(tmp_path)
    for i, row in enumerate(rig.frozen_rows):
        row["author"] = "human" if i < human else "nemotron-super"
    rig.flush()
    code, out = rig.run("frozen", capsys)
    assert code == 0 and any("human share" in ln for ln in out.splitlines()) is warns
