"""Learn `screen name -> route` from the dataset's own screen text.

Why this exists
---------------
When the browser extension is not connected, the log loses BOTH `browser_*`
events and `context.active_browser_tab`, so the URL -- the primary context
channel -- disappears completely.  That is not a rare corner: 7 of dataset A's
63 sessions and 1 of dataset B's 15 sessions have zero L3 events, and they
segment to nothing without a fallback.

What survives is
  * the window title, which names the business system
    (`HR人事給与システム` / `財務会計システム` / `受発注在庫管理システム`), and
  * `context.extracted_text`, which on ~4.5% of events contains the page
    breadcrumb `ダッシュボード / <screen name>`.

Sessions that DO have the extension show the breadcrumb and the URL in the same
OCR blob, so the mapping from a Japanese screen name to a route can be *learned
from the data itself*, per dataset, and then applied to the sessions that lost
the URL.  No hand-written translation table, and it works unchanged on dataset
B, whose screen names are different from A's.
"""
from __future__ import annotations

import collections
import re
from typing import Any

from common import portal_context

SYSTEM_BY_WINDOW = {
    "HR人事給与システム": "hr",
    "財務会計システム": "fin",
    "受発注在庫管理システム": "ops",
}

_OCR_URL = re.compile(r"127\.0\.0\.1:(51\d\d)/#/([a-z-]+)")
_BREADCRUMB = re.compile(r"ダッシュボード\s*/\s*([^\n/]{2,24})")
# The left-hand nav renders each entry as "<label>\n<url>", which pins a label
# to a route directly and is by far the strongest evidence when it is present.
_NAV_PAIR = re.compile(r"([^\n]{2,24})\n\s*http://127\.0\.0\.1:(51\d\d)/#/([a-z-]+)")


def system_from_window(title: str | None) -> str | None:
    if not title:
        return None
    for k, v in SYSTEM_BY_WINDOW.items():
        if k in title:
            return v
    return None


def breadcrumb(text: str | None) -> str | None:
    if not text:
        return None
    m = _BREADCRUMB.search(text)
    return m.group(1).strip() if m else None


def learn(sessions: dict[str, list[dict[str, Any]]], port_system) -> dict[tuple[str, str], str]:
    """(system, japanese screen name) -> route.

    Two independent sources of evidence are pooled:
      1. nav entries `label\\nhttp://.../#/route`  (weight 3 -- unambiguous)
      2. a breadcrumb co-occurring with the page URL in the same OCR blob
         (weight 1 -- the blob may also contain another tab's chrome)
    """
    votes: dict[tuple[str, str], collections.Counter] = collections.defaultdict(collections.Counter)
    for evs in sessions.values():
        for e in evs:
            t = e.get("text")
            if not t:
                continue
            for label, port, route in _NAV_PAIR.findall(t):
                sysn = port_system.get(port)
                label = label.strip().rstrip("0123456789 ").strip()
                if sysn and label and label not in SYSTEM_BY_WINDOW:
                    votes[(sysn, label)][route] += 3
            bc = breadcrumb(t)
            if bc:
                # Vote with the tab URL recorded on the *event*, not with a URL
                # parsed out of the OCR blob: the blob also renders the whole
                # left-hand nav, so several routes appear in it and the modal
                # one is not necessarily the page being viewed.
                ctx = portal_context(e.get("nav_url")) or portal_context(e.get("tab_url"))
                if ctx:
                    votes[(ctx[0], bc)][ctx[1]] += 1
    # A screen name belongs to exactly one screen of one system -- verified in
    # both datasets from the rendered nav lists.  Multi-tab OCR blobs (6 of
    # dataset B's 15 sessions work with 2-3 tabs open) leak another system's
    # page text into the current tab's event, so keep, for each name, only the
    # system that has the most evidence for it.
    best_system: dict[str, tuple[int, str]] = {}
    for (sysn, name), c in votes.items():
        tot = sum(c.values())
        if name not in best_system or tot > best_system[name][0]:
            best_system[name] = (tot, sysn)

    out: dict[tuple[str, str], str] = {}
    for (sysn, name), c in votes.items():
        if name == "ダッシュボード" or best_system[name][1] != sysn:
            continue
        route, n = c.most_common(1)[0]
        if n >= 3 and n / sum(c.values()) >= 0.6:
            out[(sysn, name)] = route
    return out


def describe(mapping: dict[tuple[str, str], str]) -> str:
    by_sys: dict[str, list[tuple[str, str]]] = collections.defaultdict(list)
    for (sysn, name), route in mapping.items():
        by_sys[sysn].append((route, name))
    lines = []
    for sysn in ("hr", "fin", "ops"):
        for route, name in sorted(by_sys.get(sysn, [])):
            lines.append(f"  {sysn:3s} {route:20s} {name}")
    return "\n".join(lines)
