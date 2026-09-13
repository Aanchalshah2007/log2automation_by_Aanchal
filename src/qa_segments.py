"""Programmatic quality gate for segments.jsonl.  Exits non-zero on any failure."""
import collections, datetime as dt, json, os, statistics, sys

from common import load_sessions, DATASETS, ROOT

PATH = os.path.join(ROOT, "segments.jsonl")
FIELDS = {"session_id", "start", "end", "label"}
ISO = "%Y-%m-%dT%H:%M:%SZ"


def main() -> int:
    ev = load_sessions("B")
    valid_sessions = {d for d in os.listdir(DATASETS["B"])
                      if os.path.isdir(os.path.join(DATASETS["B"], d))}
    span = {s: (min(e["ts"] for e in v), max(e["ts"] for e in v)) for s, v in ev.items()}

    rows, bad_json = [], 0
    for i, line in enumerate(open(PATH, encoding="utf-8"), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append((i, json.loads(line)))
        except json.JSONDecodeError:
            bad_json += 1

    fails: list[str] = []
    warns: list[str] = []

    def check(name, ok, detail=""):
        (print(f"  PASS  {name}" + (f"  ({detail})" if detail else ""))
         if ok else fails.append(f"{name}: {detail}"))
        if not ok:
            print(f"  FAIL  {name}  ({detail})")

    print(f"segments.jsonl: {len(rows)} lines\n")
    check("valid JSONL", bad_json == 0, f"{bad_json} unparseable lines")
    check("exact field set", all(set(r) == FIELDS for _, r in rows),
          str([i for i, r in rows if set(r) != FIELDS][:5]))

    bad_sess = [i for i, r in rows if r["session_id"] not in valid_sessions]
    check("session_id matches a real session directory", not bad_sess, str(bad_sess[:5]))

    ts = {}
    bad_fmt = []
    for i, r in rows:
        try:
            ts[i] = (dt.datetime.strptime(r["start"], ISO).replace(tzinfo=dt.timezone.utc),
                     dt.datetime.strptime(r["end"], ISO).replace(tzinfo=dt.timezone.utc))
        except ValueError:
            bad_fmt.append(i)
    check("timestamps are ISO 8601 UTC (…Z)", not bad_fmt, str(bad_fmt[:5]))

    bad_order = [i for i, r in rows if i in ts and ts[i][0] >= ts[i][1]]
    check("start < end", not bad_order, str(bad_order[:5]))

    out_of_range = []
    for i, r in rows:
        if i not in ts:
            continue
        lo, hi = span[r["session_id"]]
        a, b = ts[i][0].timestamp() * 1000, ts[i][1].timestamp() * 1000
        if a < lo - 1000 or b > hi + 1000:
            out_of_range.append(i)
    check("inside the session's event range", not out_of_range, str(out_of_range[:5]))

    # every boundary must sit on real activity
    no_events = []
    for i, r in rows:
        if i not in ts:
            continue
        a, b = ts[i][0].timestamp() * 1000, ts[i][1].timestamp() * 1000
        n = sum(1 for e in ev[r["session_id"]] if a <= e["ts"] <= b)
        if n < 3:
            no_events.append((i, n))
    check("each segment contains >=3 events", not no_events, str(no_events[:5]))

    dup = [k for k, v in collections.Counter(
        (r["session_id"], r["start"], r["end"], r["label"]) for _, r in rows).items() if v > 1]
    check("no duplicate segments", not dup, str(dup[:3]))

    overlaps = []
    by_s = collections.defaultdict(list)
    for i, r in rows:
        if i in ts:
            by_s[r["session_id"]].append((ts[i][0], ts[i][1], i))
    for s, v in by_s.items():
        v.sort()
        for a, b in zip(v, v[1:]):
            if b[0] < a[1]:
                overlaps.append((s, a[2], b[2]))
    check("no overlapping segments", not overlaps, f"{len(overlaps)} overlaps {overlaps[:3]}")

    durs = sorted((ts[i][1] - ts[i][0]).total_seconds() for i, _ in rows if i in ts)
    impossible = [d for d in durs if d < 2 or d > 1800]
    check("no impossible durations (2 s - 30 min)", not impossible, str(impossible[:5]))

    # unexplained silence inside a segment
    silent = []
    for i, r in rows:
        if i not in ts:
            continue
        a, b = ts[i][0].timestamp() * 1000, ts[i][1].timestamp() * 1000
        w = [e["ts"] for e in ev[r["session_id"]] if a <= e["ts"] <= b]
        if len(w) > 1:
            g = max(y - x for x, y in zip(w, w[1:]))
            if g > 60_000:
                silent.append((i, round(g / 1000)))
    check("no >60 s silent gap inside a segment", not silent, str(silent[:5]))

    labs = collections.Counter(r["label"] for _, r in rows)
    check("labels are stable identifiers (no per-instance suffixes)",
          all(not l.rsplit("_", 1)[-1].isdigit() for l in labs), str(list(labs)[:5]))
    check("every label used more than once", all(v > 1 for v in labs.values()),
          str([l for l, v in labs.items() if v == 1]))

    covered = {r["session_id"] for _, r in rows}
    check("dataset B fully processed", covered == set(ev), str(sorted(set(ev) - covered)))

    # ---- informational ----
    tot_seg = sum(durs)
    tot_sess = sum((hi - lo) / 1000 for lo, hi in span.values())
    print(f"\n  info  labels={len(labs)}  segments={len(rows)}  sessions={len(covered)}")
    print(f"  info  segment time {tot_seg/60:.0f} min of {tot_sess/60:.0f} min recorded "
          f"({100*tot_seg/tot_sess:.0f}%)")
    print(f"  info  duration s: min={durs[0]:.0f} median={statistics.median(durs):.0f} "
          f"p90={durs[int(.9*len(durs))]:.0f} max={durs[-1]:.0f}")
    persess = collections.Counter(r["session_id"] for _, r in rows)
    thin = [s for s, n in persess.items() if n < 10]
    if thin:
        warns.append(f"sessions with <10 segments: {thin}")
    for w in warns:
        print(f"  WARN  {w}")

    print()
    if fails:
        print(f"{len(fails)} CHECK(S) FAILED")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
