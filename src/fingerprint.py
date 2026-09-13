"""Behavioural fingerprint of a segment, used only for label consistency checks.

These features are deliberately NOT used to draw boundaries -- they are how we
test, after the fact, two questions the brief asks:

  * do two segments carrying the same label really do the same work?
  * do two different labels describe the same work, and should be merged?
"""
from __future__ import annotations

import collections
import math
from typing import Any


def fingerprint(events: list[dict[str, Any]], seg) -> dict[str, float]:
    win = [e for e in events if seg.start <= e["ts"] <= seg.end]
    n = max(len(win), 1)
    f: dict[str, float] = collections.defaultdict(float)
    dwell: dict[str, float] = collections.defaultdict(float)
    for a, b in zip(win, win[1:]):
        dwell[a.get("app") or "?"] += min(b["ts"] - a["ts"], 30_000) / 1000
    total = sum(dwell.values()) or 1.0
    for app, v in dwell.items():
        f[f"app:{app}"] = v / total
    for e in win:
        t = e["type"]
        f[f"ev:{t}"] += 1 / n
        if t == "shortcut" and e.get("keys"):
            f[f"key:{e['keys']}"] += 1 / n
        if t == "window_title_change" and e.get("new_title"):
            doc = e["new_title"].split("  -  ")[0].split(" [")[0].split(" - ")[0].lstrip("*")
            f[f"doc:{doc}"] += 1
        if t == "browser_click" and (e.get("selector") or "").startswith("#btn-"):
            f[f"btn:{e['selector']}"] += 1
    f["_dur_s"] = (seg.end - seg.start) / 1000
    f["_n_events"] = len(win)
    return dict(f)


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    keys = {k for k in a if not k.startswith("_")} | {k for k in b if not k.startswith("_")}
    num = sum(a.get(k, 0.0) * b.get(k, 0.0) for k in keys)
    da = math.sqrt(sum(a.get(k, 0.0) ** 2 for k in keys))
    db = math.sqrt(sum(b.get(k, 0.0) ** 2 for k in keys))
    return num / (da * db) if da and db else 0.0


def centroid(fps: list[dict[str, float]]) -> dict[str, float]:
    out: dict[str, float] = collections.defaultdict(float)
    for f in fps:
        for k, v in f.items():
            if not k.startswith("_"):
                out[k] += v / len(fps)
    return dict(out)


def two_means(fps: list[dict[str, float]], iters: int = 25):
    """Cheap 2-means on cosine similarity; returns (labels, separation).

    `separation` is (mean within-cluster similarity) - (between-centroid
    similarity).  Near zero means the two clusters are not really distinct.
    """
    if len(fps) < 8:
        return [0] * len(fps), 0.0
    order = sorted(range(len(fps)), key=lambda i: fps[i].get("_dur_s", 0))
    c = [centroid([fps[i] for i in order[: len(order) // 3]]),
         centroid([fps[i] for i in order[-len(order) // 3:]])]
    lab = [0] * len(fps)
    for _ in range(iters):
        new = [0 if cosine(f, c[0]) >= cosine(f, c[1]) else 1 for f in fps]
        if new == lab:
            break
        lab = new
        for k in (0, 1):
            mem = [f for f, l in zip(fps, lab) if l == k]
            if mem:
                c[k] = centroid(mem)
    within = []
    for f, l in zip(fps, lab):
        within.append(cosine(f, c[l]))
    sep = (sum(within) / len(within)) - cosine(c[0], c[1])
    sizes = (lab.count(0), lab.count(1))
    return lab, (sep if min(sizes) >= max(3, 0.15 * len(fps)) else 0.0)
