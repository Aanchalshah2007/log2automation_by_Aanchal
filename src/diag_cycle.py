"""Fallback signal: does 'return to the portal' repeat once per execution?"""
import collections, statistics
from common import load_sessions
from features import resolve_contexts, enrich_side_apps, case_anchor
from groundtruth import load_gt

ev = load_sessions("A"); gt = load_gt()
for s in ev:
    resolve_contexts(ev[s]); enrich_side_apps(ev[s])

def returns_to_portal(win):
    """count transitions (non-portal station) -> portal"""
    n, prev = 0, None
    for e in win:
        st = e.get("station")
        if st is None: continue
        if prev is not None and prev != "portal" and st == "portal":
            n += 1
        prev = st
    return n

def excursions(win):
    n, prev = 0, None
    for e in win:
        st = e.get("station")
        if st is None: continue
        if prev == "portal" and st != "portal":
            n += 1
        prev = st
    return n

allc, anchc = [], []
for s, execs in gt.items():
    evs = ev[s]
    a = {e["ts"] for e in evs if case_anchor(e)}
    for x in execs:
        win = [e for e in evs if x.start <= e["ts"] <= x.end]
        r, ex = returns_to_portal(win), excursions(win)
        has = any(x.start <= t <= x.end for t in a)
        (allc if has else anchc).append((r, ex))
for nm, v in [("with anchors", allc), ("ANCHORLESS", anchc)]:
    print(f"{nm}: n={len(v)}")
    print(f"   returns-to-portal  {dict(collections.Counter(r for r,_ in v).most_common(6))}")
    print(f"   portal-excursions  {dict(collections.Counter(x for _,x in v).most_common(6))}")
# app attribution sanity after fix
c = collections.Counter()
for s in ev:
    for e in ev[s]:
        if e["type"] == "shortcut" and e.get("keys") in ("Ctrl+F", "Ctrl+V"):
            c[(e["keys"], e.get("app"))] += 1
print("\nshortcut x foreground app after fix:", dict(c.most_common(10)))
