"""Command line entry point. Subcommands are added milestone by milestone."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    print("sigfw: no commands yet" if not args else f"sigfw: unknown command {args[0]!r}", file=sys.stderr)
    return 2
