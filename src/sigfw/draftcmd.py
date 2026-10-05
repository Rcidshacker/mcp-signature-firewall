"""Handlers for `sigfw data draft-quoting` and `sigfw data review-quoting`."""

from __future__ import annotations

import datetime as dt
import sys
from collections.abc import Mapping
from pathlib import Path

import httpx

from sigfw import drafting
from sigfw.config import ConfigError, Settings
from sigfw.llm import ChatClient
from sigfw.quoting import SLICES


def draft(
    *,
    source_type: str,
    n: int,
    slice_name: str,
    confirm_live: bool,
    prompts_dir: Path,
    staging: Path,
    ledger_path: Path,
    own_dir: Path,
    env: Mapping[str, str],
    transport: httpx.BaseTransport | None,
) -> int:
    if not confirm_live:
        print(
            "sigfw: refusing live generation without --confirm-live (the author must reply DRAFT first)",
            file=sys.stderr,
        )
        return 2
    try:
        settings = Settings.from_env(env)
        template = (prompts_dir / f"{source_type}.txt").read_text(encoding="utf-8")
    except (ConfigError, OSError) as e:
        print(f"sigfw: {e}", file=sys.stderr)
        return 2
    existing = [r["text"] for s in SLICES for r in drafting.read_rows(own_dir / f"quoting_{s}.jsonl")]
    existing += [r["text"] for r in drafting.read_rows(staging)]  # other drafts and every accepted or human row
    ledger = drafting.DraftLedger(ledger_path)
    day = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    try:
        with ChatClient(settings, transport=transport) as client:
            report = drafting.draft_quoting(
                source_type=source_type,
                n=n,
                slice_name=slice_name,
                client=client,
                template=template,
                ledger=ledger,
                staging=staging,
                existing_texts=existing,
                date=day,
            )
    except drafting.DraftError as e:
        print(f"ERROR {e}")
        return 1
    print(
        f"DRAFT_DONE source_type={source_type} requested={report.requested} calls={report.calls} kept={report.kept} "
        f"malformed={report.malformed} duplicate={report.duplicate} failed={report.failed} staging={staging}"
    )
    return 0


def review(*, staging: Path, own_dir: Path, log_path: Path, ledger_path: Path) -> int:
    accepted, rejected, left = drafting.review(staging=staging, own_dir=own_dir, log_path=log_path)
    c = drafting.counts(drafting.DraftLedger(ledger_path), log_path)
    print(f"generated: calls={c['calls']} outcomes={c['outcomes']}")
    print(f"reviewed so far: accepted={c['accepted']} rejected={c['rejected']}")
    print(f"REVIEW_DONE accepted={accepted} rejected={rejected} remaining={left}")
    return 0
