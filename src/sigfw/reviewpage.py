"""A local page for reviewing staged quoting drafts (ADR 0001, Amendment 8). The human decides; nothing here judges.

Same four reject reasons, same append-only log and same accepted-row format as the terminal review, because decisions
go through drafting.apply_decision. The page keeps choices in the browser until you press Save, so a wrong key press is
undone by changing the choice. The server refuses any batch that would take a slice past its row limit.
"""

from __future__ import annotations

import json
import secrets
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from sigfw import drafting
from sigfw.quoting import DEV_RANGE, FROZEN_N, TEMPLATE_PREFIX

LIMITS = {"frozen": FROZEN_N, "dev": DEV_RANGE[1]}
MAX_BODY = 1_000_000


class ReviewError(ValueError):
    pass


def pending(staging: Path, log_path: Path) -> list[dict[str, Any]]:
    decided = {r["id"] for r in drafting.read_rows(log_path)}
    return [r for r in drafting.read_rows(staging) if r["id"] not in decided]


def have(own_dir: Path) -> dict[str, int]:
    """Rows already in each slice file, not counting TEMPLATE rows."""
    return {
        s: sum(not str(r["id"]).startswith(TEMPLATE_PREFIX) for r in drafting.read_rows(own_dir / f"quoting_{s}.jsonl"))
        for s in LIMITS
    }


def commit(decisions: object, *, staging: Path, own_dir: Path, log_path: Path) -> tuple[int, int]:
    """Validate the whole batch, then write it. Returns (accepted, rejected). Nothing is written on an error."""
    if not isinstance(decisions, list):
        raise ReviewError("decisions must be a list")
    rows = {r["id"]: r for r in pending(staging, log_path)}
    reasons = set(drafting.REJECT_REASONS.values())
    seen: set[str] = set()
    plan: list[tuple[dict[str, Any], str | None]] = []
    for d in decisions:
        if not isinstance(d, dict) or not isinstance(d.get("id"), str):
            raise ReviewError("malformed decision")
        if d["id"] not in rows or d["id"] in seen:
            raise ReviewError(f"{d['id']} is not a pending draft (or is listed twice)")
        seen.add(d["id"])
        if d.get("decision") == "accept":
            plan.append((rows[d["id"]], None))
        elif d.get("decision") == "reject" and d.get("reason") in reasons:
            plan.append((rows[d["id"]], str(d["reason"])))
        else:
            raise ReviewError(f"{d['id']}: a decision is accept or reject with one of {sorted(reasons)}")
    rows_in = have(own_dir)
    for s, limit in LIMITS.items():
        total = rows_in[s] + sum(r["slice"] == s and why is None for r, why in plan)
        if total > limit:
            raise ReviewError(f"the {s} slice would have {total} rows, over its limit of {limit}")
    for row, why in plan:
        drafting.apply_decision(row, why, own_dir, log_path)
    return sum(why is None for _, why in plan), sum(why is not None for _, why in plan)


def page(staging: Path, own_dir: Path, log_path: Path, token: str) -> str:
    data = {
        "drafts": pending(staging, log_path),
        "have": have(own_dir),
        "limits": LIMITS,
        "reasons": drafting.REJECT_REASONS,
        "token": token,
    }
    blob = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")  # a draft may contain "</script>"
    return PAGE.replace("__DATA__", blob)


def make_server(staging: Path, own_dir: Path, log_path: Path, port: int = 8765) -> tuple[HTTPServer, str]:
    token = secrets.token_urlsafe(24)

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, kind: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _local(self) -> bool:  # refuses DNS-rebinding requests that carry another Host name
            return self.headers.get("Host", "").split(":")[0] in ("127.0.0.1", "localhost")

        def do_GET(self) -> None:
            if self.path != "/" or not self._local():
                self._send(404, b"not found", "text/plain")
                return
            self._send(200, page(staging, own_dir, log_path, token).encode("utf-8"), "text/html; charset=utf-8")

        def do_POST(self) -> None:
            length = self.headers.get("Content-Length", "0")
            size = int(length) if length.isdigit() else 0
            raw = (
                self.rfile.read(size) if size <= MAX_BODY else b""
            )  # read the body first, or a refusal resets the client
            if self.path != "/commit" or not self._local() or self.headers.get("X-Token") != token:
                self._send(403, b"forbidden", "text/plain")
                return
            try:
                if size > MAX_BODY:
                    raise ReviewError("request too large")
                accepted, rejected = commit(json.loads(raw), staging=staging, own_dir=own_dir, log_path=log_path)
            except (ReviewError, ValueError) as e:
                self._send(400, json.dumps({"error": str(e)}).encode("utf-8"), "application/json")
                return
            body = {"accepted": accepted, "rejected": rejected, "have": have(own_dir)}
            self._send(200, json.dumps(body).encode("utf-8"), "application/json")

        def log_message(self, format: str, *args: object) -> None:
            pass

    return HTTPServer(("127.0.0.1", port), Handler), token


def serve(staging: Path, own_dir: Path, log_path: Path, port: int, *, open_browser: bool = True) -> int:
    server, _ = make_server(staging, own_dir, log_path, port)
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"review page: {url}  (Ctrl+C to stop; unsaved choices stay in the browser)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Quoting review</title>
<style>
:root{--bg:#fff;--fg:#1a1a1a;--mut:#666;--card:#f5f5f2;--line:#d8d8d2;--ok:#1a7f37;--no:#b3261e;--acc:#1f4fd8}
@media (prefers-color-scheme:dark){:root{--bg:#161616;--fg:#eee;--mut:#a0a0a0;--card:#202020;--line:#3a3a3a;--ok:#4cc26a;--no:#ff7b72;--acc:#7aa2ff}}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif}
main{max-width:860px;margin:0 auto;padding:16px}
.bar{display:flex;flex-wrap:wrap;gap:6px 18px;color:var(--mut);font-size:14px;margin-bottom:10px}
.bar b{color:var(--fg)}
.rule{border:1px solid var(--line);border-radius:8px;padding:8px 12px;font-size:14px;color:var(--mut);margin-bottom:12px}
.meta{font-size:14px;color:var(--mut);margin-bottom:6px}
#text{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:16px;white-space:pre-wrap;
overflow-wrap:anywhere;font:17px/1.55 ui-monospace,Consolas,monospace;min-height:140px}
.row{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}
button{font:inherit;padding:9px 14px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--fg);cursor:pointer}
button kbd{font:12px ui-monospace,monospace;opacity:.7;margin-left:6px}
#a{border-color:var(--ok);color:var(--ok)}.rj{border-color:var(--no);color:var(--no)}
#save{background:var(--acc);border-color:var(--acc);color:#fff}
.badge{display:inline-block;padding:1px 8px;border-radius:99px;font-size:13px;border:1px solid var(--line)}
#msg{min-height:1.4em;font-size:14px}
</style></head><body><main>
<div class="bar" id="bar"></div>
<div class="rule"><b>Accept</b> only if the text is benign: it quotes or discusses an attack and does not itself tell a
reader or agent to do something. <b>When in doubt, reject</b>: there are spare drafts. No editing here, by design.</div>
<div class="meta" id="meta"></div>
<div id="text"></div>
<div class="row" id="keys">
<button id="a">Accept<kbd>A</kbd></button>
<button class="rj" data-k="n">Reject: not benign<kbd>N</kbd></button>
<button class="rj" data-k="q">Reject: no attack quoted/discussed<kbd>Q</kbd></button>
<button class="rj" data-k="d">Reject: duplicate<kbd>D</kbd></button>
<button class="rj" data-k="m">Reject: malformed<kbd>M</kbd></button>
</div>
<div class="row"><button id="prev">&larr; Back</button><button id="next">Skip &rarr;</button>
<button id="save">Save decisions<kbd>S</kbd></button></div>
<div id="msg"></div>
<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const KEY = 'sigfw-review-v1';
let choice = {}; try { choice = JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) {}
const ids = new Set(D.drafts.map(d => d.id));
for (const k of Object.keys(choice)) if (!ids.has(k)) delete choice[k];
let have = D.have, i = 0;
const $ = id => document.getElementById(id);
const live = () => D.drafts.filter(d => !d.saved);
const acc = s => Object.entries(choice).filter(([k, v]) => v.decision === 'accept' && D.drafts.find(d => d.id === k).slice === s).length;
const persist = () => { try { localStorage.setItem(KEY, JSON.stringify(choice)); } catch (e) {} };
function msg(t) { $('msg').textContent = t; }
function show() {
  const L = live(); if (i >= L.length) i = Math.max(0, L.length - 1);
  const n = Object.keys(choice).length, a = Object.values(choice).filter(v => v.decision === 'accept').length;
  const left = L.length - n;
  $('bar').innerHTML = '';
  for (const [k, v] of [['Draft', L.length ? (i + 1) + '/' + L.length : '0/0'], ['Accepted (unsaved)', a],
    ['Rejected (unsaved)', n - a], ['Undecided', left],
    ['Frozen file', (have.frozen + acc('frozen')) + '/' + D.limits.frozen]]) {
    const s = document.createElement('span'); s.textContent = k + ': '; const b = document.createElement('b');
    b.textContent = v; s.appendChild(b); $('bar').appendChild(s);
  }
  if (!L.length) { $('meta').textContent = 'No pending drafts.'; $('text').textContent = ''; return; }
  const d = L[i], c = choice[d.id];
  $('meta').textContent = d.id + '  |  ' + d.source_type + '  |  ' + d.form + '  |  ' + d.channel + '  |  slice ' + d.slice +
    (c ? '  |  your choice: ' + c.decision + (c.reason ? ' (' + c.reason + ')' : '') : '');
  $('text').textContent = d.text;
}
function decide(decision, reason) {
  const L = live(); if (!L.length) return; const d = L[i];
  if (decision === 'accept' && !(choice[d.id] && choice[d.id].decision === 'accept') &&
      have[d.slice] + acc(d.slice) >= D.limits[d.slice]) { msg('The ' + d.slice + ' slice is full (' + D.limits[d.slice] + ').'); return; }
  choice[d.id] = { decision, reason: reason || null }; persist(); msg('');
  if (i < L.length - 1) i++; show();
}
async function save() {
  const body = Object.entries(choice).map(([id, v]) => ({ id, decision: v.decision, reason: v.reason }));
  if (!body.length) { msg('Nothing to save.'); return; }
  const r = await fetch('/commit', { method: 'POST', headers: { 'X-Token': D.token, 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const j = await r.json();
  if (!r.ok) { msg('Not saved: ' + j.error); return; }
  for (const d of D.drafts) if (choice[d.id]) d.saved = true;
  choice = {}; persist(); have = j.have; i = 0; msg('Saved: ' + j.accepted + ' accepted, ' + j.rejected + ' rejected.'); show();
}
$('a').onclick = () => decide('accept');
document.querySelectorAll('[data-k]').forEach(b => b.onclick = () => decide('reject', D.reasons[b.dataset.k]));
$('prev').onclick = () => { if (i > 0) i--; show(); };
$('next').onclick = () => { if (i < live().length - 1) i++; show(); };
$('save').onclick = save;
document.addEventListener('keydown', e => {
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  const k = e.key.toLowerCase();
  if (k === 'a') decide('accept'); else if (D.reasons[k]) decide('reject', D.reasons[k]);
  else if (k === 'arrowleft' || k === 'b') $('prev').click(); else if (k === 'arrowright') $('next').click();
  else if (k === 's') save();
});
window.addEventListener('beforeunload', e => { if (Object.keys(choice).length) { e.preventDefault(); e.returnValue = ''; } });
show();
</script></main></body></html>
"""  # noqa: E501
