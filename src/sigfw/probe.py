"""Endpoint availability probe. A NON-MEASUREMENT tool (ADR 0001, Amendment 3): it sends one fixed string,
never a dataset item, and its output feeds no result."""

from __future__ import annotations

import json
from dataclasses import dataclass

from sigfw.llm import ChatClient, LLMError

PROBE_PROMPT = "Reply with the single word: pong."
JSON_PROMPT = 'Reply with exactly this JSON object and nothing else: {"ok": true}'

DEFAULT_CANDIDATES = (
    ("chat", "nvidia/nemotron-3.5-lightning-30b-a3b"),
    ("chat", "nvidia/nemotron-3-super-120b-a12b"),
    ("chat", "nvidia/nemotron-3-ultra-550b-a55b"),
    ("chat", "nvidia/nemotron-3.5-content-safety"),
    ("embed", "nvidia/nemotron-3-embed-1b"),
)


@dataclass(frozen=True)
class Candidate:
    kind: str  # "chat" | "embed"
    model: str


@dataclass(frozen=True)
class ProbeRow:
    model: str
    kind: str
    ok: bool
    http_status: int | None
    latency_s: float | None
    json_mode_ok: bool | None
    embed_dim: int | None
    note: str


def _fail(c: Candidate, e: LLMError) -> ProbeRow:
    return ProbeRow(c.model, c.kind, False, e.status, None, None, None, f"{e.kind}: {e.detail}".strip()[:120])


def _probe_chat(client: ChatClient, c: Candidate) -> ProbeRow:
    try:
        plain = client.chat([{"role": "user", "content": PROBE_PROMPT}], max_tokens=64, model=c.model)
    except LLMError as e:
        return _fail(c, e)
    json_ok: bool | None
    note = ""
    try:
        js = client.chat([{"role": "user", "content": JSON_PROMPT}], json_mode=True, max_tokens=64, model=c.model)
        try:
            parsed = json.loads(js.content)
            json_ok = isinstance(parsed, dict)
        except ValueError:
            json_ok = False
            note = "json_mode returned non-JSON"
    except LLMError as e:
        json_ok = False
        note = f"json_mode {e.kind}"
    return ProbeRow(c.model, c.kind, True, 200, plain.latency_s, json_ok, None, note)


def _probe_embed(client: ChatClient, c: Candidate) -> ProbeRow:
    try:
        r = client.embed([PROBE_PROMPT], model=c.model, input_type="query")
    except LLMError as e:
        return _fail(c, e)
    dim = len(r.vectors[0]) if r.vectors else 0
    return ProbeRow(c.model, c.kind, dim > 0, 200, r.latency_s, None, dim, "")


def run_probe(client: ChatClient, candidates: list[Candidate]) -> list[ProbeRow]:
    return [_probe_chat(client, c) if c.kind == "chat" else _probe_embed(client, c) for c in candidates]


def render_markdown(rows: list[ProbeRow], *, endpoint: str, date: str) -> str:
    lines = [
        f"# API probe: {endpoint} ({date})",
        "",
        "Non-measurement probe (ADR 0001, Amendment 3). One fixed string per call; no dataset item was used.",
        "Listed in `/v1/models` does not mean working; this table is what actually answered.",
        "",
        "| model | kind | ok | http | latency s | JSON mode | embed dim | note |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lat = f"{r.latency_s:.2f}" if r.latency_s is not None else "-"
        js = "-" if r.json_mode_ok is None else ("yes" if r.json_mode_ok else "no")
        lines.append(
            f"| `{r.model}` | {r.kind} | {'yes' if r.ok else 'NO'} | {r.http_status or '-'} | {lat} | {js} "
            f"| {r.embed_dim or '-'} | {r.note.replace('|', '/')} |"
        )
    return "\n".join(lines) + "\n"
