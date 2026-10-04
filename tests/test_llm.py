"""Seam: sigfw.llm.ChatClient. Only the network is faked (httpx.MockTransport); sleep and rng are injected."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from sigfw.config import Settings
from sigfw.llm import ChatClient, LLMError

KEY = "nvapi" + "-CANARY0123456789abcdefghijklmnopqrstuvwxyz"  # split so the repo key scan stays meaningful
SETTINGS = Settings.from_env({"NVIDIA_API_KEY": KEY, "NVIDIA_BASE_URL": "https://llm.test/v1/"})
OK_BODY = {
    "choices": [{"message": {"content": '{"verdict":"benign"}'}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 11, "completion_tokens": 5, "total_tokens": 16},
}


def make_client(handler: Callable[[httpx.Request], httpx.Response]) -> tuple[ChatClient, list[float]]:
    sleeps: list[float] = []
    client = ChatClient(
        SETTINGS,
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
        rng=lambda: 1.0,  # full jitter at its maximum: delay == cap, so tests are exact
    )
    return client, sleeps


def test_success_sends_expected_request_and_parses_result() -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=OK_BODY)

    client, sleeps = make_client(handler)
    r = client.chat([{"role": "user", "content": "hi"}], json_mode=True, max_tokens=64)
    assert r.content == '{"verdict":"benign"}'
    assert r.finish_reason == "stop"
    assert (r.prompt_tokens, r.completion_tokens) == (11, 5)
    assert r.attempts == 1 and r.latency_s >= 0 and sleeps == []

    req = seen[0]
    assert str(req.url) == "https://llm.test/v1/chat/completions"  # trailing slash in base_url handled
    assert req.headers["authorization"] == f"Bearer {KEY}"
    body = json.loads(req.content)
    assert body["model"] == SETTINGS.model
    assert body["temperature"] == 0
    assert body["max_tokens"] == 64
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"] == [{"role": "user", "content": "hi"}]


def test_json_mode_off_omits_response_format() -> None:
    seen: list[dict[str, object]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(json.loads(req.content))
        return httpx.Response(200, json=OK_BODY)

    client, _ = make_client(handler)
    client.chat([{"role": "user", "content": "hi"}])
    assert "response_format" not in seen[0]


def test_429_then_success_honours_retry_after_seconds() -> None:
    calls = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "7"}, json={"error": "slow down"})
        return httpx.Response(200, json=OK_BODY)

    client, sleeps = make_client(handler)
    r = client.chat([{"role": "user", "content": "hi"}])
    assert r.attempts == 2 and r.retries_429 == 1
    assert sleeps == [7.0]


def test_5xx_is_retried_with_capped_exponential_backoff() -> None:
    calls = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503) if calls["n"] < 3 else httpx.Response(200, json=OK_BODY)

    client, sleeps = make_client(handler)
    r = client.chat([{"role": "user", "content": "hi"}])
    assert r.attempts == 3
    assert sleeps == [1.0, 2.0]  # base 1 s, doubling, jitter fixed at max by the injected rng


def test_gives_up_after_max_attempts_with_a_typed_error() -> None:
    client, sleeps = make_client(lambda _: httpx.Response(429, json={}))
    with pytest.raises(LLMError) as ei:
        client.chat([{"role": "user", "content": "hi"}])
    assert ei.value.kind == "rate_limited"
    assert len(sleeps) == 3  # 4 attempts -> 3 sleeps


@pytest.mark.parametrize(("status", "kind"), [(400, "bad_request"), (401, "auth"), (403, "auth"), (404, "not_found")])
def test_client_errors_are_never_retried(status: int, kind: str) -> None:
    calls = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(status, json={"detail": "nope"})

    client, sleeps = make_client(handler)
    with pytest.raises(LLMError) as ei:
        client.chat([{"role": "user", "content": "hi"}])
    assert ei.value.kind == kind and ei.value.status == status
    assert calls["n"] == 1 and sleeps == []


def test_timeouts_are_retried_then_reported() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    client, sleeps = make_client(handler)
    with pytest.raises(LLMError) as ei:
        client.chat([{"role": "user", "content": "hi"}])
    assert ei.value.kind == "timeout"
    assert len(sleeps) == 3


def test_empty_content_with_length_finish_is_returned_not_raised() -> None:
    body = {"choices": [{"message": {"content": None}, "finish_reason": "length"}], "usage": {}}
    client, _ = make_client(lambda _: httpx.Response(200, json=body))
    r = client.chat([{"role": "user", "content": "hi"}])
    assert r.content == "" and r.finish_reason == "length"
    assert (r.prompt_tokens, r.completion_tokens) == (0, 0)


def test_malformed_success_body_is_a_typed_error() -> None:
    client, _ = make_client(lambda _: httpx.Response(200, json={"unexpected": True}))
    with pytest.raises(LLMError) as ei:
        client.chat([{"role": "user", "content": "hi"}])
    assert ei.value.kind == "malformed"


def test_non_json_success_body_is_a_typed_error() -> None:
    client, _ = make_client(lambda _: httpx.Response(200, text="<html>gateway</html>"))
    with pytest.raises(LLMError) as ei:
        client.chat([{"role": "user", "content": "hi"}])
    assert ei.value.kind == "malformed"


def test_errors_never_contain_the_key() -> None:
    client, _ = make_client(lambda _: httpx.Response(401, text=f"bad key {KEY}"))
    with pytest.raises(LLMError) as ei:
        client.chat([{"role": "user", "content": "hi"}])
    for text in (str(ei.value), repr(ei.value), ei.value.detail):
        assert KEY not in text and "CANARY" not in text


def test_embed_returns_vectors_in_input_order() -> None:
    seen: list[dict[str, object]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(json.loads(req.content))
        data = [{"index": 1, "embedding": [0.0, 1.0]}, {"index": 0, "embedding": [1.0, 0.0]}]  # out of order
        return httpx.Response(200, json={"data": data, "usage": {"prompt_tokens": 4, "total_tokens": 4}})

    client, _ = make_client(handler)
    r = client.embed(["a", "b"], model="nvidia/nemotron-3-embed-1b", input_type="passage")
    assert r.vectors == [[1.0, 0.0], [0.0, 1.0]]
    assert seen[0]["model"] == "nvidia/nemotron-3-embed-1b" and seen[0]["input"] == ["a", "b"]
    assert seen[0]["input_type"] == "passage"


def test_embed_malformed_is_a_typed_error() -> None:
    client, _ = make_client(lambda _: httpx.Response(200, json={"data": [{"embedding": "oops"}]}))
    with pytest.raises(LLMError) as ei:
        client.embed(["a"], model="m")
    assert ei.value.kind == "malformed"


def test_settings_extra_body_is_sent_and_a_call_level_override_wins() -> None:
    seen: list[dict[str, object]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(json.loads(req.content))
        return httpx.Response(200, json=OK_BODY)

    s = Settings.from_env(
        {"NVIDIA_API_KEY": KEY, "LLM_EXTRA_BODY": '{"chat_template_kwargs": {"enable_thinking": false}, "top_p": 1}'}
    )
    client = ChatClient(s, transport=httpx.MockTransport(handler), sleep=lambda _: None)
    client.chat([{"role": "user", "content": "hi"}])
    client.chat([{"role": "user", "content": "hi"}], extra_body={"top_p": 0.5})
    assert seen[0]["chat_template_kwargs"] == {"enable_thinking": False} and seen[0]["top_p"] == 1
    assert seen[1]["top_p"] == 0.5 and seen[1]["chat_template_kwargs"] == {"enable_thinking": False}


def test_extra_body_cannot_override_the_pinned_fields() -> None:
    seen: list[dict[str, object]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(json.loads(req.content))
        return httpx.Response(200, json=OK_BODY)

    client = ChatClient(SETTINGS, transport=httpx.MockTransport(handler), sleep=lambda _: None)
    client.chat([{"role": "user", "content": "hi"}], extra_body={"temperature": 1, "model": "other", "messages": []})
    assert seen[0]["temperature"] == 0 and seen[0]["model"] == SETTINGS.model
    assert seen[0]["messages"] == [{"role": "user", "content": "hi"}]
