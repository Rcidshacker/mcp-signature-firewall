"""Seam: `sigfw data stats | split | leakage-check` (argv in, exit code and stdout out) on synthetic raw data."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from test_datapipe import make_raw

from sigfw import datacmd
from sigfw.cli import main


def run(args: list[str], tmp_path: Path, raw: Path, own: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    extra = ["--raw", str(raw), "--shadowing", str(own)]
    if args[0] != "stats":
        extra += ["--manifest", str(tmp_path / "split.json")]
    code = main(["data", *args, *extra], env={})
    return code, capsys.readouterr().out


def test_split_then_verify_reports_heldout_four(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    raw, own = make_raw(tmp_path)
    code, out = run(["split"], tmp_path, raw, own, capsys)
    assert code == 0 and out.startswith("SPLIT_WRITTEN")
    code, out = run(["split", "--verify"], tmp_path, raw, own, capsys)
    assert code == 0
    assert out.startswith("MANIFEST_OK") and "heldout=4" in out


def test_manifest_file_is_lf_json_without_dataset_text(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    raw, own = make_raw(tmp_path)
    run(["split"], tmp_path, raw, own, capsys)
    data = (tmp_path / "split.json").read_bytes()
    assert b"\r" not in data
    manifest = json.loads(data)
    leaf = json.loads((raw / "mcptox" / "pure_tool.json").read_text(encoding="utf-8"))[0]
    for rec in leaf.values():
        assert rec["tool_content"] not in data.decode("utf-8")
    assert manifest["items"] and "text" not in manifest["items"][0]


def test_verify_fails_when_the_raw_data_changed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    raw, own = make_raw(tmp_path)
    run(["split"], tmp_path, raw, own, capsys)
    path = raw / "bipia" / "code_attack_train.json"
    path.write_text(path.read_text(encoding="utf-8").replace("amber", "zzzzz"), encoding="utf-8")
    code, out = run(["split", "--verify"], tmp_path, raw, own, capsys)
    assert code == 1 and out.startswith("MANIFEST_FAIL")


def test_verify_fails_without_a_manifest(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    raw, own = make_raw(tmp_path)
    code, out = run(["split", "--verify"], tmp_path, raw, own, capsys)
    assert code == 1 and "MANIFEST_FAIL" in out


def test_split_refuses_without_the_shadowing_set(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    raw, own = make_raw(tmp_path, shadowing=False)
    code, out = run(["split"], tmp_path, raw, own, capsys)
    assert code == 1 and "shadowing" in out
    assert not (tmp_path / "split.json").exists()


def test_stats_works_without_shadowing_and_says_so(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    raw, own = make_raw(tmp_path, shadowing=False)
    code, out = run(["stats"], tmp_path, raw, own, capsys)
    assert code == 0 and "heldout=3" in out and "shadowing" in out


def test_leakage_check_is_zero_on_a_clean_build(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    raw, own = make_raw(tmp_path)
    run(["split"], tmp_path, raw, own, capsys)
    code, out = run(["leakage-check"], tmp_path, raw, own, capsys)
    assert code == 0 and out.strip().endswith("LEAK=0")


def test_leakage_check_fails_and_names_the_pair(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    raw, own = make_raw(tmp_path)
    run(["split"], tmp_path, raw, own, capsys)
    monkeypatch.setattr(datacmd, "find_leaks", lambda items, split: [("dev-a", "frozen-b", 0.9)])
    code, out = run(["leakage-check"], tmp_path, raw, own, capsys)
    assert code == 1 and "LEAK dev-a ~ frozen-b" in out and out.strip().endswith("LEAK=1")


def test_leakage_check_refuses_a_stale_manifest(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    raw, own = make_raw(tmp_path)
    run(["split"], tmp_path, raw, own, capsys)
    path = raw / "injecagent" / "test_cases_dh_base.json"
    path.write_text(path.read_text(encoding="utf-8").replace("amber", "zzzzz"), encoding="utf-8")
    code, out = run(["leakage-check"], tmp_path, raw, own, capsys)
    assert code == 1 and "MANIFEST_FAIL" in out


def test_manifest_records_authors_and_the_shadowing_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    raw, own = make_raw(tmp_path)
    (own.parent / "sources").mkdir()
    (own.parent / "sources" / "gset_v1.json").write_bytes(b'{"rows": []}\n')
    (own.parent / "shadowing.commit").write_text("a" * 40 + "\n", encoding="utf-8")
    run(["split"], tmp_path, raw, own, capsys)
    manifest = json.loads((tmp_path / "split.json").read_text(encoding="utf-8"))
    info = manifest["shadowing"]
    assert info["authors"] == {"gpt": 28, "human": 7}  # make_row: every fifth row is human
    assert info["commit"] == "a" * 40
    assert info["gset_v1_sha256"] == hashlib.sha256(b'{"rows": []}\n').hexdigest()
    shadow_items = [i for i in manifest["items"] if i["family"] == "shadowing"]
    assert {i["author"] for i in shadow_items} == {"human", "gpt"}
    assert all("author" not in i for i in manifest["items"] if i["family"] != "shadowing")


def test_changing_the_pinned_commit_after_the_split_fails_verify(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    raw, own = make_raw(tmp_path)
    commit = own.parent / "shadowing.commit"
    commit.write_text("a" * 40 + "\n", encoding="utf-8")
    run(["split"], tmp_path, raw, own, capsys)
    assert run(["split", "--verify"], tmp_path, raw, own, capsys)[0] == 0
    commit.write_text("b" * 40 + "\n", encoding="utf-8")
    code, out = run(["split", "--verify"], tmp_path, raw, own, capsys)
    assert code == 1 and out.startswith("MANIFEST_FAIL")


def test_a_malformed_commit_file_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    raw, own = make_raw(tmp_path)
    (own.parent / "shadowing.commit").write_text("not-a-hash\n", encoding="utf-8")
    code, out = run(["split"], tmp_path, raw, own, capsys)
    assert code == 1 and "40-character" in out
