"""Handler for `sigfw eval dev-probe`."""

from __future__ import annotations

import datetime as dt
import sys
from collections.abc import Mapping
from pathlib import Path

import httpx

from sigfw.classifier import Classifier, Ledger, LlmClassifier, ReplayCache, load_prompt
from sigfw.config import ConfigError, Settings
from sigfw.datacmd import _build
from sigfw.devprobe import render_markdown, run_probe, select_dev_items, summarize
from sigfw.items import HELD_OUT, LoaderError
from sigfw.llm import ChatClient


def dev_probe(
    *,
    raw: Path,
    shadowing: Path,
    prompt_path: Path,
    n: int,
    runs: int,
    seed: int,
    out: Path | None,
    date: str | None,
    env: Mapping[str, str],
    transport: httpx.BaseTransport | None,
) -> int:
    try:
        settings = Settings.from_env(env)
        prompt = load_prompt(prompt_path)
        kept, _ = _build(raw, shadowing)
    except (ConfigError, LoaderError, OSError) as e:
        print(f"sigfw: {e}", file=sys.stderr)
        return 2
    dev = [i for i in kept if i.family not in HELD_OUT]
    items = select_dev_items(dev, n, seed)
    if not items:
        print("sigfw: no dev items to probe", file=sys.stderr)
        return 1
    clients: list[ChatClient] = []

    def make() -> tuple[Classifier, Ledger]:
        client = ChatClient(settings, transport=transport)
        clients.append(client)
        ledger = Ledger()
        return LlmClassifier(client, prompt, cache=ReplayCache(), ledger=ledger), ledger

    try:
        result = run_probe(items, make, runs)
    finally:
        for c in clients:
            c.close()
    day = date or dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    target = out or Path("docs") / f"dev-probe-{day}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        render_markdown(result, date=day, model=settings.model, prompt_sha256=prompt.sha256, seed=seed),
        encoding="utf-8",
        newline="\n",
    )
    s = summarize(result)
    print(
        f"PROBE_DONE items={s.items} runs={s.runs} errors={s.errors_total} "
        f"verdict_agreement={s.verdict_agreement}/{s.items} out={target}"
    )
    return 0
