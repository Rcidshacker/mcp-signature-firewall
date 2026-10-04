"""Pre-registration ordering: the shadowing set is committed before any prompt file exists.

The author pins the shadowing commit in PIN_FILE. It must be a strict ancestor of the first commit that touches
prompts/ (or of HEAD while a prompt file is still uncommitted), and the shadowing file at that commit must pass the
own-data check.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from sigfw.owndata import check_shadowing

PIN_FILE = "data/own/shadowing.commit"
SHADOWING_FILE = "data/own/shadowing.jsonl"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8", check=False)


def check_prompt_order(repo: Path) -> tuple[bool, str]:
    history = _git(repo, "log", "--reverse", "--format=%H", "--", "prompts").stdout.split()
    present = _git(repo, "ls-files", "--cached", "--others", "--exclude-standard", "--", "prompts").stdout.split()
    if not history and not present:
        return True, "no prompt yet, nothing to order"

    pin_path = repo / PIN_FILE
    if not pin_path.is_file():
        return False, f"prompts exist but {PIN_FILE} is missing"
    pinned = pin_path.read_text(encoding="utf-8").strip()
    resolved = _git(repo, "rev-parse", "--verify", "--quiet", f"{pinned}^{{commit}}")
    if resolved.returncode != 0:
        return False, f"{PIN_FILE} names {pinned!r}, which is not a commit"
    pinned = resolved.stdout.strip()

    first_prompt = history[0] if history else _git(repo, "rev-parse", "HEAD").stdout.strip()
    if pinned == first_prompt or _git(repo, "merge-base", "--is-ancestor", pinned, first_prompt).returncode != 0:
        return (
            False,
            f"shadowing commit {pinned[:12]} is not a strict ancestor of the first prompt commit {first_prompt[:12]}",
        )

    shown = _git(repo, "show", f"{pinned}:{SHADOWING_FILE}")
    if shown.returncode != 0:
        return False, f"{SHADOWING_FILE} does not exist at the pinned commit"
    report = check_shadowing(shown.stdout)
    if not report.ok:
        return False, f"{SHADOWING_FILE} fails check-own at the pinned commit: n={report.n}; {report.errors[0]}"
    return True, f"shadowing commit {pinned[:12]} (n={report.n}) precedes the first prompt commit {first_prompt[:12]}"
