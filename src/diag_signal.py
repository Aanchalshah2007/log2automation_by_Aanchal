"""Diagnostic: how much of the segmentation problem does portal context solve?

Run before committing to a method.  Measures, on dataset A only:
  * purity  -- can (system, route) identify the GT process code?
  * how often the context is actually observed vs carried forward
  * how well context-change points line up with GT boundaries
"""
import collections
import statistics
import sys

from common import load_sessions
from features import resolve_contexts, case_anchor, enrich_side_apps
from groundtruth import load_gt


def main() -> None:
    ev = load_sessions("A")
    gt = load_gt()
    for s in ev:
        resolve_contexts(ev[s])
        enrich_side_apps(ev[s])

    # ---- 1. context purity vs GT process code -----------------------------
    ctx_by_code = collections.defaultdict(collections.Counter)
    code_by_ctx = collections.defaultdict(collections.Counter)
    observed = carried = none_ctx = 0
    for s, execs in gt.items():
        evs = ev[s]
        i = 0
        for x in execs:
            while i < len(evs) and evs[i]["ts"] < x.start:
                i += 1
            j = i
            while j < len(evs) and evs[j]["ts"] <= x.end:
                e = evs[j]
                if e["ctx"]:
                    ctx_by_code[x.code][e["ctx"]] += 1
                    code_by_ctx[e["ctx"]][x.code] += 1
                    (observed := observed) # noqa
                j += 1
    for s in ev:
        for e in ev[s]:
            if e["ctx"] is None:
                none_ctx += 1
            elif e["ctx_observed"]:
                observed += 1
            else:
                carried += 1
    tot = observed + carried + none_ctx
    print(f"context resolution: observed={observed} ({100*observed/tot:.1f}%) "
          f"carried_forward={carried} ({100*carried/tot:.1f}%) "
          f"unresolved={none_ctx} ({100*none_ctx/tot:.1f}%)")

    print("\nGT code -> dominant portal context (share of that code's events):")
    ok = 0
    for code in sorted(ctx_by_code):
        c = ctx_by_code[code]
        top, n = c.most_common(1)[0]
        share = n / sum(c.values())
        ok += share
        print(f"  {code}  {top[0]:3s}/{top[1]:20s} {100*share:5.1f}%   "
              f"(runner-up {c.most_common(2)[-1][0] if len(c)>1 else '-'})")
    print(f"  mean dominant-context share = {100*ok/len(ctx_by_code):.1f}%")

    print("\nportal context -> dominant GT code (is the mapping 1:1?):")
    for ctx in sorted(code_by_ctx):
        c = code_by_ctx[ctx]
        top, n = c.most_common(1)[0]
        print(f"  {ctx[0]:3s}/{ctx[1]:20s} -> {top}  {100*n/sum(c.values()):5.1f}%  "
              f"({len(c)} codes seen)")

    # ---- 2. case anchors ---------------------------------------------------
    per_exec_open = []
    per_exec_commit = []
    for s, execs in gt.items():
        evs = ev[s]
        for x in execs:
            o = c = 0
            for e in evs:
                if not (x.start <= e["ts"] <= x.end):
                    continue
                a = case_anchor(e)
                if a and a[0] == "open":
                    o += 1
                elif a and a[0] == "commit":
                    c += 1
            per_exec_open.append(o)
            per_exec_commit.append(c)
    print(f"\ncase anchors per GT execution ({len(per_exec_open)} executions):")
    print(f"  row-open   : {dict(collections.Counter(per_exec_open).most_common())}")
    print(f"  commit-btn : {dict(collections.Counter(per_exec_commit).most_common())}")
    print(f"  executions with >=1 anchor of either kind: "
          f"{100*sum(1 for o,c in zip(per_exec_open,per_exec_commit) if o or c)/len(per_exec_open):.1f}%")

    # ---- 3. do context changes line up with GT boundaries? ----------------
    tol = 3000
    hits = misses = 0
    dists = []
    for s, execs in gt.items():
        evs = ev[s]
        bounds = sorted({x.start for x in execs} | {x.end for x in execs})
        changes = [e["ts"] for a, e in zip(evs, evs[1:]) if a["ctx"] != e["ctx"] and e["ctx"]]
        for b in bounds:
            if not changes:
                misses += 1
                continue
            d = min(abs(b - c) for c in changes)
            dists.append(d / 1000)
            if d <= tol:
                hits += 1
            else:
                misses += 1
    print(f"\nGT boundaries within 3s of a portal-context change: "
          f"{hits}/{hits+misses} ({100*hits/(hits+misses):.1f}%)")
    print(f"  distance to nearest context change (s): median={statistics.median(dists):.2f} "
          f"p75={sorted(dists)[int(.75*len(dists))]:.2f} p90={sorted(dists)[int(.9*len(dists))]:.2f}")


if __name__ == "__main__":
    main()
