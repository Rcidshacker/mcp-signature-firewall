"""Nemotron 3 Super drafting of quoting-slice candidates, and the human review of them (ADR 0001, Amendment 8).

Drafts are only candidates: author=nemotron-super, reviewed=false, in a gitignored staging file. Nothing here calls the
classifier, and no draft is selected or rejected by anything but the author's review (reasons are limited to four).
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sigfw.llm import ChatClient, LLMError
from sigfw.quoting import CHANNELS, FORMS
from sigfw.textsim import NEAR_DUP_THRESHOLD, jaccard, ngrams

SUPER_MODEL = "nvidia/nemotron-3-super-120b-a12b"
MAX_PER_TYPE = 40
MAX_TOTAL = 250
MAX_TOKENS = 700
MIN_CHARS, MAX_CHARS = 80, 2500
TOPICS = (
    "an email assistant",
    "a calendar tool",
    "a file search tool",
    "a web browsing tool",
    "a code execution sandbox",
    "a customer support bot",
    "a database query tool",
    "a note-taking app plugin",
    "a payment API",
    "a document summarizer",
    "a chat moderation bot",
    "a travel booking agent",
    "a package registry",
    "a CI pipeline",
    "a wiki search tool",
    "a ticketing system",
    "a PDF reader",
    "a spreadsheet tool",
    "a voice assistant",
    "an MCP server directory",
)
FORM_TEXT = {
    "verbatim_quote": (
        "include at least one verbatim example of an injected instruction, shown as a quote or a code block "
        "and clearly framed as an example"
    ),
    "discussion": "describe the attack in your own words, without reproducing any injected instruction",
}
CHANNEL_TEXT = {
    "tool_description": "it reads like text found in a tool's description or its documentation page",
    "tool_result": "it reads like content returned by a tool, such as a fetched page, an email or an issue",
    "other": "it reads like an ordinary article, post or note that a person reads",
}
REJECT_REASONS = {
    "n": "not_benign",
    "q": "does_not_quote_or_discuss_an_attack",
    "d": "duplicate",
    "m": "malformed",
}


class DraftError(ValueError):
    pass


def variation(k: int) -> tuple[str, str, str]:
    """(topic, form, channel) for the k-th draft of a source type; distinct for k below 40."""
    return TOPICS[(k // 2) % len(TOPICS)], FORMS[k % 2], CHANNELS[k % 3]


def render_prompt(template: str, k: int) -> tuple[str, str, str]:
    topic, form, channel = variation(k)
    prompt = (
        template.replace("<<topic>>", topic)
        .replace("<<form>>", FORM_TEXT[form])
        .replace("<<channel>>", CHANNEL_TEXT[channel])
    )
    return prompt, form, channel


def parse_draft(content: str, finish_reason: str) -> tuple[str | None, str | None]:
    """(text, None) or (None, reason). Only a JSON object {"text": str} of sensible length is accepted."""
    if finish_reason not in ("stop", ""):
        return None, f"finish_reason={finish_reason}"
    try:
        obj = json.loads(content)
    except ValueError:
        return None, "reply is not JSON"
    if not isinstance(obj, dict) or set(obj) != {"text"} or not isinstance(obj["text"], str):
        return None, "reply is not exactly {text: string}"
    text = obj["text"].strip()
    if not MIN_CHARS <= len(text) <= MAX_CHARS:
        return None, f"text length {len(text)} outside {MIN_CHARS} to {MAX_CHARS}"
    return text, None


class DraftLedger:
    """One JSONL line per generation call: model and settings, so the caps and the provenance can be audited."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.entries: list[dict[str, Any]] = []
        if path.exists():
            for line in path.read_text(encoding="utf-8").split("\n"):
                try:
                    self.entries.append(json.loads(line))
                except ValueError:
                    continue

    def generated(self, source_type: str | None = None) -> int:
        return sum(1 for e in self.entries if source_type is None or e.get("source_type") == source_type)

    def record(self, entry: dict[str, Any]) -> None:
        self.entries.append(entry)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")


@dataclass
class DraftReport:
    requested: int
    kept: int = 0
    malformed: int = 0
    duplicate: int = 0
    failed: int = 0

    @property
    def calls(self) -> int:
        return self.kept + self.malformed + self.duplicate + self.failed


def _is_duplicate(text: str, others: list[frozenset[str]]) -> bool:
    grams = ngrams(text)
    return any(jaccard(grams, other) >= NEAR_DUP_THRESHOLD for other in others)


def draft_quoting(
    *,
    source_type: str,
    n: int,
    slice_name: str,
    client: ChatClient,
    template: str,
    ledger: DraftLedger,
    staging: Path,
    existing_texts: Iterable[str],
    date: str,
) -> DraftReport:
    """Generate n drafts of one source type. The caps count calls, so a malformed or duplicate draft still uses one."""
    if n <= 0:
        raise DraftError("--n must be positive")
    if ledger.generated(source_type) + n > MAX_PER_TYPE:
        raise DraftError(
            f"cap: {ledger.generated(source_type)} {source_type} drafts already generated, "
            f"{n} more would exceed {MAX_PER_TYPE}"
        )
    if ledger.generated() + n > MAX_TOTAL:
        raise DraftError(f"cap: {ledger.generated()} drafts already generated, {n} more would exceed {MAX_TOTAL}")
    seen = [ngrams(t) for t in existing_texts]
    prompt_sha = hashlib.sha256(template.encode("utf-8")).hexdigest()
    base = ledger.generated(source_type)
    report = DraftReport(requested=n)
    settings = {
        "model": SUPER_MODEL,
        "extra_body": client.settings.extra_body,
        "max_tokens": MAX_TOKENS,
        "temperature": 0,
        "prompt_sha256": prompt_sha,
    }
    for i in range(n):
        k = base + i
        prompt, form, channel = render_prompt(template, k)
        entry: dict[str, Any] = {"source_type": source_type, "k": k, "slice": slice_name, "date": date, **settings}
        try:
            result = client.chat(
                [{"role": "system", "content": prompt}, {"role": "user", "content": "Write the document now."}],
                json_mode=True,
                max_tokens=MAX_TOKENS,
                model=SUPER_MODEL,
            )
        except LLMError as e:
            report.failed += 1
            ledger.record({**entry, "outcome": "failed", "detail": e.kind})
            continue
        text, problem = parse_draft(result.content, result.finish_reason)
        if text is None:
            report.malformed += 1
            ledger.record({**entry, "outcome": "malformed", "detail": problem})
            continue
        if _is_duplicate(text, seen):
            report.duplicate += 1
            ledger.record({**entry, "outcome": "duplicate"})
            continue
        row = {
            "id": f"ns-{source_type}-{k + 1:03d}",
            "author": "nemotron-super",
            "slice": slice_name,
            "source_type": source_type,
            "form": form,
            "channel": channel,
            "reviewed": False,
            "text": text,
        }
        staging.parent.mkdir(parents=True, exist_ok=True)
        with staging.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        seen.append(ngrams(text))
        report.kept += 1
        ledger.record({**entry, "outcome": "kept"})
    return report


def read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").split("\n"):
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _ask_choice(ask: Callable[[str], str], show: Callable[[str], None], prompt: str, allowed: Iterable[str]) -> str:
    options = tuple(allowed)
    while True:
        answer = ask(prompt).strip().lower()
        if answer in options:
            return answer
        show("type " + ", ".join(options))


def review(
    *,
    staging: Path,
    own_dir: Path,
    log_path: Path,
    ask: Callable[[str], str] | None = None,
    show: Callable[[str], None] | None = None,
) -> tuple[int, int, int]:
    """Show undecided drafts one at a time. Accept or reject only, no editing. Returns (accepted, rejected, left)."""
    ask = ask or input  # looked up at call time, so a replaced builtins.input is honoured
    show = show or print
    decided = {r["id"] for r in read_rows(log_path)}
    pending = [r for r in read_rows(staging) if r["id"] not in decided]
    accepted = rejected = 0
    reason_prompt = "reason: [n] not benign  [q] does not quote or discuss an attack  [d] duplicate  [m] malformed: "
    for index, row in enumerate(pending, start=1):
        show(f"--- draft {index}/{len(pending)}: {row['id']} | {row['source_type']} | {row['form']} | {row['channel']}")
        show(row["text"])
        try:
            choice = _ask_choice(ask, show, "[a]ccept  [r]eject  [s]top: ", ("a", "r", "s"))
            if choice == "s":
                break
            reason = _ask_choice(ask, show, reason_prompt, REJECT_REASONS) if choice == "r" else None
        except EOFError:
            break
        apply_decision(row, REJECT_REASONS[reason] if reason is not None else None, own_dir, log_path)
        if reason is None:
            accepted += 1
        else:
            rejected += 1
    return accepted, rejected, len(pending) - accepted - rejected


def apply_decision(row: dict[str, Any], reason: str | None, own_dir: Path, log_path: Path) -> None:
    """Record one human decision: a reject (reason is a REJECT_REASONS value) or an accept (reason None)."""
    entry = {"id": row["id"], "slice": row["slice"]}
    if reason is not None:
        _log(log_path, {**entry, "decision": "reject", "reason": reason})
        return
    target = own_dir / f"quoting_{row['slice']}.jsonl"
    existing = target.read_bytes() if target.exists() else b""
    prefix = "\n" if existing and not existing.endswith(b"\n") else ""
    with target.open("a", encoding="utf-8", newline="\n") as f:
        f.write(prefix + json.dumps({**row, "reviewed": True}, ensure_ascii=False) + "\n")
    _log(log_path, {**entry, "decision": "accept", "reason": None})


def _log(path: Path, entry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")


def counts(ledger: DraftLedger, log_path: Path) -> dict[str, Any]:
    """Generated vs accepted counts (Amendment 8.3): from the call ledger and the review log."""
    log = read_rows(log_path)
    return {
        "calls": ledger.generated(),
        "outcomes": dict(Counter(e.get("outcome") for e in ledger.entries)),
        "accepted": sum(r["decision"] == "accept" for r in log),
        "rejected": dict(Counter(r["reason"] for r in log if r["decision"] == "reject")),
    }
