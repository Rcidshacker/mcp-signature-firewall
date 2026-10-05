"""Seams: sigfw.devprobe (select_dev_items, run_probe, summarize) and `sigfw eval dev-probe` on synthetic data.

Only the network is faked. The synthetic raw files come from test_datapipe.make_raw (filler words, no real data).
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from test_datapipe import make_raw

from sigfw.classifier import Ledger, Verdict
from sigfw.cli import main
from sigfw.devprobe import ProbeResult, run_probe, select_dev_items, summarize
from sigfw.items import HELD_OUT, Item

KEY = "nvapi" + "-CANARY0123456789abcdefghijklmnopqrstuvwxyz"  # split so the repo key scan stays meaningful
ATTACK = '{"verdict": "attack", "family": "tool_misuse", "span": "quoted"}'
BENIGN = '{"verdict": "benign", "family": null, "span": null}'


def mk(id_: str, family: str) -> Item:
    return Item(id_, "src", family, "tool_result", "attack", f"text of {id_}")


def test_selection_spreads_over_families_uses_a_fixed_seed_and_remainders_go_first() -> None:
    items = [mk(f"{f}/{n}", f) for f in ("a", "b", "c") for n in range(10)]
    chosen = select_dev_items(items, 7, seed=1)
    counts = {f: sum(i.family == f for i in chosen) for f in "abc"}
    assert counts == {"a": 3, "b": 2, "c": 2}
    assert select_dev_items(items, 7, seed=1) == chosen  # same seed, same items
    assert select_dev_items(items, 7, seed=2) != chosen  # the seed matters
    assert [i.id for i in chosen] == sorted(i.id for i in chosen)


def test_a_family_smaller_than_its_share_gives_what_it_has() -> None:
    items = [mk("a/0", "a"), *[mk(f"b/{n}", "b") for n in range(10)]]
    assert len(select_dev_items(items, 8, seed=1)) == 1 + 4


@pytest.mark.parametrize("family", sorted(HELD_OUT))
def test_held_out_items_can_never_reach_the_probe(family: str) -> None:
    with pytest.raises(ValueError, match="held-out"):
        select_dev_items([mk("x", "dev_fam"), mk("y", family)], 2, seed=1)


class ScriptedClassifier:
    def __init__(self, replies: list[Verdict]) -> None:
        self._replies = iter(replies)

    def classify(self, text: str) -> Verdict:
        return next(self._replies)


def test_summary_counts_mix_agreement_errors_and_latency() -> None:
    items = [mk(f"i{n}", "a") for n in range(4)]
    run1 = [
        Verdict("attack", family="x"),
        Verdict("attack", family="x"),
        Verdict("benign"),
        Verdict("attack", family="y"),
    ]
    run2 = [Verdict("attack", family="x"), Verdict("benign"), Verdict("benign"), Verdict("error", error="llm timeout")]
    scripted = iter([run1, run2])

    def make() -> tuple[ScriptedClassifier, Ledger]:
        return ScriptedClassifier(next(scripted)), Ledger()

    result = run_probe(items, make, runs=2)
    s = summarize(result)
    assert (s.items, s.runs) == (4, 2)
    assert s.verdict_agreement == 2  # items 0 and 2 agree; 1 and 3 differ
    assert s.verdict_and_family_agreement == 2
    assert s.per_run[0].verdicts == {"attack": 3, "benign": 1}
    assert s.per_run[1].verdicts == {"attack": 1, "benign": 2, "error": 1}
    assert [r.errors for r in s.per_run] == [0, 1] and s.errors_total == 1
    assert all(r.latency_max >= r.latency_median >= 0 for r in s.per_run)


def test_same_verdict_with_a_different_family_is_not_full_agreement() -> None:
    items = [mk("i0", "a")]
    scripted = iter([[Verdict("attack", family="x")], [Verdict("attack", family="y")]])
    result = run_probe(items, lambda: (ScriptedClassifier(next(scripted)), Ledger()), runs=2)
    s = summarize(result)
    assert s.verdict_agreement == 1 and s.verdict_and_family_agreement == 0


def run_cli(tmp_path: Path, handler, *, n: int = 6, runs: int = 2) -> tuple[int, str, Path, ProbeResult | None]:  # type: ignore[no-untyped-def]
    raw, own = make_raw(tmp_path)
    prompt = tmp_path / "p.txt"
    prompt.write_text("FIXTURE PROMPT\n", encoding="utf-8")
    out = tmp_path / "probe.md"
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = main(
            [
                "eval", "dev-probe", "--prompt", str(prompt), "--n", str(n), "--runs", str(runs),
                "--raw", str(raw), "--shadowing", str(own), "--out", str(out), "--date", "2026-10-05",
            ],
            env={"NVIDIA_API_KEY": KEY},
            transport=httpx.MockTransport(handler),
        )  # fmt: skip
    return code, buf.getvalue(), out, None


def reply(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3},
        },
    )


def test_cli_probes_only_dev_items_and_writes_a_text_free_report(tmp_path: Path) -> None:
    sent: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        sent.append(json.loads(req.content)["messages"][1]["content"])
        return reply(ATTACK)

    code, out, report, _ = run_cli(tmp_path, handler)
    assert code == 0
    assert out.startswith("PROBE_DONE items=6 runs=2 errors=0 verdict_agreement=6/6")
    assert len(sent) == 12  # 6 items x 2 runs: the second run is never answered from a cache
    md = report.read_text(encoding="utf-8")
    assert KEY not in md and "CANARY" not in md
    for family in HELD_OUT:
        assert family not in md  # held-out families never appear, not even as names
    assert "own/shadowing" not in md
    assert "prompt sha256" in md and "seed 20261005" in md
    for text in sent:  # no item text in the report
        body = text.removeprefix("<untrusted_text>\n").removesuffix("\n</untrusted_text>")
        assert body not in md


def test_cli_reports_disagreement_and_errors(tmp_path: Path) -> None:
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] <= 6:
            return reply(ATTACK)
        return reply(BENIGN if calls["n"] % 2 else "not json")  # second run: mixed benign and parse errors

    code, out, report, _ = run_cli(tmp_path, handler)
    assert code == 0
    assert "errors=3" in out and "verdict_agreement=0/6" in out
    assert "error (reply is not JSON)" in report.read_text(encoding="utf-8")


def test_cli_without_a_key_is_a_config_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    raw, own = make_raw(tmp_path)
    prompt = tmp_path / "p.txt"
    prompt.write_text("x\n", encoding="utf-8")
    code = main(["eval", "dev-probe", "--prompt", str(prompt), "--raw", str(raw), "--shadowing", str(own)], env={})
    assert code == 2 and "NVIDIA_API_KEY" in capsys.readouterr().err


def test_cli_with_a_missing_prompt_file_fails_cleanly(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    raw, own = make_raw(tmp_path)
    code = main(
        ["eval", "dev-probe", "--prompt", str(tmp_path / "nope.txt"), "--raw", str(raw), "--shadowing", str(own)],
        env={"NVIDIA_API_KEY": KEY},
    )
    assert code == 2 and "nope.txt" in capsys.readouterr().err
