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
import pathlib
import socketserver
import sys
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cases as case_seed  # noqa: E402

STATIC = pathlib.Path(__file__).resolve().parent / "static"

_LOCK = threading.Lock()
_STATE: dict = {}


def reset(n: int = 18) -> None:
    with _LOCK:
        _STATE["cases"] = case_seed.seed(n)
        _STATE["toast"] = ""
        _STATE["commit_log"] = []


def _public_state() -> dict:
    """What the page and any observer may see. `_mock` never leaves the server."""
    return {
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
        if self.path in ("/", ""):
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
            return self._json({"ok": True})

        return self._json({"ok": False, "code": "NOT_FOUND"}, 404)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5233)
    ap.add_argument("--cases", type=int, default=18)
    args = ap.parse_args()

    reset(args.cases)
    with Server(("127.0.0.1", args.port), Handler) as httpd:
        print(f"発注管理 mock portal  ->  http://127.0.0.1:{args.port}/")
        print(f"  {args.cases} synthetic cases seeded "
              f"({sum(1 for c in _STATE['cases'] if c['_mock']['seeded_failure'])} of them "
              f"deliberately unautomatable)")
        print("  Ctrl-C to stop")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")


if __name__ == "__main__":
    main()
