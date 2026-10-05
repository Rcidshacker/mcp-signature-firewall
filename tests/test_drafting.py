"""Seams: sigfw.drafting (variation, parse_draft, caps), `sigfw data draft-quoting` and `review-quoting`.

Network faked with MockTransport; every generated text is filler words. No live call happens in these tests.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest
from test_owndata import filler

from sigfw import drafting
from sigfw.cli import main
from sigfw.drafting import DraftLedger, parse_draft, render_prompt, variation
from sigfw.quoting import SOURCE_TYPES

Handler = Callable[[httpx.Request], httpx.Response]
KEY = "nvapi" + "-CANARY0123456789abcdefghijklmnopqrstuvwxyz"  # split so the repo key scan stays meaningful
ROOT = Path(__file__).resolve().parents[1]


def reply(text_or_raw: str, *, raw: bool = False, finish: str = "stop") -> httpx.Response:
    content = text_or_raw if raw else json.dumps({"text": text_or_raw})
    return httpx.Response(
        200, json={"choices": [{"message": {"content": content}, "finish_reason": finish}], "usage": {}}
    )


class Rig:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        self.prompts = tmp_path / "gen_prompts"
        self.prompts.mkdir()
        for name in SOURCE_TYPES:
            (self.prompts / f"{name}.txt").write_text(
                f"STYLE {name}. Setting: <<topic>> Form: <<form>> Where: <<channel>>\n", encoding="utf-8", newline="\n"
            )
        self.staging = tmp_path / "var" / "staging.jsonl"
        self.ledger = tmp_path / "var" / "ledger.jsonl"
        self.dir = tmp_path / "own"
        self.dir.mkdir()
        self.requests: list[dict[str, object]] = []
        self.counter = 0

    def next_text(self) -> str:
        self.counter += 1
        return filler(50_000 + self.counter, 20)

    def run(
        self,
        handler: Handler,
        source_type: str = "docs",
        n: int = 3,
        *,
        live: bool = True,
        extra: list[str] | None = None,
    ) -> int:
        def spy(req: httpx.Request) -> httpx.Response:
            self.requests.append(json.loads(req.content))
            return handler(req)

        args = ["data", "draft-quoting", "--source-type", source_type, "--n", str(n)]
        args += ["--prompts", str(self.prompts), "--staging", str(self.staging), "--ledger", str(self.ledger)]
        args += ["--dir", str(self.dir)] + (["--confirm-live"] if live else []) + (extra or [])
        return main(
            args,
            env={"NVIDIA_API_KEY": KEY, "LLM_EXTRA_BODY": '{"chat_template_kwargs": {"enable_thinking": false}}'},
            transport=httpx.MockTransport(spy),
        )

    def rows(self) -> list[dict[str, object]]:
        return [json.loads(ln) for ln in self.staging.read_text(encoding="utf-8").splitlines() if ln.strip()]


def fresh(rig: Rig) -> Handler:
    return lambda req: reply(rig.next_text())


def test_variation_is_distinct_for_the_first_forty_drafts_of_a_type() -> None:
    combos = {variation(k) for k in range(40)}
    assert len(combos) == 40
    assert {v[1] for v in combos} == {"verbatim_quote", "discussion"}
    assert {v[2] for v in combos} == {"tool_description", "tool_result", "other"}


def test_render_prompt_fills_every_placeholder() -> None:
    prompt, form, channel = render_prompt("A <<topic>> B <<form>> C <<channel>>", 1)
    assert "<<" not in prompt and form == "discussion" and channel == "tool_result"


@pytest.mark.parametrize(
    ("content", "finish", "ok"),
    [
        (json.dumps({"text": "x" * 100}), "stop", True),
        (json.dumps({"text": "x" * 79}), "stop", False),
        (json.dumps({"text": "x" * 2501}), "stop", False),
        (json.dumps({"text": "x" * 100, "extra": 1}), "stop", False),
        (json.dumps({"text": 5}), "stop", False),
        ("not json", "stop", False),
        ("[]", "stop", False),
        (json.dumps({"text": "x" * 100}), "length", False),
    ],
)
def test_parse_draft(content: str, finish: str, ok: bool) -> None:
    text, problem = parse_draft(content, finish)
    assert (text is not None) is ok and (problem is None) is ok


def test_refuses_to_run_live_without_the_confirm_flag(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    assert rig.run(fresh(rig), live=False) == 2
    assert rig.requests == [] and not rig.staging.exists()


def test_a_draft_run_writes_unreviewed_super_rows_and_a_full_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rig = Rig(tmp_path)
    assert rig.run(fresh(rig), "docs", 3) == 0
    out = capsys.readouterr().out
    assert out.startswith("DRAFT_DONE source_type=docs requested=3 calls=3 kept=3 malformed=0 duplicate=0 failed=0")
    rows = rig.rows()
    assert [r["id"] for r in rows] == ["ns-docs-001", "ns-docs-002", "ns-docs-003"]
    for k, r in enumerate(rows):
        assert r["author"] == "nemotron-super" and r["reviewed"] is False and r["slice"] == "frozen"
        assert r["source_type"] == "docs" and (r["form"], r["channel"]) == variation(k)[1:]
    req = rig.requests[0]
    assert req["model"] == drafting.SUPER_MODEL and req["response_format"] == {"type": "json_object"}
    assert req["chat_template_kwargs"] == {"enable_thinking": False} and req["temperature"] == 0
    assert "STYLE docs" in req["messages"][0]["content"] and "<<" not in req["messages"][0]["content"]  # type: ignore[index]
    entries = DraftLedger(rig.ledger).entries
    assert len(entries) == 3 and all(e["model"] == drafting.SUPER_MODEL and e["outcome"] == "kept" for e in entries)
    assert entries[0]["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}
    assert entries[0]["prompt_sha256"] == hashlib.sha256((rig.prompts / "docs.txt").read_bytes()).hexdigest()
    for path in (rig.staging, rig.ledger):
        assert KEY not in path.read_text(encoding="utf-8") and "CANARY" not in path.read_text(encoding="utf-8")


def test_a_second_run_continues_the_numbering(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.run(fresh(rig), "docs", 2)
    rig.run(fresh(rig), "docs", 2)
    assert [r["id"] for r in rig.rows()] == [f"ns-docs-{k:03d}" for k in (1, 2, 3, 4)]
    assert [(r["form"], r["channel"]) for r in rig.rows()][2] == variation(2)[1:]


def test_duplicates_of_drafts_and_of_human_rows_are_dropped(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rig = Rig(tmp_path)
    human_text = filler(777, 20)
    (rig.dir / "quoting_frozen.jsonl").write_text(
        json.dumps({"id": "h1", "author": "human", "text": human_text}) + "\n", encoding="utf-8"
    )
    same = filler(888, 20)
    texts = iter([human_text.upper(), same, same + " tail", filler(999, 20)])
    assert rig.run(lambda req: reply(next(texts)), "docs", 4) == 0
    out = capsys.readouterr().out
    assert "kept=2 malformed=0 duplicate=2" in out and "calls=4" in out
    assert len(rig.rows()) == 2


def test_malformed_and_failed_replies_are_counted_and_never_staged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rig = Rig(tmp_path)
    answers: Iterator[httpx.Response] = iter(
        [reply("nope", raw=True), reply("short"), httpx.Response(401, json={}), reply(rig.next_text())]
    )
    assert rig.run(lambda req: next(answers), "docs", 4) == 0
    out = capsys.readouterr().out
    assert "kept=1 malformed=2 duplicate=0 failed=1" in out
    assert [e["outcome"] for e in DraftLedger(rig.ledger).entries] == ["malformed", "malformed", "failed", "kept"]


def test_the_per_type_cap_is_40_calls_in_total_across_runs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rig = Rig(tmp_path)
    assert rig.run(fresh(rig), "docs", 41) == 1
    assert "cap" in capsys.readouterr().out and rig.requests == []
    assert rig.run(fresh(rig), "docs", 40) == 0
    assert rig.run(fresh(rig), "docs", 1) == 1  # 40 already generated
    assert rig.run(fresh(rig), "forum_post", 1) == 0  # another type has its own allowance
    assert len(rig.requests) == 41


def test_malformed_calls_count_against_the_cap(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.run(lambda req: reply("nope", raw=True), "docs", 40)
    assert rig.run(fresh(rig), "docs", 1) == 1


def test_the_total_cap_is_250(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rig = Rig(tmp_path)
    ledger = DraftLedger(rig.ledger)
    for i in range(245):  # 245 earlier calls spread over source types, none above 40
        ledger.record({"source_type": SOURCE_TYPES[i % 10], "k": i, "outcome": "kept"})
    assert rig.run(fresh(rig), "docs", 6) == 1 and "250" in capsys.readouterr().out and rig.requests == []
    assert rig.run(fresh(rig), "docs", 5) == 0


def test_drafting_never_touches_the_classifier() -> None:
    for name in ("drafting.py", "draftcmd.py"):
        source = (ROOT / "src" / "sigfw" / name).read_text(encoding="utf-8")
        assert "sigfw.classifier" not in source and "LlmClassifier" not in source


# ---------------------------------------------------------------- generation prompts


def squash(text: str) -> str:
    return " ".join(text.split()).casefold()


def test_every_source_type_has_a_generic_prompt_with_the_three_placeholders() -> None:
    for name in SOURCE_TYPES:
        raw = (ROOT / "data" / "gen_prompts" / f"{name}.txt").read_bytes()
        text = raw.decode("utf-8")
        assert b"\r" not in raw and all(p in text for p in ("<<topic>>", "<<form>>", "<<channel>>"))
        assert "ONE JSON object" in text
    assert len(list((ROOT / "data" / "gen_prompts").glob("*.txt"))) == len(SOURCE_TYPES)


def test_generation_prompts_share_no_30_character_stretch_with_shadowing_text() -> None:
    shadowing = [
        json.loads(ln)["text"]
        for ln in (ROOT / "data" / "own" / "shadowing.jsonl").read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    prompts = " ".join(squash(p.read_text(encoding="utf-8")) for p in (ROOT / "data" / "gen_prompts").glob("*.txt"))
    for text in map(squash, shadowing):
        assert not any(text[i : i + 30] in prompts for i in range(max(1, len(text) - 29)))


# ---------------------------------------------------------------- review


def feed(monkeypatch: pytest.MonkeyPatch, answers: list[str]) -> list[str]:
    seen: list[str] = []
    it = iter(answers)

    def fake(prompt: str = "") -> str:
        seen.append(prompt)
        return next(it)

    monkeypatch.setattr("builtins.input", fake)
    return seen


def review(rig: Rig) -> int:
    log = rig.dir / "quoting_review_log.jsonl"
    return main(
        [
            "data",
            "review-quoting",
            "--staging",
            str(rig.staging),
            "--ledger",
            str(rig.ledger),
            "--dir",
            str(rig.dir),
            "--log",
            str(log),
        ],
        env={},
    )


def test_review_accepts_and_rejects_with_the_four_reasons_and_never_edits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rig = Rig(tmp_path)
    rig.run(fresh(rig), "docs", 4)
    staged = rig.rows()
    capsys.readouterr()
    feed(monkeypatch, ["a", "r", "q", "r", "x", "n", "a"])
    assert review(rig) == 0
    out = capsys.readouterr().out
    assert "REVIEW_DONE accepted=2 rejected=2 remaining=0" in out
    accepted = [json.loads(ln) for ln in (rig.dir / "quoting_frozen.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["id"] for r in accepted] == [staged[0]["id"], staged[3]["id"]]
    assert all(r["reviewed"] is True and r["author"] == "nemotron-super" for r in accepted)
    assert accepted[0]["text"] == staged[0]["text"]  # text is byte-for-byte what Super wrote
    log = [json.loads(ln) for ln in (rig.dir / "quoting_review_log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(e["decision"], e["reason"]) for e in log] == [
        ("accept", None),
        ("reject", "does_not_quote_or_discuss_an_attack"),
        ("reject", "not_benign"),
        ("accept", None),
    ]
    assert "type" in out  # the invalid reason key 'x' was asked again


def test_review_has_no_edit_option_and_stop_leaves_the_rest_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rig = Rig(tmp_path)
    rig.run(fresh(rig), "docs", 3)
    capsys.readouterr()
    feed(monkeypatch, ["e", "edit", "a", "s"])
    review(rig)
    out = capsys.readouterr().out
    assert "REVIEW_DONE accepted=1 rejected=0 remaining=2" in out
    assert len((rig.dir / "quoting_frozen.jsonl").read_text(encoding="utf-8").splitlines()) == 1
    feed(monkeypatch, ["a", "a"])  # a later session resumes with the two undecided drafts
    review(rig)
    assert "REVIEW_DONE accepted=2 rejected=0 remaining=0" in capsys.readouterr().out


def test_review_survives_end_of_input_and_appends_after_a_missing_newline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rig = Rig(tmp_path)
    rig.run(fresh(rig), "docs", 2)
    (rig.dir / "quoting_frozen.jsonl").write_text(json.dumps({"id": "h1"}), encoding="utf-8")  # no final newline
    capsys.readouterr()
    feed(monkeypatch, ["a"])  # then input runs out
    monkeypatch.setattr("builtins.input", _eof_after(["a"]))
    review(rig)
    lines = (rig.dir / "quoting_frozen.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0]) == {"id": "h1"} and json.loads(lines[1])["reviewed"] is True


def _eof_after(answers: list[str]) -> Callable[[str], str]:
    it = iter(answers)

    def fake(prompt: str = "") -> str:
        try:
            return next(it)
        except StopIteration:
            raise EOFError from None

    return fake
