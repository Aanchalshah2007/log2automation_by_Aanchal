import sys
from common import load_sessions, PORT_SYSTEM
from groundtruth import load_gt
from segmenter import segment_dataset
import screenmap
import evaluate

ev = load_sessions("A")
gt = load_gt()
smap = screenmap.learn(ev, PORT_SYSTEM)
label_of = lambda p: f"{p.ctx[0]}/{p.ctx[1]}"

for fb in (False, True):
    evaluate.report(segment_dataset(ev, use_fallback=fb, screen_map=smap), gt, ev, label_of,
                    f"AACS  fallback={fb}")

# the sessions where the browser extension never connected
weak = [s for s in ev if sum(1 for e in ev[s] if e["layer"] == "L3") < 20]
sub = {s: ev[s] for s in weak}
evaluate.report(segment_dataset(sub, use_fallback=True, screen_map=smap),
                {s: gt[s] for s in weak}, sub, label_of,
                f"extension-less sessions only (n={len(weak)})")
strong = [s for s in ev if s not in weak]
sub2 = {s: ev[s] for s in strong}
evaluate.report(segment_dataset(sub2, use_fallback=True, screen_map=smap),
                {s: gt[s] for s in strong}, sub2, label_of,
                f"sessions with the extension (n={len(strong)})")
