"""Discover the process identities present in dataset B, from dataset B alone.

Three questions, in order:
  1. what distinct screens (= candidate processes) does B contain?
  2. does any one of those screens actually host two different processes?
  3. do any two screens host the same process and need merging?
"""
import collections, json, statistics, sys

from common import load_sessions, PORT_SYSTEM, BUILD
import screenmap, segmenter
from fingerprint import fingerprint, cosine, centroid, two_means

ev = load_sessions("B")
smap = screenmap.learn(ev, PORT_SYSTEM)
pred = segmenter.segment_dataset(ev, True, smap)

name_of = {}
for (sysn, jp), route in smap.items():
    name_of.setdefault((sysn, route), jp)

fps = collections.defaultdict(list)
segs = collections.defaultdict(list)
for s, ss in pred.items():
    for sg in ss:
        k = f"{sg.ctx[0]}/{sg.ctx[1]}"
        fps[k].append(fingerprint(ev[s], sg))
        segs[k].append((s, sg))

print("=== 1. candidate processes (screens) ===")
print(f"{'screen':26s} {'segs':>5s} {'sess':>5s} {'med_s':>7s} {'total_min':>9s}  screen name (from B's own OCR)")
for k in sorted(fps, key=lambda k: -len(fps[k])):
    d = [f["_dur_s"] for f in fps[k]]
    sysn, route = k.split("/")
    print(f"{k:26s} {len(fps[k]):5d} {len(set(s for s, _ in segs[k])):5d} "
          f"{statistics.median(d):7.1f} {sum(d)/60:9.1f}  {name_of.get((sysn, route), '?')}")

print("\n=== 2. split test: is any screen hosting two processes? ===")
print(f"{'screen':26s} {'sizes':>12s} {'separation':>11s}  discriminating features")
splits = {}
for k in sorted(fps):
    lab, sep = two_means(fps[k])
    if sep <= 0:
        print(f"{k:26s} {'-':>12s} {'n/a':>11s}  (too few segments or degenerate split)")
        continue
    c0 = centroid([f for f, l in zip(fps[k], lab) if l == 0])
    c1 = centroid([f for f, l in zip(fps[k], lab) if l == 1])
    diff = sorted(((abs(c0.get(x, 0) - c1.get(x, 0)), x) for x in set(c0) | set(c1)), reverse=True)
    top = ", ".join(f"{x}({c0.get(x,0):.2f}|{c1.get(x,0):.2f})" for _, x in diff[:3])
    print(f"{k:26s} {str((lab.count(0), lab.count(1))):>12s} {sep:11.3f}  {top}")
    splits[k] = sep

print("\n=== 3. merge test: are any two screens the same process? ===")
cents = {k: centroid(v) for k, v in fps.items()}
pairs = []
for a in sorted(cents):
    for b in sorted(cents):
        if a < b:
            pairs.append((cosine(cents[a], cents[b]), a, b))
pairs.sort(reverse=True)
for sim, a, b in pairs[:8]:
    print(f"  {sim:.3f}  {a:26s} <-> {b}")
print(f"  ... {len(pairs)-8} further pairs below {pairs[8][0]:.3f}")

json.dump({"screens": {k: {"segments": len(v), "median_s": statistics.median(f["_dur_s"] for f in v),
                           "name_jp": name_of.get(tuple(k.split("/")), "")}
                       for k, v in fps.items()},
           "split_separation": splits,
           "top_merge_pairs": [[round(s, 3), a, b] for s, a, b in pairs[:8]]},
          open(f"{BUILD}/discovery_B.json", "w"), ensure_ascii=False, indent=1)
