"""Seam: `sigfw data add-own` (typed answers in, one appended row out). It never generates or suggests text."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from test_owndata import filler, make_row, write

from sigfw.cli import main


def feed(monkeypatch: pytest.MonkeyPatch, answers: list[str]) -> list[str]:
    prompts: list[str] = []
    it: Iterator[str] = iter(answers)

    def fake_input(prompt: str = "") -> str:
        prompts.append(prompt)
        return next(it)

    monkeypatch.setattr("builtins.input", fake_input)
    return prompts


def add(path: Path) -> int:
    return main(["data", "add-own", "--path", str(path)], env={})


def test_appends_one_human_row_with_a_multiline_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path / "s.jsonl", [make_row(i, author="gpt") for i in range(35)])
    prompts = feed(monkeypatch, ["h-01", "my_technique", "end", "host.a", "target.b", "first line", "second line", "."])
    assert add(path) == 0
    rows = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 36
    assert rows[-1] == {
        "id": "h-01",
        "author": "human",
        "channel": "tool_description",
        "family": "shadowing",
        "technique": "my_technique",
        "clause_position": "end",
        "host_tool": "host.a",
        "target_tool": "target.b",
        "text": "first line\nsecond line",
    }
    out = capsys.readouterr().out
    assert "ADDED id=h-01" in out and "shadowing n=36" in out
    assert any("clause_position" in p for p in prompts)


def test_invalid_enum_and_empty_required_fields_are_asked_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path / "s.jsonl", [make_row(i) for i in range(35)])
    answers = ["", "h-02", "t", "top", "middle", "", "host", "target", "body", "."]
    feed(monkeypatch, answers)
    assert add(path) == 0
    last = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
    assert last["id"] == "h-02" and last["clause_position"] == "middle" and last["host_tool"] == "host"
    assert "must be one of" in capsys.readouterr().out


def test_a_near_duplicate_is_rejected_and_the_file_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path / "s.jsonl", [make_row(i) for i in range(35)])
    before = path.read_bytes()
    feed(monkeypatch, ["h-03", "t", "start", "h", "g", str(make_row(4)["text"]) + " extra", "."])
    assert add(path) == 1
    assert path.read_bytes() == before
    assert "near-duplicate" in capsys.readouterr().out


def test_a_duplicate_id_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = write(tmp_path / "s.jsonl", [make_row(i) for i in range(35)])
    before = path.read_bytes()
    feed(monkeypatch, ["s000", "t", "start", "h", "g", filler(555), "."])
    assert add(path) == 1 and path.read_bytes() == before


def test_creates_the_file_when_missing_and_adds_the_row_even_below_the_minimum(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "new.jsonl"
    feed(monkeypatch, ["h-01", "t", "start", "h", "g", filler(1), "."])
    assert add(path) == 0  # n is below 35 while the author is still writing rows; that alone never blocks an add
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_a_file_without_a_trailing_newline_is_not_corrupted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "s.jsonl"
    path.write_text(json.dumps(make_row(0)), encoding="utf-8", newline="\n")  # no final newline
    feed(monkeypatch, ["h-09", "t", "start", "h", "g", filler(9), "."])
    assert add(path) == 0
    assert [json.loads(ln)["id"] for ln in path.read_text(encoding="utf-8").splitlines()] == ["s000", "h-09"]


def test_end_of_input_cancels_without_writing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = write(tmp_path / "s.jsonl", [make_row(i) for i in range(35)])
    before = path.read_bytes()

    def eof(prompt: str = "") -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    assert add(path) == 1 and path.read_bytes() == before
