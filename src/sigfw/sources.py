"""Pinned third-party dataset files. Nothing here is committed as data: `sigfw data fetch` downloads each file at a
fixed commit into data/raw/ (gitignored) and refuses any file whose git blob SHA differs from the pin."""

from __future__ import annotations

import hashlib
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

RAW_URL = "https://raw.githubusercontent.com/{repo}/{commit}/{path}"


@dataclass(frozen=True)
class Pin:
    source: str
    repo: str
    commit: str
    path: str
    blob_sha: str  # git blob SHA-1 of the file at that commit
    size: int

    @property
    def url(self) -> str:
        return RAW_URL.format(repo=self.repo, commit=self.commit, path=self.path)

    @property
    def filename(self) -> str:
        return self.path.rsplit("/", 1)[-1]


_MCPTOX = ("zhiqiangwang4/MCPTox-Benchmark", "f85189f9ad12504c197c7f920ab818a40657b1fa")
_BIPIA = ("microsoft/BIPIA", "a004b69ec0dd446e0afd461d98cb5e96e120a5d0")
_INJECAGENT = ("uiuc-kang-lab/InjecAgent", "f19c9f2c79a41046eb13c03c51a24c567a8ffa07")

PINS: tuple[Pin, ...] = (
    Pin("mcptox", *_MCPTOX, "pure_tool.json", "0198262328539de9d0323f3d8dd3706eb0a16aaf", 316620),
    Pin("bipia", *_BIPIA, "benchmark/code_attack_test.json", "5c55000d29c51c4349b01e68b262de6855bf0fa8", 16356),
    Pin("bipia", *_BIPIA, "benchmark/code_attack_train.json", "c9bbd9a3a7dfaebe75eac83b26cb7ddf62c1821b", 16343),
    Pin("bipia", *_BIPIA, "benchmark/text_attack_test.json", "259e58a7aaf696ecddbf664022c0f254318b0a05", 6322),
    Pin("bipia", *_BIPIA, "benchmark/text_attack_train.json", "190918308f4ef25d5f43d7c1b118bf3fe5dc61d2", 5999),
    Pin("injecagent", *_INJECAGENT, "data/attacker_cases_dh.jsonl", "a4814fa052d46694e1fbab6679f6e285f5f5b2b2", 10937),
    Pin("injecagent", *_INJECAGENT, "data/attacker_cases_ds.jsonl", "d008cc0e4be560377c07bdded1ebfb938d086081", 13209),
    Pin("injecagent", *_INJECAGENT, "data/test_cases_dh_base.json", "976ad4e2108a553a3b885951e8eb119aa91f9445", 672918),
    Pin(
        "injecagent",
        *_INJECAGENT,
        "data/test_cases_dh_enhanced.json",
        "803bd383695faaaeb2a03863aafc83d8b46a7e78",
        721878,
    ),
    Pin("injecagent", *_INJECAGENT, "data/test_cases_ds_base.json", "16f82d8a34349182eba883871333e569bafc6b93", 765370),
    Pin(
        "injecagent",
        *_INJECAGENT,
        "data/test_cases_ds_enhanced.json",
        "f4580cb98e195d3a77ec92149294cc1bf37c0f5d",
        817594,
    ),
)


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()  # noqa: S324 - git's own object id, not security


def local_path(dest: Path, pin: Pin) -> Path:
    return dest / pin.source / pin.filename


def download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310 - fixed https hosts from PINS
        data: bytes = resp.read()
    return data


def fetch_all(
    dest: Path,
    *,
    pins: tuple[Pin, ...] = PINS,
    fetch: Callable[[str], bytes] = download,
    log: Callable[[str], None] = print,
) -> list[str]:
    """Download every pin into dest/<source>/. Returns error messages; an unverified file is never written."""
    errors: list[str] = []
    for pin in pins:
        target = local_path(dest, pin)
        if target.is_file() and git_blob_sha(target.read_bytes()) == pin.blob_sha:
            log(f"ok (cached) {pin.source}/{pin.filename}")
            continue
        try:
            data = fetch(pin.url)
        except Exception as e:  # network errors are reported per file, the rest still run
            errors.append(f"{pin.source}/{pin.filename}: download failed ({type(e).__name__})")
            continue
        if git_blob_sha(data) != pin.blob_sha:
            errors.append(f"{pin.source}/{pin.filename}: blob SHA does not match the pin, file not written")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        log(f"ok {pin.source}/{pin.filename} ({len(data)} bytes)")
    return errors
