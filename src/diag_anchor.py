"""Where do case anchors sit inside a GT execution?  Drives boundary placement."""
import collections, statistics
from common import load_sessions
from features import resolve_contexts, case_anchor, enrich_side_apps
from groundtruth import load_gt

ev = load_sessions("A"); gt = load_gt()
for s in ev:
    resolve_contexts(ev[s]); enrich_side_apps(ev[s])

open_off, commit_off, commit_to_end = [], [], []
anchorless = collections.Counter()
gap_commit_to_next_open, gap_boundary_in_window = [], []
prev_commit = {}
for s, execs in gt.items():
    evs = ev[s]
    anchors = [(e["ts"], case_anchor(e)) for e in evs if case_anchor(e)]
    for x in execs:
        inside = [(t, a) for t, a in anchors if x.start <= t <= x.end]
        o = [t for t, a in inside if a[0] == "open"]
        c = [t for t, a in inside if a[0] == "commit"]
        if not o and not c:
            anchorless[x.code] += 1
            continue
        if o:
            open_off.append((o[0] - x.start) / 1000)
        if c:
            commit_off.append((c[-1] - x.start) / 1000)
            commit_to_end.append((x.end - c[-1]) / 1000)
    # boundary position between consecutive executions
    for a, b in zip(execs, execs[1:]):
        ca = [t for t, an in anchors if a.start <= t <= a.end and an[0] == "commit"]
        ob = [t for t, an in anchors if b.start <= t <= b.end and an[0] == "open"]
        if ca and ob and ob[0] > ca[-1]:
            span = ob[0] - ca[-1]
            gap_commit_to_next_open.append(span / 1000)
            gap_boundary_in_window.append((b.start - ca[-1]) / span)

def q(v, p): return sorted(v)[int(p * (len(v) - 1))]
print(f"row-open offset from exec start (s): n={len(open_off)} median={statistics.median(open_off):.2f} "
      f"p10={q(open_off,.1):.2f} p90={q(open_off,.9):.2f}")
print(f"last commit offset from exec start (s): median={statistics.median(commit_off):.2f} "
      f"p90={q(commit_off,.9):.2f}")
print(f"exec end - last commit (s): median={statistics.median(commit_to_end):.2f} "
      f"p10={q(commit_to_end,.1):.2f} p90={q(commit_to_end,.9):.2f}")
print(f"\ncommit_i -> open_(i+1) span (s): n={len(gap_commit_to_next_open)} "
      f"median={statistics.median(gap_commit_to_next_open):.2f} p90={q(gap_commit_to_next_open,.9):.2f}")
print(f"GT boundary position inside that span (0=at commit, 1=at next open): "
      f"median={statistics.median(gap_boundary_in_window):.3f} "
      f"p10={q(gap_boundary_in_window,.1):.3f} p90={q(gap_boundary_in_window,.9):.3f}")
print(f"\nexecutions with no anchor at all: {sum(anchorless.values())} "
      f"of {sum(len(v) for v in gt.values())}  by code: {dict(anchorless.most_common())}")

# why are they anchorless?  extension state around them
import json
ext = collections.Counter()
for s, execs in gt.items():
    evs = ev[s]
    anchors = {e["ts"] for e in evs if case_anchor(e)}
    for x in execs:
        if any(x.start <= t <= x.end for t in anchors):
            continue
        has_l3 = any(x.start <= e["ts"] <= x.end and e["layer"] == "L3" for e in evs)
        ext["has_L3" if has_l3 else "no_L3_at_all"] += 1
print("anchorless executions - is any L3 event present?", dict(ext))
