"""Handlers for `sigfw eval protocol --check`, `sigfw eval dev` and `sigfw eval frozen`.

Only the frozen run writes docs/verdict-*.md. Every classifier call goes through LlmClassifier (replay cache, ledger),
so a rerun of the same prompt and item replays instead of calling the model again.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

import httpx

from sigfw import quoting
from sigfw.classifier import Ledger, LlmClassifier, ReplayCache, Verdict, load_prompt
from sigfw.config import ConfigError, Settings
from sigfw.datacmd import _build
from sigfw.evalrun import (
    RunItem,
    attack_run_items,
    frozen_guard,
    protocol_problems,
    quoting_run_items,
    render_verdict,
    run_items,
)
from sigfw.items import HELD_OUT, LoaderError, load_all
from sigfw.llm import ChatClient
from sigfw.metrics import Scored, counts_by, error_stats, evaluate_frozen, run_is_valid
from sigfw.protocol import parse_frozen_protocol
from sigfw.split import verify_manifest


def _under(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def protocol_check(root: Path, protocol_path: Path, env: Mapping[str, str]) -> int:
    protocol_path = _under(root, protocol_path)
    try:
        problems = protocol_problems(root, protocol_path, env)
    except ConfigError as e:
        problems = [f"configuration: {e}"]
    for p in problems:
        print(f"PROTOCOL_FAIL {p}")
    if not problems:
        print("PROTOCOL_OK")
    return 1 if problems else 0


def _head(root: Path) -> str:
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False)
    return r.stdout.strip()


def _append(path: Path, event: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(event, sort_keys=True) + "\n")


def _run_log(run_dir: Path, total: int) -> Callable[[RunItem, Verdict], None]:
    """One events.jsonl line per finished item: ids and call metadata, never item text. An error verdict also writes
    its raw reply to errors.jsonl (under the gitignored runs/, because a reply can quote attack text)."""
    seen = {"n": 0, "errors": 0}

    def log(item: RunItem, v: Verdict) -> None:
        info = {k: x for k, x in (v.info or {}).items() if k != "raw"}
        meta = {"id": item.id, "family": item.family, "channel": item.channel, "label": item.label}
        _append(run_dir / "events.jsonl", {**meta, "verdict": v.verdict, "cached": v.cached, "error": v.error, **info})
        if v.verdict == "error":
            _append(run_dir / "errors.jsonl", {"id": item.id, "error": v.error, "raw": (v.info or {}).get("raw")})
        seen["n"] += 1
        seen["errors"] += v.verdict == "error"
        if seen["n"] % 25 == 0 or seen["n"] == total:
            print(f"progress {seen['n']}/{total} errors={seen['errors']}", flush=True)

    return log


def _write_results(run_dir: Path, scored: list[Scored]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    lines = (json.dumps({"id": s.id, "verdict": s.verdict}) for s in scored)  # ids and verdicts only, never text
    (run_dir / "results.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _classifier(
    settings: Settings, prompt_path: Path, run_dir: Path, transport: httpx.BaseTransport | None
) -> tuple[ChatClient, LlmClassifier]:
    client = ChatClient(settings, transport=transport)
    run_dir.mkdir(parents=True, exist_ok=True)
    clf = LlmClassifier(
        client,
        load_prompt(prompt_path),
        cache=ReplayCache(run_dir / "cache.jsonl"),
        ledger=Ledger(run_dir / "ledger.jsonl"),
    )
    return client, clf


def frozen_run(
    *,
    root: Path,
    raw: Path,
    shadowing: Path,
    manifest_path: Path,
    protocol_path: Path,
    own_dir: Path,
    ledger_path: Path,
    runs_dir: Path,
    docs_dir: Path,
    workers: int,
    confirm: bool,
    new_experiment: bool,
    date: str | None,
    env: Mapping[str, str],
    transport: httpx.BaseTransport | None,
    replay_from: Path | None = None,
) -> int:
    if not confirm:
        print("sigfw: refusing the frozen run without --confirm", file=sys.stderr)
        return 2
    protocol_path, ledger_path = _under(root, protocol_path), _under(root, ledger_path)
    if replay_from is not None:
        replay_from = _under(root, replay_from)
        if not replay_from.is_file():
            print(f"REFUSED --replay-from {replay_from} is not a file")
            return 1
    try:
        problems = frozen_guard(root, protocol_path, env, ledger_path, new_experiment=new_experiment)
        settings = Settings.from_env(env)
    except ConfigError as e:
        print(f"sigfw: {e}", file=sys.stderr)
        return 2
    if problems:
        for p in problems:
            print(f"REFUSED {p}")
        return 1

    try:
        items = load_all(raw, shadowing)
        kept, _ = _build(raw, shadowing)
        recorded = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (LoaderError, OSError) as e:
        print(f"REFUSED cannot load the data or the manifest: {e}")
        return 1
    ok, line = verify_manifest(recorded, kept)
    if not ok:
        print(f"REFUSED {line}")
        return 1
    windows = quoting.attack_windows(quoting.heldout_attacks(items))
    raws = {s: quoting.read(own_dir / f"quoting_{s}.jsonl") for s in quoting.SLICES}
    report = quoting.check_slice("frozen", raws, windows)
    if not report.ok:
        for message in report.errors:
            print(f"REFUSED quoting_frozen: {message}")
        return 1
    parse_errors: list[str] = []
    frozen_rows, _ = quoting.parse(raws["frozen"], "frozen", parse_errors)

    protocol, _ = parse_frozen_protocol(protocol_path)
    assert protocol is not None  # frozen_guard already parsed it
    day = date or dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    run_items_list: list[RunItem] = attack_run_items([i for i in kept if i.family in HELD_OUT]) + quoting_run_items(
        [row for _, row in frozen_rows]
    )
    started = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    protocol_sha = hashlib.sha256(protocol_path.read_bytes()).hexdigest()
    _append(
        ledger_path,
        {
            "event": "start",
            "utc": started,
            "head": _head(root),
            "protocol_sha256": protocol_sha,
            "new_experiment": new_experiment,
            **({"replay_from_sha256": hashlib.sha256(replay_from.read_bytes()).hexdigest()} if replay_from else {}),
        },
    )
    run_dir = runs_dir / f"frozen-{started}"
    if (
        replay_from is not None
    ):  # the cache key holds model, options, max_tokens and prompt sha, so only a match replays
        run_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(replay_from, run_dir / "cache.jsonl")
    client, clf = _classifier(settings, protocol.prompt_path, run_dir, transport)
    try:
        scored = run_items(clf, run_items_list, workers, on_result=_run_log(run_dir, len(run_items_list)))
    finally:
        client.close()
    _write_results(run_dir, scored)

    result = evaluate_frozen(scored)
    if not result.valid:
        _append(ledger_path, {"event": "finish", "verdict": "INVALID", "errors": result.errors, "n": result.n})
        print(f"RUN_INVALID errors={result.errors}/{result.n} (more than 1%); a rerun is a new experiment")
        return 1
    n_existing = len(list(docs_dir.glob(f"verdict-{day}*.md"))) if docs_dir.exists() else 0
    doc = docs_dir / (f"verdict-{day}.md" if n_existing == 0 else f"verdict-{day}-{n_existing + 1}.md")
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(
        render_verdict(
            result,
            date=day,
            head=_head(root),
            protocol_sha256=protocol_sha,
            prompt_sha256=protocol.prompt_sha256,
            model=settings.model,
            endpoint=settings.endpoint,
        ),
        encoding="utf-8",
        newline="\n",
    )
    assert result.verdict is not None
    word = "PASS" if result.verdict.passed else "FAIL"
    _append(ledger_path, {"event": "finish", "verdict": word, "errors": result.errors, "n": result.n, "doc": doc.name})
    print(f"verdict document: {doc}")
    print(f"KILL_VERDICT: {word}")
    return 0


def dev_run(
    *,
    raw: Path,
    shadowing: Path,
    own_dir: Path,
    prompt_path: Path,
    runs_dir: Path,
    workers: int,
    env: Mapping[str, str],
    transport: httpx.BaseTransport | None,
) -> int:
    """Dev items (dev-family attacks and the dev quoting slice) through the classifier. No verdict, no document."""
    try:
        settings = Settings.from_env(env)
        kept, _ = _build(raw, shadowing)
    except (ConfigError, LoaderError) as e:
        print(f"sigfw: {e}", file=sys.stderr)
        return 2
    parse_errors: list[str] = []
    dev_rows, _ = quoting.parse(quoting.read(own_dir / "quoting_dev.jsonl"), "dev", parse_errors)
    items = attack_run_items([i for i in kept if i.family not in HELD_OUT]) + quoting_run_items(
        [r for _, r in dev_rows]
    )
    started = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = runs_dir / f"dev-{started}"
    client, clf = _classifier(settings, prompt_path, run_dir, transport)
    try:
        scored = run_items(clf, items, workers, on_result=_run_log(run_dir, len(items)))
    finally:
        client.close()
    _write_results(run_dir, scored)
    n_errors, n = error_stats(scored)
    for family, (hits, total) in counts_by(scored, "attack", lambda s: s.family).items():
        print(f"{family}: detected {hits}/{total}")
    flagged, total = counts_by(scored, "benign", lambda s: "q").get("q", (0, 0))
    print(f"dev quoting: flagged {flagged}/{total}")
    print(f"DEV_DONE items={n} errors={n_errors} valid={run_is_valid(n_errors, n)} run={run_dir}")
    return 0
