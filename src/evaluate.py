"""Validation of the segmentation against dataset A's ground truth.

Reported families:
  * boundary precision / recall / F1 at several tolerances
  * segment-level temporal IoU and matched-at-IoU>=0.5
  * over- / under-segmentation counts
  * time coverage in both directions
  * label consistency (purity, inverse purity, V-measure, ARI) -- our labels are
    our own invention, so what matters is whether they partition executions the
    same way the GT codes do, not what they are called.
"""
from __future__ import annotations

import collections
import math
import statistics
from typing import Any, Iterable

from segmenter import Segment
from groundtruth import Execution


# --------------------------------------------------------------------------- #
def _greedy_match(pred: list[int], true: list[int], tol: int) -> int:
    """Max 1-1 matches between two boundary sets within `tol` ms (greedy on distance)."""
    pairs = sorted(((abs(p - t), i, j) for i, p in enumerate(pred) for j, t in enumerate(true)
                    if abs(p - t) <= tol))
    up, ut = set(), set()
    n = 0
    for _, i, j in pairs:
        if i in up or j in ut:
            continue
        up.add(i); ut.add(j); n += 1
    return n


def _collapse(points: Iterable[int], eps: int = 250) -> list[int]:
    """Merge timestamps closer than `eps` into one transition point.

    94.8% of consecutive GT executions abut with a 2-3 ms gap: the generator
    writes `process_switched_out` and the next `process_started` microseconds
    apart.  Those are ONE transition, not two boundaries.  Without collapsing
    them the recall ceiling for any segmenter that emits a single boundary per
    handover would be ~0.56, which measures the file format rather than the
    method.
    """
    out: list[int] = []
    for t in sorted(points):
        if out and t - out[-1] <= eps:
            continue
        out.append(t)
    return out


def boundary_scores(pred: dict[str, list[Segment]], gt: dict[str, list[Execution]],
                    tols=(1000, 2000, 5000)) -> dict[int, dict[str, float]]:
    out = {}
    for tol in tols:
        tp = np = nt = 0
        for s in gt:
            pb = _collapse({x.start for x in pred.get(s, [])} | {x.end for x in pred.get(s, [])})
            tb = _collapse({x.start for x in gt[s]} | {x.end for x in gt[s]})
            tp += _greedy_match(pb, tb, tol)
            np += len(pb); nt += len(tb)
        p = tp / np if np else 0.0
        r = tp / nt if nt else 0.0
        out[tol] = {"precision": p, "recall": r,
                    "f1": 2 * p * r / (p + r) if p + r else 0.0,
                    "n_pred": np, "n_true": nt, "tp": tp}
    return out


def _iou(a: tuple[int, int], b: tuple[int, int]) -> float:
    lo = max(a[0], b[0]); hi = min(a[1], b[1])
    inter = max(0, hi - lo)
    union = (a[1] - a[0]) + (b[1] - b[0]) - inter
    return inter / union if union > 0 else 0.0


def segment_scores(pred: dict[str, list[Segment]], gt: dict[str, list[Execution]]) -> dict[str, Any]:
    ious, matched_pairs = [], []
    over = under = 0
    n_pred = n_true = 0
    for s in gt:
        P = sorted(pred.get(s, []), key=lambda x: x.start)
        T = sorted(gt[s], key=lambda x: x.start)
        n_pred += len(P); n_true += len(T)
        for t in T:
            best, bi = 0.0, None
            for i, p in enumerate(P):
                v = _iou((p.start, p.end), (t.start, t.end))
                if v > best:
                    best, bi = v, i
            ious.append(best)
            if bi is not None:
                matched_pairs.append((s, bi, t))
            # how many predictions materially overlap this execution?
            k = sum(1 for p in P if _iou((p.start, p.end), (t.start, t.end)) > 0.15)
            if k > 1:
                over += 1
        for p in P:
            k = sum(1 for t in T if _iou((p.start, p.end), (t.start, t.end)) > 0.15)
            if k > 1:
                under += 1
    return {
        "n_pred": n_pred, "n_true": n_true, "ratio": n_pred / n_true if n_true else 0.0,
        "mean_iou": statistics.mean(ious) if ious else 0.0,
        "median_iou": statistics.median(ious) if ious else 0.0,
        "matched_iou50": sum(1 for v in ious if v >= 0.5) / len(ious) if ious else 0.0,
        "matched_iou25": sum(1 for v in ious if v >= 0.25) / len(ious) if ious else 0.0,
        "over_segmented_execs": over, "under_segmenting_preds": under,
        "matched_pairs": matched_pairs,
    }


def _union(iv):
    iv = sorted(iv)
    out = []
    for a, b in iv:
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def _len(iv) -> int:
    return sum(b - a for a, b in iv)


def _inter(x, y) -> int:
    x, y = _union(x), _union(y)
    i = j = tot = 0
    while i < len(x) and j < len(y):
        tot += max(0, min(x[i][1], y[j][1]) - max(x[i][0], y[j][0]))
        if x[i][1] < y[j][1]:
            i += 1
        else:
            j += 1
    return tot


def coverage(pred: dict[str, list[Segment]], gt: dict[str, list[Execution]],
             sessions: dict[str, list[dict[str, Any]]]) -> dict[str, float]:
    """Time accounting.  All three quantities are unions, so they cannot exceed 1."""
    P, T, S = [], [], []
    for s in gt:
        P += [(p.start, p.end) for p in pred.get(s, [])]
        T += [(t.start, t.end) for t in gt[s]]
        ts = [e["ts"] for e in sessions[s]]
        S.append((min(ts), max(ts)))
    tp_, tt, ts_ = _len(_union(P)), _len(_union(T)), _len(_union(S))
    ov = _inter(P, T)
    return {"pred_time_h": tp_ / 3.6e6, "gt_time_h": tt / 3.6e6, "session_time_h": ts_ / 3.6e6,
            "gt_time_recovered": ov / tt if tt else 0.0,
            "pred_time_inside_gt": ov / tp_ if tp_ else 0.0}


def label_consistency(matched_pairs, pred: dict[str, list[Segment]],
                      label_of) -> dict[str, float]:
    """Cluster-quality of our labels against the GT process codes."""
    cont = collections.Counter()
    for s, i, t in matched_pairs:
        p = pred[s][i]
        cont[(label_of(p), t.code)] += 1
    if not cont:
        return {}
    n = sum(cont.values())
    by_pred = collections.Counter(); by_true = collections.Counter()
    for (a, b), v in cont.items():
        by_pred[a] += v; by_true[b] += v
    purity = sum(max(v for (a, b), v in cont.items() if a == lab)
                 for lab in by_pred) / n
    inv_purity = sum(max(v for (a, b), v in cont.items() if b == code)
                     for code in by_true) / n

    def H(c):
        return -sum((v / n) * math.log(v / n) for v in c.values() if v)
    Hp, Ht = H(by_pred), H(by_true)
    Hpt = -sum((v / n) * math.log(v / by_true[b]) for (a, b), v in cont.items() if v)
    Htp = -sum((v / n) * math.log(v / by_pred[a]) for (a, b), v in cont.items() if v)
    hom = 1 - Hpt / Hp if Hp else 1.0
    com = 1 - Htp / Ht if Ht else 1.0
    v = 2 * hom * com / (hom + com) if hom + com else 0.0

    def C2(x): return x * (x - 1) / 2
    idx = sum(C2(v_) for v_ in cont.values())
    ea = sum(C2(v_) for v_ in by_pred.values())
    eb = sum(C2(v_) for v_ in by_true.values())
    exp = ea * eb / C2(n) if n > 1 else 0
    mx = (ea + eb) / 2
    ari = (idx - exp) / (mx - exp) if mx != exp else 0.0
    return {"n": n, "purity": purity, "inverse_purity": inv_purity,
            "homogeneity": hom, "completeness": com, "v_measure": v, "ari": ari,
            "n_labels": len(by_pred), "n_gt_codes": len(by_true), "contingency": cont}


def report(pred, gt, sessions, label_of, title="") -> dict[str, Any]:
    b = boundary_scores(pred, gt)
    s = segment_scores(pred, gt)
    c = coverage(pred, gt, sessions)
    l = label_consistency(s["matched_pairs"], pred, label_of)
    if title:
        print(f"\n===== {title} =====")
    print(f"segments: pred={s['n_pred']} true={s['n_true']} ratio={s['ratio']:.3f}")
    for tol, m in b.items():
        print(f"boundary @{tol/1000:>3.0f}s : P={m['precision']:.3f} R={m['recall']:.3f} "
              f"F1={m['f1']:.3f}  (tp={m['tp']} pred={m['n_pred']} true={m['n_true']})")
    print(f"IoU: mean={s['mean_iou']:.3f} median={s['median_iou']:.3f} "
          f"@>=0.5={s['matched_iou50']:.3f} @>=0.25={s['matched_iou25']:.3f}")
    print(f"over-segmented GT execs={s['over_segmented_execs']}  "
          f"under-segmenting preds={s['under_segmenting_preds']}")
    print(f"time: GT recovered={c['gt_time_recovered']:.3f}  pred inside GT={c['pred_time_inside_gt']:.3f}  "
          f"(pred {c['pred_time_h']:.1f}h / gt {c['gt_time_h']:.1f}h / session {c['session_time_h']:.1f}h)")
    if l:
        print(f"labels: n={l['n_labels']} vs {l['n_gt_codes']} GT codes | purity={l['purity']:.3f} "
              f"inv_purity={l['inverse_purity']:.3f} V={l['v_measure']:.3f} ARI={l['ari']:.3f}")
    return {"boundary": b, "segment": s, "coverage": c, "label": l}
