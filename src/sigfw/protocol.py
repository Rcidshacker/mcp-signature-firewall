"""protocol.toml: the frozen measurement protocol. Only the classifier prompt path is read so far (more at M4)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


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
