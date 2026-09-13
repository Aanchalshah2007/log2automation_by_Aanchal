"""Parameter sweep with a held-out split.

Only four constants are fitted, and each has a physical meaning.  Sessions are
split deterministically 2:1 into dev / holdout so we can see whether the fitted
values are picking up something real or just memorising dataset A.
"""
import itertools, json, sys
import segmenter
from common import load_sessions
from groundtruth import load_gt
import evaluate

ev = load_sessions("A"); gt = load_gt()
sessions = sorted(gt)
dev = [s for i, s in enumerate(sessions) if i % 3 != 2]
hold = [s for i, s in enumerate(sessions) if i % 3 == 2]
label_of = lambda p: f"{p.ctx[0]}/{p.ctx[1]}"


def score(subset, fallback, **kw):
    old = {k: getattr(segmenter, k) for k in kw}
    for k, v in kw.items():
        setattr(segmenter, k, v)
    sub = {s: ev[s] for s in subset}
    pred = segmenter.segment_dataset(sub, use_fallback=fallback)
    g = {s: gt[s] for s in subset}
    b = evaluate.boundary_scores(pred, g, tols=(2000,))[2000]
    sc = evaluate.segment_scores(pred, g)
    cv = evaluate.coverage(pred, g, sub)
    lb = evaluate.label_consistency(sc["matched_pairs"], pred, label_of)
    for k, v in old.items():
        setattr(segmenter, k, v)
    return {"bF1": b["f1"], "bP": b["precision"], "bR": b["recall"],
            "iou": sc["mean_iou"], "iou50": sc["matched_iou50"],
            "ratio": sc["ratio"], "cov": cv["gt_time_recovered"],
            "prec_t": cv["pred_time_inside_gt"], "ari": lb.get("ari", 0)}


def show(tag, r):
    print(f"  {tag:44s} bF1={r['bF1']:.3f} IoU={r['iou']:.3f} @50={r['iou50']:.3f} "
          f"ratio={r['ratio']:.3f} cov={r['cov']:.3f} precT={r['prec_t']:.3f} ARI={r['ari']:.3f}")


if __name__ == "__main__":
    print("== LEAD_FRAC / TAIL_FRAC (dev) ==")
    best = None
    for lead in (0.15, 0.19, 0.223, 0.26, 0.30):
        for tail in (0.10, 0.156, 0.22):
            r = score(dev, False, LEAD_FRAC=lead, TAIL_FRAC=tail)
            show(f"lead={lead} tail={tail}", r)
            k = r["bF1"] + r["iou"] + r["ari"]
            if best is None or k > best[0]:
                best = (k, lead, tail)
    _, LEAD, TAIL = best
    print(f"  -> chose lead={LEAD} tail={TAIL}")

    print("\n== ABSORB_MULT (dev) ==")
    bestA = None
    for a in (3.0, 4.0, 6.0, 8.0, 10.0, 14.0, 1e9):
        r = score(dev, False, LEAD_FRAC=LEAD, TAIL_FRAC=TAIL, ABSORB_MULT=a)
        show(f"absorb={a}", r)
        k = r["bF1"] + r["iou"] + r["ari"]
        if bestA is None or k > bestA[0]:
            bestA = (k, a)
    ABS = bestA[1]
    print(f"  -> chose absorb={ABS}")

    print("\n== REOPEN_MERGE_MS (dev) ==")
    bestR = None
    for m in (0, 1500, 2500, 4000, 8000):
        r = score(dev, False, LEAD_FRAC=LEAD, TAIL_FRAC=TAIL, ABSORB_MULT=ABS, REOPEN_MERGE_MS=m)
        show(f"reopen={m}", r)
        k = r["bF1"] + r["iou"] + r["ari"]
        if bestR is None or k > bestR[0]:
            bestR = (k, m)
    RE = bestR[1]
    print(f"  -> chose reopen={RE}")

    print("\n== excursion fallback on/off ==")
    for fb in (False, True):
        show(f"dev  fallback={fb}", score(dev, fb, LEAD_FRAC=LEAD, TAIL_FRAC=TAIL,
                                          ABSORB_MULT=ABS, REOPEN_MERGE_MS=RE))
    print()
    for fb in (False, True):
        show(f"HOLD fallback={fb}", score(hold, fb, LEAD_FRAC=LEAD, TAIL_FRAC=TAIL,
                                           ABSORB_MULT=ABS, REOPEN_MERGE_MS=RE))
    json.dump({"LEAD_FRAC": LEAD, "TAIL_FRAC": TAIL, "ABSORB_MULT": ABS,
               "REOPEN_MERGE_MS": RE}, open("../build/tuned.json", "w"), indent=1)
    print(f"\nwrote build/tuned.json  (dev={len(dev)} sessions, holdout={len(hold)})")
