"""Seam: sigfw.textnorm.normalize (NORMALIZER_VERSION 1: surface tag chars, NFKC, strip invisibles)."""

from __future__ import annotations

import pytest

from sigfw.textnorm import NORMALIZER_VERSION, normalize


def test_version_is_frozen_at_one() -> None:
    assert NORMALIZER_VERSION == 1


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("plain text, unchanged.", "plain text, unchanged."),
        ("line1\nline2\ttab", "line1\nline2\ttab"),  # ordinary control whitespace is kept
        ("ﬁle", "file"),  # NFKC: ligature
        ("ＡＢＣ", "ABC"),  # NFKC: fullwidth
        ("ig​nore", "ignore"),  # zero-width space
        ("a‌‍b", "ab"),  # ZWNJ, ZWJ
        ("﻿start", "start"),  # BOM
        ("soft­hyphen", "softhyphen"),
        ("rtl‮text‬", "rtltext"),  # bidi override and pop
        ("word⁠joiner", "wordjoiner"),
        ("emoji️", "emoji"),  # variation selector
    ],
)
def test_normalisation_cases(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


def test_unicode_tag_characters_are_surfaced_not_decoded() -> None:
    hidden = "".join(chr(0xE0000 + ord(c)) for c in "hi")  # tag characters spelling "hi"
    out = normalize("a" + hidden + "b")
    assert out == "a<U+E0068><U+E0069>b"
    assert "hi" not in out  # v1 makes them visible; decoding is v2 and runs after the verdict


@pytest.mark.parametrize("cp", [0xE0001, 0xE0020, 0xE007E, 0xE007F])
def test_every_tag_block_codepoint_is_surfaced(cp: int) -> None:
    assert normalize(chr(cp)) == f"<U+{cp:04X}>"


def test_idempotent() -> None:
    raw = "x​ﬁ\U000e0041y"
    assert normalize(normalize(raw)) == normalize(raw)


def test_lone_surrogates_do_not_raise() -> None:
    assert normalize("a\ud800b") == "a\ud800b"
