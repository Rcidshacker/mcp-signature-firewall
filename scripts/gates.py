"""Portable acceptance checks used by GATES.md. Each check prints a success-only token and exits 0, or exits 1."""

from __future__ import annotations

import subprocess
import sys

KEY_PATTERN = r"nvapi-[A-Za-z0-9_-]{20,}"


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", check=False)


def env_ignored() -> bool:
    return _git("check-ignore", ".env").returncode == 0


def env_example_not_ignored() -> bool:
    return _git("check-ignore", ".env.example").returncode == 1


def no_keys_in_tree() -> bool:
    # --untracked also scans new files that are not ignored; the ignored .env is the one place a key may live.
    r = _git("grep", "-nE", "--untracked", KEY_PATTERN)
    return r.returncode == 1 and not r.stdout


def tests_pass() -> bool:
    r = subprocess.run([sys.executable, "-m", "pytest", "-q"], capture_output=True, text=True, encoding="utf-8")
    print(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "no pytest output", file=sys.stderr)
    return r.returncode == 0


CHECKS = {
    "tests": (tests_pass, "TESTS_OK"),
    "env-ignored": (env_ignored, "ENV_IGNORED_OK"),
    "env-example-tracked": (env_example_not_ignored, "ENV_EXAMPLE_OK"),
    "no-keys": (no_keys_in_tree, "NO_KEYS_OK"),
}


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in CHECKS:
        print(f"usage: gates.py {{{'|'.join(CHECKS)}}}", file=sys.stderr)
        return 2
    check, token = CHECKS[argv[0]]
    if check():
        print(token)
        return 0
    print(f"FAILED: {argv[0]}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
