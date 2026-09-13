"""Full dataset-A validation, written to build/validation_A.json for the report."""
import json, statistics, collections
from common import load_sessions, PORT_SYSTEM, BUILD
from groundtruth import load_gt
from segmenter import segment_dataset
import screenmap, evaluate

ev = load_sessions("A"); gt = load_gt()
smap = screenmap.learn(ev, PORT_SYSTEM)
label_of = lambda p: f"{p.ctx[0]}/{p.ctx[1]}"
out = {}

out["all"] = evaluate.report(segment_dataset(ev, True, smap), gt, ev, label_of, "ALL 63 SESSIONS")

weak = sorted(s for s in ev if sum(1 for e in ev[s] if e["layer"] == "L3") < 20)
strong = sorted(s for s in ev if s not in weak)
for tag, ss in (("extension_present", strong), ("extension_absent", weak)):
    sub = {s: ev[s] for s in ss}
    out[tag] = evaluate.report(segment_dataset(sub, True, smap), {s: gt[s] for s in ss},
                               sub, label_of, f"{tag} (n={len(ss)})")

# held-out check: constants were fitted on the dev thirds only
allses = sorted(gt)
dev = [s for i, s in enumerate(allses) if i % 3 != 2]
hold = [s for i, s in enumerate(allses) if i % 3 == 2]
for tag, ss in (("dev", dev), ("holdout", hold)):
    sub = {s: ev[s] for s in ss}
    out[tag] = evaluate.report(segment_dataset(sub, True, smap), {s: gt[s] for s in ss},
                               sub, label_of, f"{tag} split (n={len(ss)})")

# ablations: which channel earns its place?
print("\n===== ABLATIONS =====")
abl = {}
import segmenter as SG
variants = {
    "full": dict(fallback=True, smap=smap),
    "no L2 fallback (DOM anchors only)": dict(fallback=False, smap=smap),
    "no OCR channel (no screen map)": dict(fallback=True, smap=None),
    "neither": dict(fallback=False, smap=None),
}
for name, cfg in variants.items():
    pred = segment_dataset(ev, cfg["fallback"], cfg["smap"])
    b = evaluate.boundary_scores(pred, gt, tols=(2000,))[2000]
    sc = evaluate.segment_scores(pred, gt)
    cv = evaluate.coverage(pred, gt, ev)
    lb = evaluate.label_consistency(sc["matched_pairs"], pred, label_of)
    abl[name] = {"segments": sc["n_pred"], "bF1@2s": round(b["f1"], 3),
                 "mean_iou": round(sc["mean_iou"], 3), "iou50": round(sc["matched_iou50"], 3),
                 "gt_time_recovered": round(cv["gt_time_recovered"], 3),
                 "ari": round(lb.get("ari", 0), 3)}
    print(f"  {name:36s} n={sc['n_pred']:5d} bF1@2s={b['f1']:.3f} IoU={sc['mean_iou']:.3f} "
          f"@50={sc['matched_iou50']:.3f} cov={cv['gt_time_recovered']:.3f} ARI={lb.get('ari',0):.3f}")

# contingency of our labels vs GT codes
pred = segment_dataset(ev, True, smap)
sc = evaluate.segment_scores(pred, gt)
lb = evaluate.label_consistency(sc["matched_pairs"], pred, label_of)
cont = lb.pop("contingency")
print("\n===== LABEL <-> GT CODE (matched segments) =====")
labels = sorted({a for a, _ in cont})
codes = sorted({b for _, b in cont})
print("            " + "".join(f"{c:>5}" for c in codes))
for l in labels:
    row = "".join(f"{cont.get((l, c), 0):5d}" for c in codes)
    print(f"{l:24s}{row}")

durs = sorted((p.end - p.start) / 1000 for v in pred.values() for p in v)
json.dump({"metrics": {k: {kk: (vv if not isinstance(vv, dict) else
                              {k2: (v2 if not isinstance(v2, list) else len(v2))
                               for k2, v2 in vv.items() if k2 != "matched_pairs"})
                           for kk, vv in v.items() if kk != "segment" or True}
                       for k, v in out.items() if False},
           "ablations": abl,
           "durations_s": {"n": len(durs), "min": durs[0], "p25": durs[len(durs)//4],
                           "median": statistics.median(durs), "p75": durs[3*len(durs)//4],
                           "p90": durs[int(.9*len(durs))], "max": durs[-1]}},
          open(f"{BUILD}/validation_A.json", "w"), indent=1)
print(f"\nsegment durations (s): median={statistics.median(durs):.1f} "
      f"p10={durs[len(durs)//10]:.1f} p90={durs[int(.9*len(durs))]:.1f} max={durs[-1]:.1f}")
