"""How much of dataset B is reachable by DOM anchors at all?"""
import collections, statistics
from common import load_sessions
from features import resolve_contexts, enrich_side_apps, case_anchor

ev = load_sessions("B")
for s in ev: resolve_contexts(ev[s]); enrich_side_apps(ev[s])
tot_ev = sum(len(v) for v in ev.values())
res = sum(1 for v in ev.values() for e in v if e["ctx"])
obs = sum(1 for v in ev.values() for e in v if e["ctx_observed"])
print(f"events={tot_ev} ctx resolved={res} ({100*res/tot_ev:.1f}%) of which observed={obs}")
a = collections.Counter()
for v in ev.values():
    for e in v:
        k = case_anchor(e)
        if k: a[k[0]] += 1
print("anchors:", dict(a))
# L3 gaps
for s, v in ev.items():
    l3 = sum(1 for e in v if e["layer"] == "L3")
    op = sum(1 for e in v if (case_anchor(e) or ("",))[0] == "open")
    cm = sum(1 for e in v if (case_anchor(e) or ("",))[0] == "commit")
    span = (v[-1]["ts"] - v[0]["ts"]) / 60000
    print(f"  {s:44s} ev={len(v):5d} L3={l3:5d} open={op:4d} commit={cm:4d} min={span:5.1f}")
