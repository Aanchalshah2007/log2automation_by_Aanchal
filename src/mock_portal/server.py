"""Mock 発注管理 portal — one screen, source and destination.

Standard library only, like the rest of this repository. Serves the reconstructed
発注管理 worklist + detail pane + commit button, and holds the case state
server-side so that the automation's read-back is a real read of real state and
not a read of something the automation itself just typed into the page.

    python3 src/mock_portal/server.py [--port 5233] [--cases 18]

Routes
    GET  /                 the screen
    GET  /api/state        the whole worklist (used by the page, and by the
                           Streamlit UI to show what is pending)
    POST /api/commit       {case_id, note} -> the portal's own commit logic.
                           Called by the PAGE, never by the automation: the
                           automation clicks #btn-rt-ok like an operator does.
    POST /api/reset        reseed, so a demo can be run twice

The commit logic here is where the seeded failures live. It is deliberately
NOT charitable: it refuses a second commit, it refuses a blank note, and for the
unregistered-supplier case it accepts the click, shows a non-committal toast and
leaves the row exactly where it was. That last one is the only failure the
automation cannot see coming, and it is what the verify step exists for.
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
import pathlib
import socket
import socketserver
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cases as case_seed  # noqa: E402

STATIC = pathlib.Path(__file__).resolve().parent / "static"

# This server's console output is Japanese. A Windows console defaults to cp1252 and
# cannot encode it, which killed the process on its own startup banner. Same fix as
# engine.py: force UTF-8 before anything is printed.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

_LOCK = threading.Lock()
_STATE: dict = {}

# THE authoritative identity of this portal process. The row state below lives in
# this process's memory and nowhere else — no state file, no second copy — so
# "which portal am I talking to" is the same question as "which process". Every
# client stamps this id into whatever it records, which is what makes a mismatch
# detectable instead of silent. See build notes §5c.
SERVER_ID = f"{os.getpid()}@{int(time.time())}"


def reset(n: int = 18) -> None:
    with _LOCK:
        _STATE["cases"] = case_seed.seed(n)
        _STATE["toast"] = ""
        _STATE["commit_log"] = []
        # A new epoch on every reset AND on every server start. Any client holding
        # a different epoch is looking at a worklist that no longer exists, and can
        # tell without having to diff the cases. This is what stops the review UI
        # and the portal from silently disagreeing about which demo is running.
        _STATE["epoch"] = uuid.uuid4().hex[:12]


def _public_state() -> dict:
    """What the page and any observer may see. `_mock` never leaves the server."""
    return {
        "epoch": _STATE["epoch"],
        "server_id": SERVER_ID,
        "pid": os.getpid(),
        "port": _STATE.get("port"),
        "screen": "発注管理",
        "system": "財務会計システム",
        "persona": "佐藤 直樹 · 経理マネージャー",
        "period": "2026年度 · 経理部門",
        "toast": _STATE["toast"],
        "cases": [
            {k: v for k, v in c.items() if k != "_mock"} for c in _STATE["cases"]
        ],
    }


def commit(case_id: str, note: str) -> dict:
    """The portal's commit. Returns {ok, code, toast}."""
    with _LOCK:
        case = next((c for c in _STATE["cases"] if c["case_id"] == case_id), None)
        if case is None:
            _STATE["toast"] = f"{case_id}: 該当データがありません"
            return {"ok": False, "code": "NO_SUCH_CASE", "toast": _STATE["toast"]}

        status = case["row_cells"]["status"]

        # A committed row is not committable again. dataset B shows 0 of 684 cases
        # committing twice, so there is no evidence anywhere that a second commit
        # is idempotent (§7.5). This mock assumes it is not.
        if status != "未処理":
            _STATE["toast"] = f"{case_id}: 既に処理済みです（ステータス {status}）"
            return {"ok": False, "code": "ALREADY_PROCESSED", "toast": _STATE["toast"]}

        if not note.strip():
            _STATE["toast"] = f"{case_id}: 処理内容が未入力です"
            return {"ok": False, "code": "NOTE_EMPTY", "toast": _STATE["toast"]}

        # The seeded verify-stage failure. The click is accepted, a toast appears,
        # and nothing is written. An automation that trusted the click would
        # report this case as done.
        if case["_mock"]["supplier_unregistered"]:
            _STATE["toast"] = f"{case_id}: 取引先未登録のため保留となりました"
            _STATE["commit_log"].append({"case_id": case_id, "accepted": False,
                                         "reason": "supplier_unregistered"})
            return {"ok": False, "code": "SUPPLIER_UNREGISTERED", "toast": _STATE["toast"]}

        case["detail"]["comment"] = note
        case["row_cells"]["status"] = "登録済み"
        _STATE["toast"] = f"{case_id}: 登録確定しました"
        _STATE["commit_log"].append({"case_id": case_id, "accepted": True})
        return {"ok": True, "code": "COMMITTED", "toast": _STATE["toast"]}


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(STATIC), **kw)

    def log_message(self, fmt, *args):   # keep the demo terminal readable
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/state"):
            return self._json(_public_state())
        # "/", "/?embed=1", "/#/resident-tax" all mean the screen. The embed flag is
        # read client-side; the server just has to not 404 on the query string.
        if self.path.split("?")[0].split("#")[0] in ("/", ""):
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json({"ok": False, "code": "BAD_JSON"}, 400)

        if self.path.startswith("/api/commit"):
            result = commit(payload.get("case_id", ""), payload.get("note", ""))
            return self._json(result)

        if self.path.startswith("/api/reset"):
            reset(int(payload.get("cases", 18)))
            return self._json({"ok": True, "epoch": _STATE["epoch"],
                               "server_id": SERVER_ID, "pid": os.getpid(),
                               "committable": sum(
                                   1 for c in _STATE["cases"]
                                   if c["row_cells"]["status"] == "未処理")})

        return self._json({"ok": False, "code": "NOT_FOUND"}, 404)


class Server(socketserver.ThreadingTCPServer):
    daemon_threads = True

    # DO NOT set allow_reuse_address on Windows.
    #
    # This is the defect that let two portals hold 127.0.0.1:5233 at the same time
    # with different state, so RESET, the engine and the reviewer's browser tab could
    # each be talking to a different "portal". On Linux SO_REUSEADDR only relaxes
    # TIME_WAIT; on Windows it genuinely permits a SECOND process to bind an address
    # that is already bound, and the later binder can win connections. Measured:
    # two sockets bound 127.0.0.1:5399 successfully with SO_REUSEADDR set, and the
    # second bind was correctly refused with errno 10048 without it.
    allow_reuse_address = (os.name == "posix")

    def server_bind(self):
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            # Belt and braces: ask Windows to refuse any other binder outright.
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def probe_existing_portal(port: int) -> dict | None:
    """Is a portal already serving this port? Returns its identity, or None.

    Checked BEFORE binding. Without this, a second `server.py --port 5233` on a
    machine where the bind is permitted starts silently and the demo then has two
    authoritative states. Failing loudly here is the whole point.
    """
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=2) as r:
            data = json.loads(r.read().decode("utf-8"))
        if "cases" in data:
            return data
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError):
        pass
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5233)
    ap.add_argument("--cases", type=int, default=18)
    args = ap.parse_args()

    existing = probe_existing_portal(args.port)
    if existing is not None:
        print(f"REFUSING TO START: a 発注管理 portal is already serving "
              f"http://127.0.0.1:{args.port}/")
        print(f"  its server_id is {existing.get('server_id')} "
              f"(pid {existing.get('pid')}), epoch {existing.get('epoch')}, "
              f"{len(existing.get('cases', []))} cases.")
        print("  Two portals on one port means two different states behind one URL,")
        print("  which is exactly the failure this check exists to prevent.")
        print("  Stop that process first, or start this one on another --port.")
        raise SystemExit(2)

    _STATE["port"] = args.port
    reset(args.cases)
    with Server(("127.0.0.1", args.port), Handler) as httpd:
        committable = sum(1 for c in _STATE["cases"]
                          if c["row_cells"]["status"] == "未処理")
        seeded = sum(1 for c in _STATE["cases"] if c["_mock"]["seeded_failure"])
        print(f"発注管理 mock portal  ->  http://127.0.0.1:{args.port}/")
        print(f"  server_id {SERVER_ID}   epoch {_STATE['epoch']}")
        print(f"  {args.cases} synthetic cases · {committable} in 未処理 · "
              f"{seeded} deliberately unautomatable "
              f"({args.cases - seeded} expected to automate)")
        print("  THIS PROCESS HOLDS THE AUTHORITATIVE PORTAL STATE.")
        print("  Ctrl-C to stop")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")


if __name__ == "__main__":
    main()
