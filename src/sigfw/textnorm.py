"""Text normalizer, version 1 (frozen, ADR 0001 Amendment 3.7): surface tag characters, NFKC, strip invisibles.

Decoding hidden payloads is version 2 and runs after the verdict, so v1 only makes tag characters visible.
"""

from __future__ import annotations

import re
import unicodedata

NORMALIZER_VERSION = 1

_TAG_CHARS = re.compile("[\U000e0000-\U000e007f]")  # the Unicode "Tags" block
_VARIATION_SELECTORS = re.compile("[︀-️\U000e0100-\U000e01ef]")


def _surface_tag(match: re.Match[str]) -> str:
    return f"<U+{ord(match.group()):04X}>"


def normalize(text: str) -> str:
    text = _TAG_CHARS.sub(_surface_tag, text)  # first: tag characters are format characters and would be stripped
    text = unicodedata.normalize("NFKC", text)
    text = _VARIATION_SELECTORS.sub("", text)
    return "".join(c for c in text if unicodedata.category(c) != "Cf")  # zero-width, bidi, BOM, soft hyphen, joiners
