"""Seam: sigfw.config. The key must never appear in repr/str or error messages."""

from __future__ import annotations

import pytest

from sigfw.config import ConfigError, Settings

KEY = "nvapi" + "-CANARY0123456789abcdefghijklmnopqrstuvwxyz"  # split so the repo key scan stays meaningful


def test_defaults_for_nvidia_endpoint() -> None:
    s = Settings.from_env({"NVIDIA_API_KEY": KEY})
    assert s.endpoint == "nvidia"
    assert s.base_url == "https://integrate.api.nvidia.com/v1"
    assert s.model == "nvidia/nemotron-3.5-lightning-30b-a3b"
    assert s.api_key == KEY


def test_repr_and_str_never_contain_the_key() -> None:
    s = Settings.from_env({"NVIDIA_API_KEY": KEY})
    for text in (repr(s), str(s), f"{s}", f"{s!r}"):
        assert KEY not in text
        assert "CANARY" not in text


def test_missing_key_raises_and_names_the_variable_not_a_value() -> None:
    with pytest.raises(ConfigError, match="NVIDIA_API_KEY"):
        Settings.from_env({})
    with pytest.raises(ConfigError, match="NVIDIA_API_KEY"):
        Settings.from_env({"NVIDIA_API_KEY": "   "})


def test_trailing_slash_is_normalised_and_url_join_is_exact() -> None:
    s = Settings.from_env({"NVIDIA_API_KEY": KEY, "NVIDIA_BASE_URL": "https://example.test/v1/"})
    assert s.base_url == "https://example.test/v1"
    assert s.url("chat/completions") == "https://example.test/v1/chat/completions"
    assert s.url("/embeddings") == "https://example.test/v1/embeddings"


def test_nebius_endpoint_needs_its_own_key_and_base_url() -> None:
    env = {"LLM_ENDPOINT": "nebius", "NVIDIA_API_KEY": KEY}
    with pytest.raises(ConfigError, match="NEBIUS_API_KEY"):
        Settings.from_env(env)
    with pytest.raises(ConfigError, match="NEBIUS_BASE_URL"):
        Settings.from_env({**env, "NEBIUS_API_KEY": "k2"})
    s = Settings.from_env({**env, "NEBIUS_API_KEY": "k2", "NEBIUS_BASE_URL": "https://api.example.test/v1"})
    assert s.endpoint == "nebius"
    assert s.api_key == "k2"  # the NVIDIA key is never used for Nebius


def test_unknown_endpoint_is_rejected() -> None:
    with pytest.raises(ConfigError, match="LLM_ENDPOINT"):
        Settings.from_env({"LLM_ENDPOINT": "openai", "NVIDIA_API_KEY": KEY})


def test_blank_env_values_fall_back_to_defaults() -> None:
    s = Settings.from_env({"NVIDIA_API_KEY": KEY, "NVIDIA_BASE_URL": "", "LLM_MODEL": ""})
    assert s.base_url == "https://integrate.api.nvidia.com/v1"
    assert s.model == "nvidia/nemotron-3.5-lightning-30b-a3b"


def test_extra_body_is_parsed_from_json_env() -> None:
    raw = '{"chat_template_kwargs": {"enable_thinking": false}}'
    s = Settings.from_env({"NVIDIA_API_KEY": KEY, "LLM_EXTRA_BODY": raw})
    assert s.extra_body == {"chat_template_kwargs": {"enable_thinking": False}}
    assert Settings.from_env({"NVIDIA_API_KEY": KEY}).extra_body == {}


@pytest.mark.parametrize("raw", ["not json", "[1, 2]", '"str"', "{"])
def test_extra_body_must_be_a_json_object(raw: str) -> None:
    with pytest.raises(ConfigError, match="LLM_EXTRA_BODY"):
        Settings.from_env({"NVIDIA_API_KEY": KEY, "LLM_EXTRA_BODY": raw})
