"""Event-level feature extraction.

Only two families of features survived the diagnostics in
reports/step1_segmentation_report.md:

  1. *portal context*  -- which business system + which work screen the browser
     is on.  This is what identifies the process.
  2. *case anchors*    -- the DOM interactions that open and commit a single
     case on that screen.  These are what separate consecutive executions of the
     same process.

Everything else (keystroke counts, mouse density, screenshots, window titles of
side applications) was measured and is reported as a secondary/diagnostic
feature only -- see `enrich_side_apps`.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

from common import portal_context
from screenmap import system_from_window, breadcrumb

# --- case anchors -----------------------------------------------------------
# Dataset A renders list rows with the case id baked into the element id:
#     #la-row-SUP-181750-001 > td:nth-of-type(4)
# Dataset B renders the same table positionally:
#     #la-table > tbody > tr:nth-of-type(4) > td:nth-of-type(4)
# Both are "the worker picked a case off the worklist".
ROW_A = re.compile(r"#([a-z]{2})-row-([A-Z]{2,4}-\d{4,6}-\d{3})")
ROW_B = re.compile(r"#([a-z]{2})-table\s*>\s*tbody\s*>\s*tr:nth-of-type\((\d+)\)")
# Commit buttons.  A uses semantic names (confirm/register/approve/complete/flag/
# query), B collapsed them all to `-ok`.
BTN = re.compile(r"#btn-([a-z]{2})-([a-z]+)")
NOTE = re.compile(r"#([a-z]{2})-note")

# Screen-module prefix (rt/pi/la/si/ob) -> route, so a DOM interaction can
# confirm the route even when the URL is stale.
MODULE_ROUTE = {
    "rt": "resident-tax", "pi": "payroll-items", "la": "leave-applications",
    "si": "social-insurance", "ob": "onboarding",
}

# Commit verbs seen in dataset A; `query`/`flag` are *outcomes*, not commits in
# a different process -- they still close a case.
COMMIT_VERBS = {"confirm", "register", "approve", "complete", "flag", "query", "ok"}


def resolve_contexts(events: list[dict[str, Any]],
                     screen_map: dict[tuple[str, str], str] | None = None) -> None:
    """Annotate every event in place with `ctx` = (system, route) or None.

    Three independent channels, in order of reliability:

      1. **URL** -- `payload.url` of the event itself (browser_navigation /
         browser_click / browser_form_input), then
         `context.active_browser_tab.url`.  Exact, but it exists only while the
         browser extension is connected.
      2. **DOM module prefix** -- a click on `#la-note` or `#btn-la-ok` names the
         screen module even when the URL field is missing.
      3. **window title + OCR breadcrumb** -- the window title names the business
         system and `ダッシュボード / <screen>` in `context.extracted_text` names
         the screen.  This is the only channel that survives when the extension
         is absent, which is the case for 7 of dataset A's 63 sessions and 1 of
         dataset B's 15.

    Whatever the channel, the resolved context is then carried forward: an
    execution spends most of its wall clock in Excel/Word/Notepad, where no URL
    is recorded, and those events belong to the screen the worker came from.
    """
    last: tuple[str, str] | None = None
    for e in events:
        ctx = portal_context(e.get("nav_url")) or portal_context(e.get("tab_url"))
        source = "url" if ctx else None

        if ctx is None:
            sel = e.get("selector")
            if sel and last is not None:
                m = ROW_A.search(sel) or ROW_B.search(sel) or BTN.search(sel) or NOTE.search(sel)
                if m:
                    route = MODULE_ROUTE.get(m.group(1))
                    if route:
                        ctx, source = (last[0], route), "dom"

        if ctx is None and screen_map is not None:
            sysn = system_from_window(e.get("window")) or system_from_window(e.get("new_title"))
            name = breadcrumb(e.get("text"))
            if name is not None:
                route = screen_map.get((sysn, name)) if sysn else None
                if route is None:
                    # the breadcrumb alone still pins the screen, because a
                    # screen name is unique across the three systems
                    hit = [(s2, r) for (s2, n2), r in screen_map.items() if n2 == name]
                    if len(hit) == 1:
                        sysn, route = hit[0]
                if sysn and route:
                    ctx, source = (sysn, route), "ocr"
            elif sysn is not None and last is not None and sysn != last[0]:
                # We know the worker moved to a different system but not to which
                # screen; drop the stale context rather than mis-attribute it.
                last = None

        e["ctx"] = ctx if ctx is not None else last
        e["ctx_source"] = source or ("carry" if e["ctx"] else None)
        e["ctx_observed"] = ctx is not None
        e["_sys_hint"] = system_from_window(e.get("window"))
        if ctx is not None:
            last = ctx

    _backfill(events)


def _backfill(events: list[dict[str, Any]]) -> None:
    """Fill leading `ctx=None` runs from the next observation.

    The forward pass can only start once the first context is seen.  In an
    extension-less session the first observation is an OCR breadcrumb, which may
    arrive a minute into the session -- yet the worker was already on that screen
    before the screenshot was taken.  So we also propagate backwards, but only
    across events whose window title still names the same business system, so we
    never carry a context over a system change.
    """
    nxt: tuple[str, str] | None = None
    nxt_sys: str | None = None
    for e in reversed(events):
        if e.get("ctx_observed"):
            nxt, nxt_sys = e["ctx"], e["ctx"][0]
            continue
        if e.get("ctx") is None and nxt is not None:
            hint = e.get("_sys_hint")
            if hint is None or hint == nxt_sys:
                e["ctx"] = nxt
                e["ctx_source"] = "backfill"


def case_anchor(e: dict[str, Any]) -> tuple[str, str] | None:
    """Classify a DOM event as a case anchor.

    Returns (kind, key) where kind is 'open' (a worklist row was picked) or
    'commit' (an action button was pressed), or None.
    """
    sel = e.get("selector")
    if not sel:
        return None
    if e.get("type") == "browser_click":
        m = ROW_A.search(sel)
        if m:
            return ("open", m.group(2))          # key = the real case id
        m = ROW_B.search(sel)
        if m:
            return ("open", f"row{m.group(2)}")  # key = row position only
        m = BTN.search(sel)
        if m and m.group(2) in COMMIT_VERBS:
            return ("commit", m.group(2))
    return None


# --- secondary / diagnostic features ---------------------------------------
SIDE_APPS = {"Microsoft Excel", "Microsoft Word", "Notepad", "Microsoft PowerPoint",
             "ms-teams", "olk", "Microsoft Outlook", "Windows Explorer",
             "WindowsTerminal", "OpenWith", "powershell", "Settings", "prl_cc"}


BROWSERS = {"Google Chrome", "Microsoft Edge"}


def enrich_side_apps(events: Iterable[dict[str, Any]]) -> None:
    """Annotate `app` = foreground application, and `station` = its role.

    `context.active_app` cannot be used for this: it is stale on 38% of dataset
    A's app_switch events (it still reports the app being switched *away* from),
    which mis-attributes Excel's Ctrl+F to Chrome.  The reliable source is the
    app_switch payload, so we run a small state machine over
    `payload.new_app` and carry it forward, seeding from context only until the
    first app_switch arrives.

    88.3% of dataset A's app_switch events are self-switches
    (new_app == previous_app); those are ignored as state transitions but still
    confirm the current app.
    """
    cur = None
    for e in events:
        if e.get("type") == "app_switch" and e.get("new_app"):
            cur = e["new_app"]
        elif cur is None:
            cur = e.get("ctx_app")
        e["app"] = cur
        e["station"] = ("portal" if cur in BROWSERS else
                        "sheet" if cur in ("Microsoft Excel",) else
                        "doc" if cur in ("Microsoft Word", "Microsoft PowerPoint") else
                        "editor" if cur in ("Notepad",) else
                        "other" if cur else None)


# Below this ratio of browser-exits per in-browser paste, the work is
# browser-resident and the case boundary is the click that follows the paste;
# above it the worker leaves the browser once per case and the boundary is the
# last click before that.  Dataset A's extension-less sessions measure 0.96-2.21
# and dataset B's measures 0.43, so 0.8 sits inside the observed gap -- but that
# gap is narrow and rests on 8 sessions.  See the report's assumptions section.
RESIDENT_RATIO = 0.8


def l2_case_anchors(events: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    """Pick the L2 anchor family that matches this session's own rhythm.

    Two workflow shapes appear in these logs and they leave different L2 traces:

    * *excursion-driven* (dataset A): the worker picks a row, leaves the browser
      for Excel/Word/Notepad, comes back and commits.  One browser exit per case,
      so the anchor is the last browser click before the exit.
    * *browser-resident* (dataset B): the worker picks a row, pastes into the
      note field and presses the action button without ever leaving the browser.
      Few exits, one paste per case, so the anchor is the click right after the
      paste.

    Taking the union of both families double-fires on excursion-driven sessions
    (58 of dataset A's 204 extension-less executions would get two anchors), so
    the family is chosen per session from the exit-to-paste ratio.
    """
    exits = pastes = 0
    prev = None
    for e in events:
        st = e.get("station")
        if st == "portal" and e.get("type") == "shortcut" and e.get("keys") == "Ctrl+V":
            pastes += 1
        if st is not None:
            if prev == "portal" and st != "portal":
                exits += 1
            prev = st
    if pastes and exits / pastes < RESIDENT_RATIO:
        return l2_paste_commit_anchors(events), "resident"
    return l2_open_anchors(events), "excursion"


def l2_paste_commit_anchors(events: list[dict[str, Any]],
                            window_ms: int = 3500) -> list[dict[str, Any]]:
    """Browser mouse_click shortly after an in-browser paste = the action button.

    This is the L2 shadow of `#btn-<module>-ok` for browser-resident work.
    """
    out: list[dict[str, Any]] = []
    last_paste: int | None = None
    for e in events:
        if e.get("station") != "portal":
            continue
        if e.get("type") == "shortcut" and e.get("keys") == "Ctrl+V":
            last_paste = e["ts"]
        elif (e.get("type") in ("mouse_click", "mouse_double_click")
              and last_paste is not None and 0 <= e["ts"] - last_paste <= window_ms):
            out.append(e)
            last_paste = None
    return out


def l2_open_anchors(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """L2-only shadow of the worklist row-click, for extension-less sessions.

    With no L3 layer there is no `browser_click`, but the click still shows up as
    a plain `mouse_click` whose foreground application is the browser.  A case
    starts when the worker picks a row and then leaves the browser to look
    something up, so the anchor is *the last browser mouse_click before the
    browser loses focus*.  Earlier clicks in the same browser visit belong to the
    previous case (pasting its note, pressing its action button).

    Measured on dataset A's extension-less sessions, this lands a median 4.5 s
    after the GT execution start -- the same offset as the real `browser_click`
    anchor -- so the same LEAD_FRAC applies.

    `enrich_side_apps` must have run first (it sets `station`).
    """
    out: list[dict[str, Any]] = []
    last_click: dict[str, Any] | None = None
    prev_station: str | None = None
    for e in events:
        st = e.get("station")
        if st == "portal":
            if e.get("type") in ("mouse_click", "mouse_double_click"):
                last_click = e
        elif st is not None and prev_station == "portal":
            if last_click is not None:
                out.append(last_click)
                last_click = None
        if st is not None:
            prev_station = st
    if last_click is not None:
        out.append(last_click)
    return out
