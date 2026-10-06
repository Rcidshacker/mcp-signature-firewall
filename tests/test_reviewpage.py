"""The local review page: same decisions and files as the terminal review, plus a row limit and a local-only server."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
from test_drafting import Rig, fresh

from sigfw import reviewpage
from sigfw.reviewpage import ReviewError, commit, make_server


def rig_with(tmp_path: Path, n: int) -> Rig:
    rig = Rig(tmp_path)
    rig.run(fresh(rig), "docs", n)
    return rig


def lines(path: Path) -> list[dict[str, object]]:
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def do_commit(rig: Rig, decisions: object) -> tuple[int, int]:
    return commit(decisions, staging=rig.staging, own_dir=rig.dir, log_path=rig.dir / "log.jsonl")


def test_commit_writes_the_same_rows_and_log_as_the_terminal_review(tmp_path: Path) -> None:
    rig = rig_with(tmp_path, 3)
    staged = rig.rows()
    decisions = [
        {"id": staged[0]["id"], "decision": "accept", "reason": None},
        {"id": staged[1]["id"], "decision": "reject", "reason": "not_benign"},
    ]
    assert do_commit(rig, decisions) == (1, 1)
    accepted = lines(rig.dir / "quoting_frozen.jsonl")
    assert [r["id"] for r in accepted] == [staged[0]["id"]]
    assert accepted[0]["reviewed"] is True and accepted[0]["text"] == staged[0]["text"]
    log = lines(rig.dir / "log.jsonl")
    assert [(e["decision"], e["reason"]) for e in log] == [("accept", None), ("reject", "not_benign")]
    assert [r["id"] for r in reviewpage.pending(rig.staging, rig.dir / "log.jsonl")] == [staged[2]["id"]]


@pytest.mark.parametrize(
    "bad",
    [
        {"id": "nope", "decision": "accept", "reason": None},
        {"id": "X", "decision": "reject", "reason": "i_felt_like_it"},
        {"id": "X", "decision": "maybe", "reason": None},
        {"id": "X", "decision": "reject"},
    ],
)
def test_a_bad_batch_is_refused_whole_and_writes_nothing(tmp_path: Path, bad: dict[str, object]) -> None:
    rig = rig_with(tmp_path, 2)
    first = rig.rows()[0]["id"]
    good = {"id": first, "decision": "accept", "reason": None}
    if bad["id"] == "X":
        bad = {**bad, "id": rig.rows()[1]["id"]}
    with pytest.raises(ReviewError):
        do_commit(rig, [good, bad])
    assert not (rig.dir / "quoting_frozen.jsonl").exists() and not (rig.dir / "log.jsonl").exists()


def test_a_decided_draft_cannot_be_decided_again_or_listed_twice(tmp_path: Path) -> None:
    rig = rig_with(tmp_path, 2)
    one = {"id": rig.rows()[0]["id"], "decision": "accept", "reason": None}
    with pytest.raises(ReviewError):
        do_commit(rig, [one, one])
    do_commit(rig, [one])
    with pytest.raises(ReviewError):
        do_commit(rig, [one])
    assert len(lines(rig.dir / "quoting_frozen.jsonl")) == 1


def test_the_frozen_slice_cannot_go_past_200_rows(tmp_path: Path) -> None:
    rig = rig_with(tmp_path, 3)
    frozen = rig.dir / "quoting_frozen.jsonl"
    frozen.write_text("".join(json.dumps({"id": f"h{i}"}) + "\n" for i in range(198)), encoding="utf-8")
    template = json.dumps({"id": "TEMPLATE-1"}) + "\n"  # template rows are not counted
    frozen.write_text(frozen.read_text(encoding="utf-8") + template, encoding="utf-8")
    before = frozen.read_bytes()
    ids = [r["id"] for r in rig.rows()]
    accept = [{"id": i, "decision": "accept", "reason": None} for i in ids]
    with pytest.raises(ReviewError, match="200"):
        do_commit(rig, accept)  # 198 + 3 = 201
    assert frozen.read_bytes() == before
    assert do_commit(rig, accept[:2]) == (2, 0)  # exactly 200 is allowed
    assert len(lines(frozen)) == 201  # 198 + template + 2


@pytest.fixture
def server(tmp_path: Path) -> Iterator[tuple[str, str, Rig]]:
    rig = rig_with(tmp_path, 2)
    srv, token = make_server(rig.staging, rig.dir, rig.dir / "log.jsonl", port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}", token, rig
    srv.shutdown()
    srv.server_close()


def post(url: str, body: object, token: str | None, host: str | None = None) -> tuple[int, dict[str, object]]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Token"] = token
    if host:
        headers["Host"] = host
    req = urllib.request.Request(url + "/commit", json.dumps(body).encode(), headers, method="POST")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, json.loads(raw) if raw.startswith(b"{") else {}


def test_the_page_lists_the_pending_drafts_and_posts_need_the_token(server: tuple[str, str, Rig]) -> None:
    url, token, rig = server
    html = urllib.request.urlopen(url + "/").read().decode("utf-8")
    assert token in html and all(r["id"] in html for r in rig.rows())
    decision = [{"id": rig.rows()[0]["id"], "decision": "accept", "reason": None}]
    assert post(url, decision, None)[0] == 403
    assert post(url, decision, "wrong")[0] == 403
    assert post(url, decision, token, host="evil.example")[0] == 403
    assert not (rig.dir / "quoting_frozen.jsonl").exists()
    code, body = post(url, decision, token)
    assert code == 200 and body["accepted"] == 1
    assert len(lines(rig.dir / "quoting_frozen.jsonl")) == 1


def test_a_refused_batch_answers_400_with_the_reason(server: tuple[str, str, Rig]) -> None:
    url, token, _ = server
    code, body = post(url, [{"id": "ghost", "decision": "accept", "reason": None}], token)
    assert code == 400 and "ghost" in str(body["error"])


def test_draft_text_cannot_break_out_of_the_page(tmp_path: Path) -> None:
    staging = tmp_path / "s.jsonl"
    row = {"id": "ns-x-001", "slice": "frozen", "text": "</script><img src=x onerror=alert(1)>"}
    staging.write_text(json.dumps(row) + "\n", encoding="utf-8")
    html = reviewpage.page(staging, tmp_path, tmp_path / "log.jsonl", "tok")
    assert "</script><img" not in html and "\\u003c/script>" in html
