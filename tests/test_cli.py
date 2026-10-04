"""Seam: sigfw.cli.main (argv in, exit code and files out). Network faked with MockTransport."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from sigfw.cli import main

KEY = "nvapi" + "-CANARY0123456789abcdefghijklmnopqrstuvwxyz"  # split so the repo key scan stays meaningful


def _handler(req: httpx.Request) -> httpx.Response:
    if req.url.path.endswith("/embeddings"):
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.5, 0.5]}], "usage": {}})
    return httpx.Response(
        200, json={"choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}], "usage": {}}
    )


def test_probe_models_writes_a_report_and_exits_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "probe.md"
    code = main(
        ["llm", "probe-models", "--out", str(out), "--date", "2026-10-04"],
        env={"NVIDIA_API_KEY": KEY},
        transport=httpx.MockTransport(_handler),
    )
    assert code == 0
    md = out.read_text(encoding="utf-8")
    assert "nvidia/nemotron-3.5-lightning-30b-a3b" in md and "nvidia/nemotron-3-embed-1b" in md
    assert KEY not in md
    assert KEY not in capsys.readouterr().out


def test_probe_exits_nonzero_when_nothing_works(tmp_path: Path) -> None:
    code = main(
        ["llm", "probe-models", "--out", str(tmp_path / "p.md"), "--date", "2026-10-04"],
        env={"NVIDIA_API_KEY": KEY},
        transport=httpx.MockTransport(lambda _: httpx.Response(404, json={})),
    )
    assert code == 1


def test_missing_key_is_a_clean_error_that_names_the_variable(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["llm", "probe-models"], env={})
    assert code == 2
    assert "NVIDIA_API_KEY" in capsys.readouterr().err


def test_unknown_command_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["nope"], env={}) == 2
    assert "unknown" in capsys.readouterr().err.lower()
