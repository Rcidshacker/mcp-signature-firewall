"""OpenAI-compatible client with explicit timeouts, bounded retries and typed errors.

Retries: 429 (honouring Retry-After), 5xx, timeouts and transport errors, with capped exponential backoff
and full jitter.
Never retried: other 4xx. The API key is only ever placed in the Authorization header; it is not logged or stored.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from sigfw.config import Settings

MAX_ATTEMPTS = 4
BACKOFF_BASE_S = 1.0
BACKOFF_CAP_S = 30.0
TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=10.0)
_DETAIL_LIMIT = 300


class LLMError(Exception):
    """kind: rate_limited | auth | bad_request | not_found | server | timeout | transport | malformed"""

    def __init__(self, kind: str, message: str, *, status: int | None = None, detail: str = "") -> None:
        super().__init__(f"{kind}: {message}")
        self.kind = kind
        self.status = status
        self.detail = detail


@dataclass(frozen=True)
class ChatResult:
    content: str
    finish_reason: str
    prompt_tokens: int
    completion_tokens: int
    latency_s: float
    attempts: int
    retries_429: int


@dataclass(frozen=True)
class EmbedResult:
    vectors: list[list[float]]
    prompt_tokens: int
    latency_s: float
    attempts: int


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    raw = resp.headers.get("retry-after")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        return max(0.0, parsedate_to_datetime(raw).timestamp() - time.time())
    except (TypeError, ValueError):
        return None


def _scrub(text: str, secret: str) -> str:
    return text.replace(secret, "<redacted>")[:_DETAIL_LIMIT] if secret else text[:_DETAIL_LIMIT]


class ChatClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        rng: Callable[[], float] = random.random,
    ) -> None:
        self._s = settings
        self._http = httpx.Client(transport=transport, timeout=TIMEOUT)
        self._sleep = sleep
        self._rng = rng

    @property
    def settings(self) -> Settings:
        return self._s

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> ChatClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ public API

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        json_mode: bool = False,
        max_tokens: int = 256,
        extra_body: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> ChatResult:
        # Extra options first, pinned fields last: configuration can never change model, messages or temperature.
        body: dict[str, Any] = {**self._s.extra_body, **(extra_body or {})}
        body.update(model=model or self._s.model, messages=messages, temperature=0, max_tokens=max_tokens)
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        data, latency, attempts, r429 = self._post("chat/completions", body)
        try:
            choice = data["choices"][0]
            content = choice["message"].get("content") or ""
            finish = str(choice.get("finish_reason") or "")
        except (KeyError, IndexError, TypeError, AttributeError) as e:
            raise LLMError("malformed", "chat response has no choices[0].message") from e
        usage = data.get("usage") or {}
        return ChatResult(
            content=str(content),
            finish_reason=finish,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            latency_s=latency,
            attempts=attempts,
            retries_429=r429,
        )

    def embed(self, inputs: list[str], *, model: str, input_type: str | None = None) -> EmbedResult:
        body: dict[str, Any] = {"model": model, "input": inputs}
        if input_type:
            body["input_type"] = input_type
        data, latency, attempts, _ = self._post("embeddings", body)
        try:
            rows = sorted(data["data"], key=lambda r: r.get("index", 0))
            vectors = [[float(x) for x in row["embedding"]] for row in rows]
        except (KeyError, TypeError, ValueError) as e:
            raise LLMError("malformed", "embeddings response has no usable data[].embedding") from e
        usage = data.get("usage") or {}
        return EmbedResult(vectors, int(usage.get("prompt_tokens") or 0), latency, attempts)

    # ------------------------------------------------------------------ internals

    def _post(self, path: str, body: dict[str, Any]) -> tuple[dict[str, Any], float, int, int]:
        url = self._s.url(path)
        headers = {"Authorization": f"Bearer {self._s.api_key}", "Accept": "application/json"}
        started = time.perf_counter()
        retries_429 = 0
        last: LLMError | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            wait: float | None = None
            try:
                resp = self._http.post(url, json=body, headers=headers)
            except httpx.TimeoutException as e:
                last = LLMError("timeout", type(e).__name__)
            except httpx.TransportError as e:
                last = LLMError("transport", type(e).__name__)
            else:
                status = resp.status_code
                if status == 200:
                    try:
                        data = resp.json()
                    except ValueError as e:
                        raise LLMError("malformed", "response body is not JSON", status=200) from e
                    if not isinstance(data, dict):
                        raise LLMError("malformed", "response JSON is not an object", status=200)
                    return data, time.perf_counter() - started, attempt, retries_429
                detail = _scrub(resp.text, self._s.api_key)
                if status == 429:
                    retries_429 += 1
                    wait = _retry_after_seconds(resp)
                    last = LLMError("rate_limited", "HTTP 429", status=429, detail=detail)
                elif status >= 500:
                    last = LLMError("server", f"HTTP {status}", status=status, detail=detail)
                else:
                    kind = {400: "bad_request", 401: "auth", 403: "auth", 404: "not_found"}.get(status, "bad_request")
                    raise LLMError(kind, f"HTTP {status}", status=status, detail=detail)
            if attempt == MAX_ATTEMPTS:
                break
            backoff = min(BACKOFF_CAP_S, BACKOFF_BASE_S * 2 ** (attempt - 1))
            self._sleep(min(BACKOFF_CAP_S, wait) if wait is not None else backoff * self._rng())
        assert last is not None
        raise last
