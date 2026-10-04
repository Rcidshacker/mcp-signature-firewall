"""Seam: sigfw.probe. Non-measurement endpoint probe; uses fixed strings, never dataset items."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx

from sigfw.config import Settings
from sigfw.llm import ChatClient
from sigfw.probe import JSON_PROMPT, PROBE_PROMPT, Candidate, render_markdown, run_probe

KEY = "nvapi" + "-CANARY0123456789abcdefghijklmnopqrstuvwxyz"  # split so the repo key scan stays meaningful
SETTINGS = Settings.from_env({"NVIDIA_API_KEY": KEY, "NVIDIA_BASE_URL": "https://llm.test/v1"})


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> ChatClient:
    return ChatClient(SETTINGS, transport=httpx.MockTransport(handler), sleep=lambda _: None, rng=lambda: 0.0)


def _chat_ok(content: str) -> httpx.Response:
    return httpx.Response(
        200, json={"choices": [{"message": {"content": content}, "finish_reason": "stop"}], "usage": {}}
    )


def test_chat_candidate_records_plain_and_json_mode_results() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        return _chat_ok('{"ok": true}' if "response_format" in body else "pong")

    rows = run_probe(_client(handler), [Candidate("chat", "nvidia/a")])
    (r,) = rows
    assert (r.model, r.kind, r.ok, r.json_mode_ok, r.http_status) == ("nvidia/a", "chat", True, True, 200)
    assert r.latency_s is not None and r.latency_s >= 0


def test_json_mode_that_returns_prose_is_reported_not_ok() -> None:
    rows = run_probe(_client(lambda _: _chat_ok("pong")), [Candidate("chat", "nvidia/a")])
    assert rows[0].ok is True and rows[0].json_mode_ok is False


def test_model_that_404s_is_recorded_and_json_probe_is_skipped() -> None:
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(json.loads(req.content)["model"])
        return httpx.Response(404, json={"detail": "Function not found"})

    rows = run_probe(_client(handler), [Candidate("chat", "nvidia/gone")])
    assert rows[0].ok is False and rows[0].http_status == 404 and rows[0].json_mode_ok is None
    assert calls == ["nvidia/gone"]  # only one call: no point probing JSON mode on a dead model


def test_embedding_candidate_records_dimension() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}], "usage": {}})

    rows = run_probe(_client(handler), [Candidate("embed", "nvidia/e")])
    assert rows[0].ok is True and rows[0].embed_dim == 3 and rows[0].json_mode_ok is None


def test_every_request_uses_the_fixed_probe_string_only() -> None:
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        seen.append(body["messages"][0]["content"] if "messages" in body else body["input"][0])
        if "input" in body:
            return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0]}], "usage": {}})
        return _chat_ok("{}")

    run_probe(_client(handler), [Candidate("chat", "m1"), Candidate("embed", "m2")])
    assert len(seen) == 3  # plain + json-mode chat, one embedding
    assert set(seen) <= {PROBE_PROMPT, JSON_PROMPT}


def test_markdown_lists_each_model_and_never_leaks_the_key() -> None:
    rows = run_probe(
        _client(lambda _: httpx.Response(401, text=f"bad key {KEY}")), [Candidate("chat", "nvidia/a")]
    )
    md = render_markdown(rows, endpoint="nvidia", date="2026-10-04")
    assert "nvidia/a" in md and "401" in md and "2026-10-04" in md
    assert KEY not in md and "CANARY" not in md
