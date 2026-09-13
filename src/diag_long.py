"""What is inside the long GT executions the segmenter under-covers?"""
import collections, statistics
from common import load_sessions
from groundtruth import load_gt
from segmenter import segment_dataset
from features import case_anchor
from evaluate import _iou

ev = load_sessions("A"); gt = load_gt()
pred = segment_dataset(ev, use_fallback=False)

rows = []
for s, T in gt.items():
    P = pred.get(s, [])
    evs = ev[s]
    for t in T:
        d = (t.end - t.start) / 1000
        if d <= 60:
            continue
        best = max((_iou((p.start, p.end), (t.start, t.end)) for p in P), default=0.0)
        win = [e for e in evs if t.start <= e["ts"] <= t.end]
        apps = collections.Counter()
        for a, b in zip(win, win[1:]):
            apps[a.get("app")] += min(b["ts"] - a["ts"], 30000) / 1000
        anch = [case_anchor(e) for e in win if case_anchor(e)]
        # largest single quiet stretch
        gaps = [(b["ts"] - a["ts"]) / 1000 for a, b in zip(win, win[1:])]
        rows.append((d, best, t.code, len([x for x in anch if x[0] == 'open']),
                     len([x for x in anch if x[0] == 'commit']),
                     max(gaps) if gaps else 0, apps.most_common(3), s))
rows.sort()
print(f"GT executions longer than 60 s: {len(rows)}  mean IoU={statistics.mean(r[1] for r in rows):.3f}")
print(f"{'dur':>7} {'IoU':>5} {'cd':>3} {'op':>3} {'cm':>3} {'maxgap':>7}  top apps by dwell(s)")
for r in rows[::max(1, len(rows)//25)]:
    print(f"{r[0]:7.1f} {r[1]:5.2f} {r[2]:>3} {r[3]:3d} {r[4]:3d} {r[5]:7.1f}  "
          + ", ".join(f"{k}:{v:.0f}" for k, v in r[6]))
n_multi = sum(1 for r in rows if r[3] > 1)
print(f"\nlong execs containing >1 row-open: {n_multi} of {len(rows)}")
print(f"long execs containing 0 anchors  : {sum(1 for r in rows if r[3]==0 and r[4]==0)}")
tot = sum(r[0] for r in rows)
print(f"long execs account for {tot/60:.0f} GT minutes of {sum((t.end-t.start)/1000 for T in gt.values() for t in T)/60:.0f}")
