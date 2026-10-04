"""Seam: sigfw.ordering.check_prompt_order against throwaway git repositories.

Rule (hard rule 2): the pinned shadowing commit must be a strict ancestor of the first commit that touches prompts/,
and the shadowing file at that commit must itself pass `check-own`.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from test_owndata import make_row

from sigfw.ordering import PIN_FILE, check_prompt_order


def git(repo: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return r.stdout.strip()


def commit_file(repo: Path, rel: str, content: str, msg: str) -> str:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8", newline="\n")
    git(repo, "add", rel)
    git(repo, "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


def rows(n: int) -> str:
    return "".join(json.dumps(make_row(i)) + "\n" for i in range(n))


def new_repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    commit_file(tmp_path, "README.md", "x\n", "init")
    return tmp_path


def pin(repo: Path, sha: str) -> None:
    commit_file(repo, PIN_FILE, sha + "\n", "pin shadowing commit")


def test_no_prompt_anywhere_is_ok(tmp_path: Path) -> None:
    ok, msg = check_prompt_order(new_repo(tmp_path))
    assert ok and "no prompt" in msg


def test_prompt_after_pinned_shadowing_commit_is_ok(tmp_path: Path) -> None:
    repo = new_repo(tmp_path)
    sha = commit_file(repo, "data/own/shadowing.jsonl", rows(35), "shadowing")
    pin(repo, sha)
    commit_file(repo, "prompts/classifier_v1.txt", "p\n", "prompt")
    assert check_prompt_order(repo)[0]


def test_prompt_before_shadowing_fails(tmp_path: Path) -> None:
    repo = new_repo(tmp_path)
    commit_file(repo, "prompts/classifier_v1.txt", "p\n", "prompt first")
    sha = commit_file(repo, "data/own/shadowing.jsonl", rows(35), "shadowing")
    pin(repo, sha)
    ok, msg = check_prompt_order(repo)
    assert not ok and "ancestor" in msg


def test_prompt_in_the_same_commit_fails(tmp_path: Path) -> None:
    repo = new_repo(tmp_path)
    (repo / "prompts").mkdir()
    (repo / "prompts" / "p.txt").write_text("p\n", encoding="utf-8")
    (repo / "data" / "own").mkdir(parents=True)
    (repo / "data" / "own" / "shadowing.jsonl").write_text(rows(35), encoding="utf-8", newline="\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "both")
    pin(repo, git(repo, "rev-parse", "HEAD"))  # the pinned commit is the one that first adds prompts/
    ok, _ = check_prompt_order(repo)
    assert not ok


def test_prompts_but_no_pin_file_fails(tmp_path: Path) -> None:
    repo = new_repo(tmp_path)
    commit_file(repo, "prompts/classifier_v1.txt", "p\n", "prompt")
    ok, msg = check_prompt_order(repo)
    assert not ok and PIN_FILE in msg


def test_pinned_commit_with_too_few_attacks_fails(tmp_path: Path) -> None:
    repo = new_repo(tmp_path)
    sha = commit_file(repo, "data/own/shadowing.jsonl", rows(20), "shadowing")
    pin(repo, sha)
    commit_file(repo, "prompts/classifier_v1.txt", "p\n", "prompt")
    ok, msg = check_prompt_order(repo)
    assert not ok and "n=20" in msg


def test_unknown_pin_fails(tmp_path: Path) -> None:
    repo = new_repo(tmp_path)
    pin(repo, "0" * 40)
    commit_file(repo, "prompts/classifier_v1.txt", "p\n", "prompt")
    ok, msg = check_prompt_order(repo)
    assert not ok and "not a commit" in msg


def test_uncommitted_prompt_file_is_checked_against_head(tmp_path: Path) -> None:
    repo = new_repo(tmp_path)
    sha = commit_file(repo, "data/own/shadowing.jsonl", rows(35), "shadowing")
    pin(repo, sha)
    (repo / "prompts").mkdir()
    (repo / "prompts" / "p.txt").write_text("p\n", encoding="utf-8")
    assert check_prompt_order(repo)[0]
    # but an uncommitted prompt with no pin fails
    git(repo, "rm", "-q", PIN_FILE)
    git(repo, "commit", "-q", "-m", "unpin")
    assert not check_prompt_order(repo)[0]
