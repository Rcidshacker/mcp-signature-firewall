"""Command line entry point. Subcommands are added milestone by milestone."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import httpx

from sigfw.config import ConfigError, Settings
from sigfw.llm import ChatClient
from sigfw.probe import DEFAULT_CANDIDATES, Candidate, render_markdown, run_probe


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sigfw")
    top = p.add_subparsers(dest="group", required=True)
    llm = top.add_parser("llm", help="LLM endpoint tools").add_subparsers(dest="cmd", required=True)
    probe = llm.add_parser("probe-models", help="one tiny call per candidate model; writes a markdown report")
    probe.add_argument("--out", type=Path, default=None, help="default: docs/api-probe-<date>.md")
    probe.add_argument("--date", default=None, help="YYYY-MM-DD (default: today, UTC)")
    return p


def _probe_models(args: argparse.Namespace, env: Mapping[str, str], transport: httpx.BaseTransport | None) -> int:
    try:
        settings = Settings.from_env(env)
    except ConfigError as e:
        print(f"sigfw: config error: {e}", file=sys.stderr)
        return 2
    date = args.date or dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    out: Path = args.out or Path("docs") / f"api-probe-{date}.md"
    with ChatClient(settings, transport=transport) as client:
        rows = run_probe(client, [Candidate(kind, model) for kind, model in DEFAULT_CANDIDATES])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_markdown(rows, endpoint=settings.endpoint, date=date), encoding="utf-8", newline="\n")
    working = sum(r.ok for r in rows)
    print(f"PROBE_DONE working={working}/{len(rows)} report={out}")
    return 0 if working else 1


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to a legacy code page
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = _build_parser()
    try:
        args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 2
        if code != 0:
            print("sigfw: unknown or incomplete command", file=sys.stderr)
        return code
    environment = os.environ if env is None else env
    if args.group == "llm" and args.cmd == "probe-models":
        return _probe_models(args, environment, transport)
    print("sigfw: unknown command", file=sys.stderr)
    return 2
