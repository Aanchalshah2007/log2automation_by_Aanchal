"""What repeats once per execution when the browser extension is down (L2 only)?"""
import collections, statistics
from common import load_sessions
from features import resolve_contexts, enrich_side_apps, case_anchor
from groundtruth import load_gt

ev = load_sessions("A"); gt = load_gt()
for s in ev:
    resolve_contexts(ev[s]); enrich_side_apps(ev[s])

cand = collections.defaultdict(list)
for s, execs in gt.items():
    evs = ev[s]
    for x in execs:
        win = [e for e in evs if x.start <= e["ts"] <= x.end]
        c = collections.Counter()
        for e in win:
            t, app = e["type"], e.get("app")
            if t == "shortcut":
                c[f"{e.get('keys')}@{app}"] += 1
                c[f"any:{e.get('keys')}"] += 1
            elif t == "clipboard_change":
                c["clipboard_change"] += 1
            elif t == "app_switch" and e.get("new_app") != e.get("prev_app"):
                c[f"switch:{e.get('prev_app')}->{e.get('new_app')}"] += 1
            elif t == "window_title_change":
                c["window_title_change"] += 1
        for k, v in c.items():
            cand[k].append(v)
n = sum(len(v) for v in gt.values())
rows = []
for k, v in cand.items():
    if len(v) < n * 0.5:
        continue
    v = v + [0] * (n - len(v))
    exactly_one = sum(1 for x in v if x == 1) / n
    rows.append((exactly_one, statistics.mean(v), k, len(cand[k]) / n))
rows.sort(reverse=True)
print(f"{'exactly-1':>9} {'mean/exec':>9} {'present':>8}  marker")
for e1, mu, k, pres in rows[:22]:
    print(f"{e1:9.3f} {mu:9.2f} {pres:8.2f}  {k}")

# how good is 'Ctrl+V@Notepad' as a per-case surrogate, restricted to anchorless execs?
anch = {}
for s, execs in gt.items():
    evs = ev[s]
    a = {e["ts"] for e in evs if case_anchor(e)}
    for x in execs:
        anch[(s, x.start)] = any(x.start <= t <= x.end for t in a)
for marker in ["Ctrl+V@Notepad", "clipboard_change", "any:Ctrl+V", "Ctrl+F@Microsoft Excel", "any:Ctrl+F"]:
    vals = []
    i = 0
    for s, execs in gt.items():
        evs = ev[s]
        for x in execs:
            if anch[(s, x.start)]:
                continue
            c = 0
            for e in evs:
                if not (x.start <= e["ts"] <= x.end):
                    continue
                if marker.startswith("any:") and e["type"] == "shortcut" and e.get("keys") == marker[4:]:
                    c += 1
                elif marker == "clipboard_change" and e["type"] == "clipboard_change":
                    c += 1
                elif "@" in marker and e["type"] == "shortcut" and f"{e.get('keys')}@{e.get('app')}" == marker:
                    c += 1
            vals.append(c)
    print(f"\n[anchorless execs, n={len(vals)}] {marker}: "
          f"distribution={dict(collections.Counter(vals).most_common(6))}")
