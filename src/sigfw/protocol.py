"""protocol.toml: the frozen measurement protocol. Only the classifier prompt path is read so far (more at M4)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ProtocolError(ValueError):
    """The protocol file is missing, unparsable or lacks a required key."""


@dataclass(frozen=True)
class Protocol:
    prompt_path: Path


def load_protocol(path: Path) -> Protocol:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise ProtocolError(f"protocol file not found: {path}") from e
    except tomllib.TOMLDecodeError as e:
        raise ProtocolError(f"protocol file is not valid TOML: {e}") from e
    section = data.get("classifier")
    raw = section.get("prompt_path") if isinstance(section, dict) else None
    if not isinstance(raw, str) or not raw.strip():
        raise ProtocolError("[classifier] prompt_path is required in the protocol file (there is no default)")
    return Protocol(prompt_path=path.parent / raw)


@dataclass(frozen=True)
class FrozenProtocol:
    """protocol.toml as frozen before the kill run (ADR 0001, Measured system and Amendments 3 and 4)."""

    prompt_path: Path
    prompt_sha256: str
    model: str
    endpoint: str
    max_tokens: int
    temperature: float
    extra_body: dict[str, Any]
    verdict_rule: str
    error_scoring: str
    normalizer_version: int


def parse_frozen_protocol(path: Path) -> tuple[FrozenProtocol | None, list[str]]:
    """The strict protocol, or a list of what is wrong with it."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, [f"{path} not found"]
    except tomllib.TOMLDecodeError as e:
        return None, [f"{path} is not valid TOML: {e}"]
    problems: list[str] = []

    def need(section: str, key: str, kind: type | tuple[type, ...]) -> Any:
        table = data.get(section)
        value = table.get(key) if isinstance(table, dict) else None
        if value is None or isinstance(value, bool) or not isinstance(value, kind):
            problems.append(f"[{section}] {key} is required")
            return None
        return value

    prompt_path = need("classifier", "prompt_path", str)
    sha = need("classifier", "prompt_sha256", str)
    model = need("classifier", "model", str)
    endpoint = need("classifier", "endpoint", str)
    max_tokens = need("classifier", "max_tokens", int)
    temperature = need("classifier", "temperature", (int, float))
    extra = need("classifier", "extra_body", dict)
    rule = need("measurement", "verdict_rule", str)
    scoring = need("measurement", "error_scoring", str)
    norm = need("measurement", "normalizer_version", int)
    if problems:
        return None, problems
    return (
        FrozenProtocol(
            path.parent / prompt_path, sha, model, endpoint, max_tokens, temperature, extra, rule, scoring, norm
        ),
        [],
    )
