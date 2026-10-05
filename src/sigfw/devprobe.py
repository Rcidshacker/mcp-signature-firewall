"""Dev probe: a few dev items, classified several times at temperature 0, to look at verdict mix, determinism,
errors and latency.

Non-gating, nothing is tuned from it (ADR 0001, Amendment 7). Dev items only. The report holds ids, verdicts and
timings; it never contains item text or quoted spans.
"""

from __future__ import annotations

import random
import statistics
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

from sigfw.classifier import Classifier, Ledger
from sigfw.items import HELD_OUT, Item


@dataclass(frozen=True)
class Outcome:
    verdict: str
    family: str | None
    error: str | None
    seconds: float


@dataclass(frozen=True)
class ProbeResult:
    items: list[Item]
    runs: list[list[Outcome]]
    ledgers: list[dict[str, int]]


def select_dev_items(items: list[Item], n: int, seed: int) -> list[Item]:
    """n items spread evenly over the dev families (earlier families take the remainder), chosen by a fixed seed."""
    if any(i.family in HELD_OUT for i in items):
        raise ValueError("held-out items must never reach the dev probe")
    families = sorted({i.family for i in items})
    if not families or n <= 0:
        return []
    rng = random.Random(seed)
    chosen: list[Item] = []
    for k, fam in enumerate(families):
        want = n // len(families) + (1 if k < n % len(families) else 0)
        pool = sorted((i for i in items if i.family == fam), key=lambda i: i.id)
        chosen += rng.sample(pool, min(want, len(pool)))
    return sorted(chosen, key=lambda i: i.id)


def run_probe(items: list[Item], make_classifier: Callable[[], tuple[Classifier, Ledger]], runs: int) -> ProbeResult:
    """Each run uses a fresh classifier (so a replay cache can never answer the second run)."""
    all_runs: list[list[Outcome]] = []
    ledgers: list[dict[str, int]] = []
    for _ in range(runs):
        classifier, ledger = make_classifier()
        outcomes = []
        for item in items:
            started = time.perf_counter()
            v = classifier.classify(item.text)
            outcomes.append(Outcome(v.verdict, v.family, v.error, time.perf_counter() - started))
        all_runs.append(outcomes)
        ledgers.append(ledger.snapshot())
    return ProbeResult(items, all_runs, ledgers)


@dataclass(frozen=True)
class RunSummary:
    verdicts: dict[str, int]
    errors: int
    latency_mean: float
    latency_median: float
    latency_max: float


@dataclass(frozen=True)
class Summary:
    items: int
    runs: int
    families: dict[str, int]
    verdict_agreement: int
    verdict_and_family_agreement: int
    per_run: list[RunSummary]

    @property
    def errors_total(self) -> int:
        return sum(r.errors for r in self.per_run)


def summarize(result: ProbeResult) -> Summary:
    first, *rest = result.runs
    n = len(result.items)
    verdict_agree = sum(all(r[i].verdict == first[i].verdict for r in rest) for i in range(n))
    full_agree = sum(
        all((r[i].verdict, r[i].family) == (first[i].verdict, first[i].family) for r in rest) for i in range(n)
    )
    per_run = []
    for outcomes in result.runs:
        seconds = [o.seconds for o in outcomes]
        per_run.append(
            RunSummary(
                verdicts=dict(Counter(o.verdict for o in outcomes)),
                errors=sum(o.verdict == "error" for o in outcomes),
                latency_mean=statistics.fmean(seconds) if seconds else 0.0,
                latency_median=statistics.median(seconds) if seconds else 0.0,
                latency_max=max(seconds, default=0.0),
            )
        )
    return Summary(
        items=n,
        runs=len(result.runs),
        families=dict(Counter(i.family for i in result.items)),
        verdict_agreement=verdict_agree,
        verdict_and_family_agreement=full_agree,
        per_run=per_run,
    )


def render_markdown(result: ProbeResult, *, date: str, model: str, prompt_sha256: str, seed: int) -> str:
    s = summarize(result)
    lines = [
        f"# Dev probe, {date}",
        "",
        "Non-gating (ADR 0001, Amendment 7): dev items only, temperature 0, Amendment 4 settings, nothing tuned.",
        "Every dev item is an attack, so this says nothing about false positives. Ids and verdicts only, no text.",
        "",
        f"- model: `{model}`",
        f"- prompt sha256: `{prompt_sha256}`",
        f"- items: {s.items} (seed {seed}), runs: {s.runs}, families: {s.families}",
        f"- verdict agreement between runs: {s.verdict_agreement}/{s.items}",
        f"- verdict and family agreement: {s.verdict_and_family_agreement}/{s.items}",
        f"- errors (all runs): {s.errors_total}",
        "",
        "| run | verdicts | errors | latency mean s | median s | max s | calls | prompt tokens | completion tokens |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for k, (run, ledger) in enumerate(zip(s.per_run, result.ledgers, strict=True), start=1):
        lines.append(
            f"| {k} | {run.verdicts} | {run.errors} | {run.latency_mean:.2f} | {run.latency_median:.2f} | "
            f"{run.latency_max:.2f} | {ledger['calls']} | {ledger['prompt_tokens']} | {ledger['completion_tokens']} |"
        )
    lines += ["", "| id | family | " + " | ".join(f"run {k}" for k in range(1, len(result.runs) + 1)) + " |"]
    lines.append("|---|---|" + "---|" * len(result.runs))
    for i, item in enumerate(result.items):
        cells = [
            (o.verdict if o.verdict != "error" else f"error ({o.error})") + (f" / {o.family}" if o.family else "")
            for o in (run[i] for run in result.runs)
        ]
        lines.append(f"| {item.id} | {item.family} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"
