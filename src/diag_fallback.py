"""Judge the L3-less fallback on exactly the executions it exists for."""
import collections, statistics, sys
from common import load_sessions
from groundtruth import load_gt
from features import case_anchor
from evaluate import _iou
import segmenter

ev = load_sessions("A"); gt = load_gt()

# the subset the fallback is supposed to rescue
target = {}
for s, T in gt.items():
    anchors = {e["ts"] for e in ev[s] if case_anchor(e)}
    target[s] = [t for t in T if not any(t.start <= a <= t.end for a in anchors)]
n_t = sum(len(v) for v in target.values())
print(f"anchorless GT executions: {n_t}")

def evaluate_variant(**kw):
    old = {k: getattr(segmenter, k, None) for k in kw}
    for k, v in kw.items(): setattr(segmenter, k, v)
    pred = segmenter.segment_dataset(ev, use_fallback=True)
    for k, v in old.items():
        if v is not None: setattr(segmenter, k, v)
    ious, n_fb = [], 0
    for s, T in target.items():
        P = [p for p in pred[s] if p.kind == "excursion"]
        n_fb += len(P)
        for t in T:
            ious.append(max((_iou((p.start, p.end), (t.start, t.end)) for p in pred[s]), default=0.0))
    hit = sum(1 for v in ious if v >= 0.25)
    return n_fb, hit / len(ious), statistics.mean(ious)

nfb, hit, mi = evaluate_variant()
print(f"current fallback: emitted {nfb} excursion segments; "
      f"{100*hit:.1f}% of anchorless execs now matched at IoU>=0.25 (mean IoU {mi:.3f})")

# sessions with NO L3 at all - the dataset-B scenario
no_l3 = [s for s in ev if not any(e["layer"] == "L3" for e in ev[s])]
print(f"\ndataset A sessions with zero L3 events: {len(no_l3)}")
part = [s for s in ev if sum(1 for e in ev[s] if e['layer']=='L3') < 20]
print(f"dataset A sessions with <20 L3 events: {len(part)} -> {part[:5]}")
# simulate: strip L3 from a few sessions and see what the fallback alone recovers
import copy
sample = sorted(gt)[:12]
stripped = {s: [e for e in ev[s] if e["layer"] != "L3"] for s in sample}
pred = segmenter.segment_dataset(stripped, use_fallback=True)
g = {s: gt[s] for s in sample}
import evaluate as EV
lbl = lambda p: f"{p.ctx[0]}/{p.ctx[1]}"
print("\n--- simulated 'extension never connected' on 12 sessions (L3 removed) ---")
EV.report(pred, g, stripped, lbl)
print("\n--- same 12 sessions, L3 intact ---")
full = {s: ev[s] for s in sample}
EV.report(segmenter.segment_dataset(full, use_fallback=True), g, full, lbl)
