"""Break the residual error down into named failure modes."""
import collections, statistics, sys
from common import load_sessions
from groundtruth import load_gt
from segmenter import segment_dataset
from features import case_anchor
from evaluate import _iou

use_fb = "--fallback" in sys.argv
ev = load_sessions("A"); gt = load_gt()
pred = segment_dataset(ev, use_fallback=use_fb)

buckets = collections.Counter()
examples = collections.defaultdict(list)
iou_by_code = collections.defaultdict(list)
dur_lost = collections.Counter()

for s, T in gt.items():
    P = sorted(pred.get(s, []), key=lambda x: x.start)
    evs = ev[s]
    anchors = [(e["ts"], case_anchor(e)) for e in evs if case_anchor(e)]
    for t in T:
        best, bp = 0.0, None
        for p in P:
            v = _iou((p.start, p.end), (t.start, t.end))
            if v > best:
                best, bp = v, p
        iou_by_code[t.code].append(best)
        has_anchor = any(t.start <= ts <= t.end for ts, _ in anchors)
        n_over = sum(1 for p in P if _iou((p.start, p.end), (t.start, t.end)) > 0.15)
        dur = (t.end - t.start) / 1000
        if best == 0.0:
            b = "0_missed_entirely" + ("_no_anchor" if not has_anchor else "_has_anchor")
        elif best < 0.25:
            b = "1_barely_overlapping"
        elif best < 0.5:
            b = "2_partial" + ("_no_anchor" if not has_anchor else "")
        elif n_over > 1:
            b = "3_over_segmented"
        else:
            b = "4_good"
        buckets[b] += 1
        dur_lost[b] += dur
        if len(examples[b]) < 3:
            examples[b].append((s, t.code, round(dur, 1), round(best, 2), has_anchor,
                                round((t.end - t.start) / 1000, 1)))

n = sum(buckets.values())
print(f"{'bucket':34s} {'n':>5s} {'%':>6s} {'GT minutes':>11s}")
for b in sorted(buckets):
    print(f"{b:34s} {buckets[b]:5d} {100*buckets[b]/n:6.1f} {dur_lost[b]/60:11.1f}")
print()
for b in sorted(examples):
    print(f"{b}: {examples[b]}")

print("\nmean IoU by GT process code:")
for c in sorted(iou_by_code):
    v = iou_by_code[c]
    print(f"  {c}  n={len(v):4d} mean={statistics.mean(v):.3f} median={statistics.median(v):.3f} "
          f"frac<0.5={sum(1 for x in v if x<0.5)/len(v):.2f}")

# long executions -- splits / suspensions
longs = [(s, t) for s, T in gt.items() for t in T if t.end - t.start > 120_000]
print(f"\nGT executions longer than 120 s: {len(longs)}")
iou_long = []
for s, t in longs:
    best = max((_iou((p.start, p.end), (t.start, t.end)) for p in pred.get(s, [])), default=0)
    iou_long.append(best)
if iou_long:
    print(f"  their IoU: mean={statistics.mean(iou_long):.3f} median={statistics.median(iou_long):.3f}")
