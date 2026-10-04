"""LLM attack classifier: fenced prompt, strict JSON verdict, replay cache and budget ledger.

Every failure mode (LLM error, empty or truncated reply, unparsable reply, exhausted budget) becomes an `error`
verdict, never `benign`. Eval scoring treats errors pessimistically (ADR 0001, Amendment 3.5). The prompt file is
supplied by the caller (its path comes from protocol.toml); this module has no default prompt.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, Protocol

from sigfw.llm import ChatClient, ChatResult, LLMError

MAX_TOKENS = 256  # ADR 0001, Amendment 4
OPEN_TAG = "<untrusted_text>"
CLOSE_TAG = "</untrusted_text>"
_FENCE_TAG = re.compile(r"<\s*/?\s*untrusted_text\s*>", re.IGNORECASE)
_VERDICT_KEYS = {"verdict", "family", "span"}


@dataclass(frozen=True)
class Verdict:
    verdict: Literal["attack", "benign", "error"]
    family: str | None = None
    span: str | None = None
    error: str | None = None
    cached: bool = False


class Classifier(Protocol):
    def classify(self, text: str) -> Verdict: ...


@dataclass(frozen=True)
class Prompt:
    text: str
    sha256: str


def load_prompt(path: Path) -> Prompt:
    data = path.read_bytes().replace(b"\r\n", b"\n")  # hash the LF form so a CRLF checkout cannot change it
    return Prompt(text=data.decode("utf-8"), sha256=hashlib.sha256(data).hexdigest())


def _sanitize(text: str) -> str:
    # Lone surrogates (valid in JSON, unencodable in UTF-8) would crash the request body.
    return text.encode("utf-8", "surrogatepass").decode("utf-8", "replace")


def render_messages(prompt: str, text: str) -> list[dict[str, str]]:
    """Rules in the system message; the untrusted text only inside one fixed fence it cannot close or reopen."""
    safe = _FENCE_TAG.sub("[fence tag removed]", _sanitize(text))
    return [
        {"role": "system", "content": prompt},
        {"role": "user", "content": f"{OPEN_TAG}\n{safe}\n{CLOSE_TAG}"},
    ]


def _error(reason: str) -> Verdict:
    return Verdict("error", error=reason)


def parse_verdict(content: str, finish_reason: str = "stop") -> Verdict:
    if finish_reason not in ("stop", ""):
        return _error(f"finish_reason={finish_reason}")
    if not content.strip():
        return _error("empty reply")
    try:
        obj = json.loads(content)
    except ValueError:
        return _error("reply is not JSON")
    if not isinstance(obj, dict) or set(obj) != _VERDICT_KEYS:
        return _error("reply keys are not exactly verdict, family, span")
    verdict, family, span = obj["verdict"], obj["family"], obj["span"]
    if verdict == "benign":
        if family is None and span is None:
            return Verdict("benign")
        return _error("benign verdict must have null family and span")
    if verdict == "attack":
        if isinstance(family, str) and family.strip() and isinstance(span, str) and span.strip():
            return Verdict("attack", family, span)
        return _error("attack verdict needs non-empty family and span strings")
    return _error("verdict must be 'attack' or 'benign'")


class ReplayCache:
    """Verdicts keyed by model, request options, prompt hash and text hash. Optional append-only JSONL file."""

    def __init__(self, path: Path | None = None) -> None:
        self._items: dict[str, Verdict] = {}
        self._path = path
        self._lock = threading.Lock()
        self._needs_newline = False
        if path is not None and path.exists():
            raw = path.read_text(encoding="utf-8")
            self._needs_newline = bool(raw) and not raw.endswith("\n")
            for line in raw.split("\n"):
                try:
                    rec = json.loads(line)
                    self._items[rec["key"]] = Verdict(rec["verdict"], rec["family"], rec["span"])
                except (ValueError, KeyError, TypeError):
                    continue  # advisory data: a torn or foreign line only costs one repeat call

    def get(self, key: str) -> Verdict | None:
        with self._lock:
            return self._items.get(key)

    def put(self, key: str, v: Verdict) -> None:
        with self._lock:
            self._items[key] = v
            if self._path is None:
                return
            rec = json.dumps({"key": key, "verdict": v.verdict, "family": v.family, "span": v.span})
            with self._path.open("a", encoding="utf-8", newline="\n") as f:
                f.write(("\n" if self._needs_newline else "") + rec + "\n")
            self._needs_newline = False


class Ledger:
    """Counts live LLM calls, tokens, errors and cache hits; optionally logs calls to JSONL and enforces a call cap."""

    def __init__(self, path: Path | None = None, max_calls: int | None = None) -> None:
        self._path = path
        self._max = max_calls
        self._lock = threading.Lock()
        self._c = dict.fromkeys(
            ("calls", "cache_hits", "blocked", "errors", "prompt_tokens", "completion_tokens", "retries_429"), 0
        )
        if path is not None and path.exists():
            for line in path.read_text(encoding="utf-8").split("\n"):
                try:
                    rec = json.loads(line)
                    self._add(rec["ok"], rec["prompt_tokens"], rec["completion_tokens"], rec["retries_429"])
                except (ValueError, KeyError, TypeError):
                    continue

    def _add(self, ok: bool, prompt: int, completion: int, retries: int) -> None:
        self._c["calls"] += 1
        self._c["errors"] += 0 if ok else 1
        self._c["prompt_tokens"] += prompt
        self._c["completion_tokens"] += completion
        self._c["retries_429"] += retries

    def has_budget(self) -> bool:
        with self._lock:
            return self._max is None or self._c["calls"] < self._max

    def record_call(self, result: ChatResult | None, ok: bool) -> None:
        """One live call. `result` is None when the call raised (tokens unknown)."""
        prompt = result.prompt_tokens if result else 0
        completion = result.completion_tokens if result else 0
        retries = result.retries_429 if result else 0
        with self._lock:
            self._add(ok, prompt, completion, retries)
            if self._path is not None:
                rec = {"ok": ok, "prompt_tokens": prompt, "completion_tokens": completion, "retries_429": retries}
                with self._path.open("a", encoding="utf-8", newline="\n") as f:
                    f.write(json.dumps(rec) + "\n")

    def record_cache_hit(self) -> None:
        with self._lock:
            self._c["cache_hits"] += 1

    def record_blocked(self) -> None:
        with self._lock:
            self._c["blocked"] += 1

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._c)


class LlmClassifier:
    def __init__(self, client: ChatClient, prompt: Prompt, *, cache: ReplayCache, ledger: Ledger) -> None:
        self._client = client
        self._prompt = prompt
        self._cache = cache
        self._ledger = ledger
        s = client.settings
        self._key_prefix = json.dumps([s.model, s.extra_body, MAX_TOKENS, prompt.sha256], sort_keys=True)

    def _key(self, text: str) -> str:
        text_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return hashlib.sha256(f"{self._key_prefix}\n{text_sha}".encode()).hexdigest()

    def classify(self, text: str) -> Verdict:
        text = _sanitize(text)
        key = self._key(text)
        hit = self._cache.get(key)
        if hit is not None:
            self._ledger.record_cache_hit()
            return replace(hit, cached=True)
        if not self._ledger.has_budget():
            self._ledger.record_blocked()
            return _error("budget exhausted")
        try:
            result = self._client.chat(render_messages(self._prompt.text, text), json_mode=True, max_tokens=MAX_TOKENS)
        except LLMError as e:
            self._ledger.record_call(None, ok=False)
            return _error(f"llm {e.kind}")
        verdict = parse_verdict(result.content, result.finish_reason)
        self._ledger.record_call(result, ok=verdict.verdict != "error")
        if verdict.verdict != "error":
            self._cache.put(key, verdict)
        return verdict
