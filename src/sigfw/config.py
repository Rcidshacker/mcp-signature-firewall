"""Settings from environment variables. The API key is never rendered in repr/str or error messages."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

DEFAULT_NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "nvidia/nemotron-3.5-lightning-30b-a3b"
ENDPOINTS = ("nvidia", "nebius")


class ConfigError(ValueError):
    """Raised for missing or invalid configuration. Messages name variables, never values."""


@dataclass(frozen=True)
class Settings:
    endpoint: str
    base_url: str
    model: str
    api_key: str = field(repr=False)
    extra_body: dict[str, Any] = field(default_factory=dict)
    max_rpm: float = 0.0  # requests per minute across all threads; 0 means unpaced

    def __str__(self) -> str:
        return repr(self)

    def url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Settings:
        def get(name: str) -> str:
            return (env.get(name) or "").strip()

        endpoint = get("LLM_ENDPOINT") or "nvidia"
        if endpoint not in ENDPOINTS:
            raise ConfigError(f"LLM_ENDPOINT must be one of {ENDPOINTS}")
        prefix = endpoint.upper()
        key = get(f"{prefix}_API_KEY")
        if not key:
            raise ConfigError(f"{prefix}_API_KEY is not set")
        base = get(f"{prefix}_BASE_URL") or (DEFAULT_NVIDIA_BASE_URL if endpoint == "nvidia" else "")
        if not base:
            raise ConfigError(f"{prefix}_BASE_URL is not set")
        extra: dict[str, Any] = {}
        raw_extra = get("LLM_EXTRA_BODY")
        if raw_extra:
            try:
                parsed = json.loads(raw_extra)
            except ValueError as e:
                raise ConfigError("LLM_EXTRA_BODY must be a JSON object") from e
            if not isinstance(parsed, dict):
                raise ConfigError("LLM_EXTRA_BODY must be a JSON object")
            extra = parsed
        raw_rpm = get("LLM_MAX_RPM")
        try:
            max_rpm = float(raw_rpm) if raw_rpm else 0.0
        except ValueError as e:
            raise ConfigError("LLM_MAX_RPM must be a number") from e
        if max_rpm < 0:
            raise ConfigError("LLM_MAX_RPM must not be negative")
        return cls(
            endpoint=endpoint,
            base_url=base.rstrip("/"),
            model=get("LLM_MODEL") or DEFAULT_MODEL,
            api_key=key,
            extra_body=extra,
            max_rpm=max_rpm,
        )
