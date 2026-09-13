"""Who owns the dead time between two GT executions?"""
import collections, statistics
from common import load_sessions
from groundtruth import load_gt
from features import resolve_contexts, enrich_side_apps

ev = load_sessions("A"); gt = load_gt()
for s in ev: resolve_contexts(ev[s]); enrich_side_apps(ev[s])

gaps = []
for s, T in gt.items():
    for a, b in zip(T, T[1:]):
        gaps.append((b.start - a.end) / 1000)
print("gap start_{i+1} - end_i (s):",
      dict(collections.Counter('exactly0' if abs(g) < .05 else '<1' if g < 1 else '1-5' if g < 5
                               else '5-15' if g < 15 else '15-40' if g < 40 else '40-90' if g < 90
                               else '>90' for g in gaps).most_common()))
print(f"  median={statistics.median(gaps):.3f}  mean={statistics.mean(gaps):.1f}  "
      f"total gap time={sum(g for g in gaps if g>0)/60:.0f} min")

# what runs during the big gaps?
big = collections.Counter(); small = collections.Counter()
for s, T in gt.items():
    evs = ev[s]
    for a, b in zip(T, T[1:]):
        g = b.start - a.end
        if g <= 1000: continue
        win = [e for e in evs if a.end <= e["ts"] <= b.start]
        bucket = big if g > 15000 else small
        for x, y in zip(win, win[1:]):
            bucket[x.get("app")] += min(y["ts"] - x["ts"], 30000) / 1000
print("\napps during gaps >15 s (dwell s):", [(k, round(v)) for k, v in big.most_common(8)])
print("apps during gaps 1-15 s (dwell s):", [(k, round(v)) for k, v in small.most_common(8)])

# does the gap coincide with leaving the portal contexts entirely?
off = on = 0
for s, T in gt.items():
    evs = ev[s]
    for a, b in zip(T, T[1:]):
        if b.start - a.end <= 15000: continue
        win = [e for e in evs if a.end <= e["ts"] <= b.start]
        frac_nonportal = sum(1 for e in win if e.get("station") not in ("portal", None)) / max(len(win), 1)
        if frac_nonportal > 0.5: off += 1
        else: on += 1
print(f"\ngaps >15 s: mostly-outside-browser={off}  mostly-in-browser={on}")

# and INSIDE long executions?
inside = collections.Counter()
for s, T in gt.items():
    evs = ev[s]
    for t in T:
        if t.end - t.start < 90000: continue
        win = [e for e in evs if t.start <= e["ts"] <= t.end]
        for x, y in zip(win, win[1:]):
            if y["ts"] - x["ts"] > 15000:
                inside[x.get("app")] += (y["ts"] - x["ts"]) / 1000
print("apps holding >15 s quiet stretches INSIDE long executions:",
      [(k, round(v)) for k, v in inside.most_common(8)])
