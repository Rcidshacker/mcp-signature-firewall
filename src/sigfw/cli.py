"""Command line entry point. Subcommands are added milestone by milestone."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import httpx

from sigfw import datacmd, draftcmd, evalcmd, runcmd
from sigfw.config import ConfigError, Settings
from sigfw.llm import ChatClient
from sigfw.owndata import check_shadowing
from sigfw.probe import DEFAULT_CANDIDATES, Candidate, render_markdown, run_probe
from sigfw.quoting import SLICES, SOURCE_TYPES
from sigfw.sources import fetch_all


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sigfw")
    top = p.add_subparsers(dest="group", required=True)
    llm = top.add_parser("llm", help="LLM endpoint tools").add_subparsers(dest="cmd", required=True)
    probe = llm.add_parser("probe-models", help="one tiny call per candidate model; writes a markdown report")
    probe.add_argument("--out", type=Path, default=None, help="default: docs/api-probe-<date>.md")
    probe.add_argument("--date", default=None, help="YYYY-MM-DD (default: today, UTC)")
    ev = top.add_parser("eval", help="evaluation tools").add_subparsers(dest="cmd", required=True)
    dp = ev.add_parser("dev-probe", help="classify a few dev items twice and report mix, determinism, errors, latency")
    dp.add_argument("--prompt", type=Path, required=True)
    dp.add_argument("--n", type=int, default=24)
    dp.add_argument("--runs", type=int, default=2)
    dp.add_argument("--seed", type=int, default=20261005)
    dp.add_argument("--out", type=Path, default=None, help="default: docs/dev-probe-<date>.md")
    dp.add_argument("--date", default=None)
    dp.add_argument("--raw", type=Path, default=Path("data/raw"))
    dp.add_argument("--shadowing", type=Path, default=Path("data/own/shadowing.jsonl"))
    pc = ev.add_parser("protocol", help="check protocol.toml against the prompt, settings and the G8/G11 orderings")
    pc.add_argument("--check", action="store_true", required=True)
    pc.add_argument("--root", type=Path, default=Path("."))
    pc.add_argument("--protocol", type=Path, default=Path("protocol.toml"))
    for name, text in (("dev", "dev items through the classifier (no verdict)"), ("frozen", "the guarded frozen run")):
        sub = ev.add_parser(name, help=text)
        sub.add_argument("--raw", type=Path, default=Path("data/raw"))
        sub.add_argument("--shadowing", type=Path, default=Path("data/own/shadowing.jsonl"))
        sub.add_argument("--dir", type=Path, default=Path("data/own"))
        sub.add_argument("--runs", type=Path, default=Path("runs"))
        sub.add_argument("--workers", type=int, default=4)
        if name == "dev":
            sub.add_argument("--prompt", type=Path, required=True)
        else:
            sub.add_argument("--confirm", action="store_true")
            sub.add_argument("--new-experiment", action="store_true")
            sub.add_argument("--root", type=Path, default=Path("."))
            sub.add_argument("--manifest", type=Path, default=Path("data/manifest/split_v1.json"))
            sub.add_argument("--protocol", type=Path, default=Path("protocol.toml"))
            sub.add_argument("--ledger", type=Path, default=Path("data/frozen_runs.jsonl"))
            sub.add_argument("--docs", type=Path, default=Path("docs"))
            sub.add_argument("--date", default=None)
    data = top.add_parser("data", help="dataset tools").add_subparsers(dest="cmd", required=True)
    own = data.add_parser("check-own", help="validate the hand-written shadowing set")
    own.add_argument("--path", type=Path, default=Path("data/own/shadowing.jsonl"))
    cq = data.add_parser("check-quoting", help="validate a quoting slice (frozen needs exactly 200 reviewed rows)")
    cq.add_argument("--slice", choices=("frozen", "dev"), required=True)
    cq.add_argument("--dir", type=Path, default=Path("data/own"))
    cq.add_argument("--raw", type=Path, default=Path("data/raw"))
    cq.add_argument("--shadowing", type=Path, default=Path("data/own/shadowing.jsonl"))
    dq = data.add_parser(
        "draft-quoting", help="draft quoting candidates with Nemotron 3 Super (live; needs --confirm-live)"
    )
    dq.add_argument("--source-type", choices=SOURCE_TYPES, required=True)
    dq.add_argument("--n", type=int, required=True)
    dq.add_argument("--slice", choices=SLICES, default="frozen")
    dq.add_argument("--confirm-live", action="store_true")
    dq.add_argument("--prompts", type=Path, default=Path("data/gen_prompts"))
    dq.add_argument("--staging", type=Path, default=Path("var/drafts/staging.jsonl"))
    dq.add_argument("--ledger", type=Path, default=Path("var/drafts/ledger.jsonl"))
    dq.add_argument("--dir", type=Path, default=Path("data/own"))
    rq = data.add_parser("review-quoting", help="accept or reject staged drafts one at a time (no editing)")
    rq.add_argument("--staging", type=Path, default=Path("var/drafts/staging.jsonl"))
    rq.add_argument("--ledger", type=Path, default=Path("var/drafts/ledger.jsonl"))
    rq.add_argument("--dir", type=Path, default=Path("data/own"))
    rq.add_argument("--log", type=Path, default=Path("data/own/quoting_review_log.jsonl"))
    add = data.add_parser("add-own", help="append one author=human shadowing row from typed answers")
    add.add_argument("--path", type=Path, default=Path("data/own/shadowing.jsonl"))
    fetch = data.add_parser("fetch", help="download the pinned third-party datasets into data/raw (gitignored)")
    fetch.add_argument("--dest", type=Path, default=Path("data/raw"))
    for name, text in (
        ("stats", "per-family counts before and after dedupe (counts only)"),
        ("split", "build the split manifest, or check it against a fresh rebuild with --verify"),
        ("leakage-check", "check that no dev item is a near-duplicate of a frozen item"),
    ):
        sub = data.add_parser(name, help=text)
        sub.add_argument("--raw", type=Path, default=Path("data/raw"))
        sub.add_argument("--shadowing", type=Path, default=Path("data/own/shadowing.jsonl"))
        if name != "stats":
            sub.add_argument("--manifest", type=Path, default=Path("data/manifest/split_v1.json"))
        if name == "split":
            sub.add_argument("--verify", action="store_true")
    return p


def _fetch(args: argparse.Namespace) -> int:
    errors = fetch_all(args.dest)
    for e in errors:
        print(f"ERROR {e}")
    if errors:
        return 1
    print(f"FETCH_OK dest={args.dest}")
    return 0


def _check_own(args: argparse.Namespace) -> int:
    path: Path = args.path
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        print("shadowing n=0")
        print(f"ERROR file not found: {path}")
        return 1
    except UnicodeDecodeError:
        print("shadowing n=0")
        print(f"ERROR file is not valid UTF-8: {path}")
        return 1
    report = check_shadowing(raw)
    print(f"shadowing n={report.n}")
    for line in report.summary:
        print(line)
    for prefix, lines in (("NOTE", report.notes), ("WARN", report.warnings), ("ERROR", report.errors)):
        for line in lines:
            print(f"{prefix} {line}")
    return 0 if report.ok else 1


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
    if args.group == "data" and args.cmd == "check-own":
        return _check_own(args)
    if args.group == "eval" and args.cmd == "protocol":
        return runcmd.protocol_check(args.root, args.protocol, environment)
    if args.group == "eval" and args.cmd == "dev":
        return runcmd.dev_run(
            raw=args.raw,
            shadowing=args.shadowing,
            own_dir=args.dir,
            prompt_path=args.prompt,
            runs_dir=args.runs,
            workers=args.workers,
            env=environment,
            transport=transport,
        )
    if args.group == "eval" and args.cmd == "frozen":
        return runcmd.frozen_run(
            root=args.root,
            raw=args.raw,
            shadowing=args.shadowing,
            manifest_path=args.manifest,
            protocol_path=args.protocol,
            own_dir=args.dir,
            ledger_path=args.ledger,
            runs_dir=args.runs,
            docs_dir=args.docs,
            workers=args.workers,
            confirm=args.confirm,
            new_experiment=args.new_experiment,
            date=args.date,
            env=environment,
            transport=transport,
        )
    if args.group == "eval" and args.cmd == "dev-probe":
        return evalcmd.dev_probe(
            raw=args.raw,
            shadowing=args.shadowing,
            prompt_path=args.prompt,
            n=args.n,
            runs=args.runs,
            seed=args.seed,
            out=args.out,
            date=args.date,
            env=environment,
            transport=transport,
        )
    if args.group == "data" and args.cmd == "check-quoting":
        return datacmd.check_quoting(args.slice, args.dir, args.raw, args.shadowing)
    if args.group == "data" and args.cmd == "draft-quoting":
        return draftcmd.draft(
            source_type=args.source_type,
            n=args.n,
            slice_name=args.slice,
            confirm_live=args.confirm_live,
            prompts_dir=args.prompts,
            staging=args.staging,
            ledger_path=args.ledger,
            own_dir=args.dir,
            env=environment,
            transport=transport,
        )
    if args.group == "data" and args.cmd == "review-quoting":
        return draftcmd.review(staging=args.staging, own_dir=args.dir, log_path=args.log, ledger_path=args.ledger)
    if args.group == "data" and args.cmd == "add-own":
        return datacmd.add_own(args.path)
    if args.group == "data" and args.cmd == "fetch":
        return _fetch(args)
    if args.group == "data" and args.cmd == "stats":
        return datacmd.stats(args.raw, args.shadowing)
    if args.group == "data" and args.cmd == "split":
        return datacmd.split(args.raw, args.shadowing, args.manifest, verify=args.verify)
    if args.group == "data" and args.cmd == "leakage-check":
        return datacmd.leakage(args.raw, args.shadowing, args.manifest)
    print("sigfw: unknown command", file=sys.stderr)
    return 2
