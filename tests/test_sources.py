"""Seam: sigfw.sources.fetch_all and git_blob_sha. The network is replaced by a dict-backed fetch function."""

from __future__ import annotations

import subprocess
from pathlib import Path

from sigfw.sources import PINS, Pin, fetch_all, git_blob_sha, local_path

BODY = b"hello\nworld\n"


def make_pin(name: str = "a.json", data: bytes = BODY) -> Pin:
    return Pin("src", "o/r", "c" * 40, f"data/{name}", git_blob_sha(data), len(data))


def test_git_blob_sha_matches_git_itself() -> None:
    expected = (
        subprocess.run(["git", "hash-object", "--stdin"], input=BODY, capture_output=True, check=True)
        .stdout.decode()
        .strip()
    )
    assert git_blob_sha(BODY) == expected


def test_fetch_writes_a_verified_file(tmp_path: Path) -> None:
    pin = make_pin()
    log: list[str] = []
    assert fetch_all(tmp_path, pins=(pin,), fetch=lambda url: BODY, log=log.append) == []
    assert local_path(tmp_path, pin).read_bytes() == BODY
    assert pin.url == f"https://raw.githubusercontent.com/o/r/{'c' * 40}/data/a.json"


def test_hash_mismatch_is_refused_and_nothing_is_written(tmp_path: Path) -> None:
    pin = make_pin()
    errors = fetch_all(tmp_path, pins=(pin,), fetch=lambda url: b"tampered", log=lambda _: None)
    assert len(errors) == 1 and "does not match" in errors[0]
    assert not local_path(tmp_path, pin).exists()


def test_cached_file_is_not_downloaded_again(tmp_path: Path) -> None:
    pin = make_pin()
    path = local_path(tmp_path, pin)
    path.parent.mkdir(parents=True)
    path.write_bytes(BODY)

    def boom(url: str) -> bytes:
        raise AssertionError("must not download")

    assert fetch_all(tmp_path, pins=(pin,), fetch=boom, log=lambda _: None) == []


def test_a_corrupted_cached_file_is_replaced(tmp_path: Path) -> None:
    pin = make_pin()
    path = local_path(tmp_path, pin)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"corrupt")
    assert fetch_all(tmp_path, pins=(pin,), fetch=lambda url: BODY, log=lambda _: None) == []
    assert path.read_bytes() == BODY


def test_download_failure_is_reported_per_file_and_others_continue(tmp_path: Path) -> None:
    bad, good = make_pin("bad.json"), make_pin("good.json")

    def fetch(url: str) -> bytes:
        if url.endswith("bad.json"):
            raise TimeoutError
        return BODY

    errors = fetch_all(tmp_path, pins=(bad, good), fetch=fetch, log=lambda _: None)
    assert len(errors) == 1 and "bad.json" in errors[0]
    assert local_path(tmp_path, good).exists()


def test_every_real_pin_is_a_full_commit_and_blob_sha() -> None:
    for pin in PINS:
        assert len(pin.commit) == 40 and len(pin.blob_sha) == 40 and pin.size > 0
    assert len({(p.source, p.filename) for p in PINS}) == len(PINS)  # no filename collisions inside a source
