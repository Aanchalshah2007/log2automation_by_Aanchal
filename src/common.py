"""Shared loading / caching layer for the ProcMine operation logs.

The raw distribution is ~4.4 GB of JSONL because every event carries
`visible_windows`, `open_apps` and (on ~4.5% of events) OCR text.  Nothing in
the segmenter needs the bulky fields, so we project each event down to a flat
record once and cache it as JSONL under build/.  Everything downstream reads
the cache, which makes an experiment loop a few seconds instead of minutes.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Iterator

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.path.join(ROOT, "build")      # derived cache, git-ignored
REPORTS = os.path.join(ROOT, "reports")  # reviewable results, committed

DATASETS = {
    "A": os.path.join(ROOT, "dataset_a-20260913T153639Z-1-001", "dataset_a"),
    "B": os.path.join(ROOT, "dataset_b-20260913T153602Z-1-001", "dataset_b"),
}

# Each business system is served as the same SPA on its own loopback port.
# Ports differ between the two recording themes; the system behind them does not.
PORT_SYSTEM = {
    "5122": "hr", "5123": "fin", "5124": "ops",      # dataset A  (theme M1)
    "5132": "hr", "5133": "fin", "5134": "ops",      # dataset B  (theme M2)
}

# Routes that are portal *work* screens.  root/dashboard are landing pages and
# never carry case rows, so they must not anchor a process.
WORK_ROUTES = {
    "resident-tax", "payroll-items", "leave-applications",
    "social-insurance", "onboarding",
}

_URL_PORT = re.compile(r"127\.0\.0\.1:(\d+)")
_URL_ROUTE = re.compile(r"#/([a-z-]+)")


def portal_context(url: str | None) -> tuple[str, str] | None:
    """(system, route) for a portal URL, or None if it is not a work screen."""
    if not url:
        return None
    m = _URL_PORT.search(url)
    if not m:
        return None
    system = PORT_SYSTEM.get(m.group(1))
    if system is None:
        return None
    r = _URL_ROUTE.search(url)
    route = r.group(1) if r else "root"
    if route not in WORK_ROUTES:
        return None
    return (system, route)


def _slim(e: dict[str, Any], session: str, chunk: str, dataset: str) -> dict[str, Any]:
    ctx = e.get("context") or {}
    app = ctx.get("active_app") or {}
    tab = ctx.get("active_browser_tab") or {}
    txt = ctx.get("extracted_text") or {}
    cor = e.get("correlation") or {}
    p = e.get("payload") or {}
    et = e.get("event_type")

    rec: dict[str, Any] = {
        "ds": dataset,
        "session": session,
        "chunk": chunk,
        "seq": cor.get("sequence_number"),
        "ts": e.get("timestamp_ms"),
        "iso": e.get("timestamp_iso"),
        "layer": e.get("layer"),
        "type": et,
        # context.active_app lags behind payload by one step on ~38% of A's
        # app_switch events, so it is kept but never trusted on its own.
        "ctx_app": app.get("app_name"),
        "window": app.get("window_title"),
        "tab_url": tab.get("url"),
        "text": (txt.get("text") if isinstance(txt, dict) else None),
        "machine": (e.get("source") or {}).get("machine_id"),
    }

    # Event-type specific projection: only what the segmenter or the report uses.
    if et == "app_switch":
        rec["new_app"] = (p.get("new_app") or {}).get("app_name")
        rec["prev_app"] = (p.get("previous_app") or {}).get("app_name")
    elif et == "browser_navigation":
        rec["nav_url"] = p.get("url")
        rec["nav_prev_url"] = p.get("previous_url")
        rec["nav_type"] = p.get("navigation_type")
    elif et == "browser_click":
        el = p.get("element") or {}
        rec["nav_url"] = p.get("url")
        rec["selector"] = el.get("css_selector")
        rec["tag"] = el.get("tag")
    elif et == "browser_form_input":
        f = p.get("field") or {}
        rec["nav_url"] = p.get("url")
        rec["selector"] = f.get("css_selector") or (("#" + f["id"]) if f.get("id") else None)
        rec["input_method"] = p.get("input_method")
    elif et == "shortcut":
        rec["keys"] = p.get("keys")
        rec["action_hint"] = p.get("action_hint")
    elif et == "clipboard_change":
        rec["clip_len"] = p.get("text_length")
    elif et == "window_title_change":
        rec["new_title"] = p.get("new_title")
        rec["title_app"] = p.get("app_name")
    elif et == "keystroke":
        rec["key"] = p.get("key")
    elif et == "screenshot_smart":
        rec["shot"] = ((p.get("file_reference") or {}).get("filename"))
    return rec


def build_cache(dataset: str, force: bool = False) -> str:
    """Project one dataset into build/events_<ds>.jsonl.  Returns the path."""
    os.makedirs(BUILD, exist_ok=True)
    out = os.path.join(BUILD, f"events_{dataset}.jsonl")
    if os.path.exists(out) and not force:
        return out
    root = DATASETS[dataset]
    n = 0
    with open(out, "w", encoding="utf-8") as fh:
        for session in sorted(os.listdir(root)):
            sdir = os.path.join(root, session)
            if not os.path.isdir(sdir):
                continue
            for chunk in sorted(os.listdir(sdir)):
                path = os.path.join(sdir, chunk, "events.jsonl")
                if not os.path.exists(path):
                    continue
                for line in open(path, encoding="utf-8"):
                    e = json.loads(line)
                    fh.write(json.dumps(_slim(e, session, chunk, dataset), ensure_ascii=False) + "\n")
                    n += 1
    print(f"[cache] {dataset}: {n} events -> {out}")
    return out


def load_sessions(dataset: str) -> dict[str, list[dict[str, Any]]]:
    """session_id -> events sorted by timestamp.

    File order follows `sequence_number`, which is NOT timestamp order: dataset A
    has 15,231 backward jumps (median 120 ms) where an L1 screenshot or a
    mouse_click is emitted out of order.  Sorting by (ts, seq) is required
    before any interval reasoning.
    """
    path = build_cache(dataset)
    out: dict[str, list[dict[str, Any]]] = {}
    for line in open(path, encoding="utf-8"):
        e = json.loads(line)
        out.setdefault(e["session"], []).append(e)
    for s in out:
        out[s].sort(key=lambda e: (e["ts"], e["seq"] if e["seq"] is not None else 0))
    return out


def iso_utc(ts_ms: int) -> str:
    """Epoch ms -> `2026-07-01T18:32:32Z` (second precision, as in the brief)."""
    import datetime as _dt
    return (_dt.datetime.fromtimestamp(ts_ms / 1000, _dt.timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ"))


def iter_jsonl(path: str) -> Iterator[dict[str, Any]]:
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line:
            yield json.loads(line)
