"""Apply the validated segmenter to dataset B and write segments.jsonl."""
import collections, json, os, statistics

from common import load_sessions, PORT_SYSTEM, ROOT, iso_utc
import labels as L
import screenmap
from segmenter import segment_dataset

OUT = os.path.join(ROOT, "segments.jsonl")


def main() -> None:
    ev = load_sessions("B")
    smap = screenmap.learn(ev, PORT_SYSTEM)
    table = L.build(smap)
    pred = segment_dataset(ev, use_fallback=True, screen_map=smap)

    rows = []
    for session in sorted(pred):
        for sg in sorted(pred[session], key=lambda x: x.start):
            rows.append({"session_id": session,
                         "start": iso_utc(sg.start),
                         "end": iso_utc(sg.end),
                         "label": L.label_for(sg.ctx, table)})
    # A second-resolution start/end can collapse a very short segment; drop those
    # rather than emit start == end.
    rows = [r for r in rows if r["start"] < r["end"]]
    with open(OUT, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    by_label = collections.Counter(r["label"] for r in rows)
    by_sess = collections.Counter(r["session_id"] for r in rows)
    durs = sorted((sg.end - sg.start) / 1000 for v in pred.values() for sg in v)
    print(f"wrote {len(rows)} segments to {OUT}")
    print(f"sessions covered: {len(by_sess)} of {len(ev)}")
    print(f"\n{'label':34s} {'segs':>5s} {'sess':>5s} {'med_s':>7s} {'total_min':>9s}")
    tot = collections.defaultdict(float)
    ses = collections.defaultdict(set)
    for session, v in pred.items():
        for sg in v:
            lab = L.label_for(sg.ctx, table)
            tot[lab] += (sg.end - sg.start) / 1000
            ses[lab].add(session)
    med = collections.defaultdict(list)
    for session, v in pred.items():
        for sg in v:
            med[L.label_for(sg.ctx, table)].append((sg.end - sg.start) / 1000)
    for lab in sorted(by_label, key=lambda x: -by_label[x]):
        print(f"{lab:34s} {by_label[lab]:5d} {len(ses[lab]):5d} "
              f"{statistics.median(med[lab]):7.1f} {tot[lab]/60:9.1f}")
    print(f"\nduration s: min={durs[0]:.1f} p10={durs[len(durs)//10]:.1f} "
          f"median={statistics.median(durs):.1f} p90={durs[int(.9*len(durs))]:.1f} max={durs[-1]:.1f}")
    print(f"segments/session: min={min(by_sess.values())} max={max(by_sess.values())} "
          f"mean={sum(by_sess.values())/len(by_sess):.1f}")


if __name__ == "__main__":
    main()
