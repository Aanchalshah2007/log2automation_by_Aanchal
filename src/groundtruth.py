"""Ground truth for dataset A, reconstructed defensively.

DATA_SCHEMA.md warns that gt.jsonl "sometimes emits the same process_started
twice in a row" and that "process_switched_out does not always pair up".  On top
of that, 257 of the 2,009 executions in gt_manifest.json carry `end_ts: null`.

Rather than trusting either file alone we rebuild the interval list from the
gt.jsonl event stream (which is complete) and use gt_manifest only to attach
variant / case metadata and to cross-check the intervals we can check.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import dataclass, field
from typing import Any

from common import DATASETS

OPEN_EVENTS = {"process_started", "process_resumed"}
CLOSE_EVENTS = {"process_switched_out", "process_suspended"}


def _ms(ts: str) -> int:
    return int(dt.datetime.fromisoformat(ts).timestamp() * 1000)


@dataclass
class Execution:
    session: str
    code: str
    name: str
    domain: str
    start: int
    end: int
    case_id: str | None = None
    variant: str | None = None
    phase: int = 1
    source: str = "gt.jsonl"


def _catalog(session_dir: str) -> tuple[dict[str, tuple[str, str]], list[dict[str, Any]]]:
    """process_code -> (family_name, domain), plus the raw execution records."""
    path = os.path.join(session_dir, "gt_manifest.json")
    names: dict[str, tuple[str, str]] = {}
    execs: list[dict[str, Any]] = []
    if not os.path.exists(path):
        return names, execs
    m = json.load(open(path, encoding="utf-8"))
    for p in m.get("processes", []):
        names[p["code"]] = (p.get("family_name", p["code"]), p.get("domain", "?"))
        for x in p.get("executions", []):
            execs.append({**x, "code": p["code"]})
    return names, execs


def load_gt(session_ids: list[str] | None = None) -> dict[str, list[Execution]]:
    """session_id -> non-overlapping execution intervals, ordered by start."""
    root = DATASETS["A"]
    out: dict[str, list[Execution]] = {}
    for session in sorted(os.listdir(root)):
        sdir = os.path.join(root, session)
        if not os.path.isdir(sdir) or not os.path.exists(os.path.join(sdir, "gt.jsonl")):
            continue
        if session_ids is not None and session not in session_ids:
            continue
        names, mexecs = _catalog(sdir)
        lines = [json.loads(l) for l in open(os.path.join(sdir, "gt.jsonl"), encoding="utf-8")]
        lines.sort(key=lambda e: e["ts_utc"])

        # Pass 1 - walk the event stream and close each open execution at the
        # first of: an explicit close, the next open (the duplicate-start quirk,
        # which is exactly how a back-to-back repeat of the same process is
        # recorded), or session_ended.
        execs: list[Execution] = []
        cur: dict[str, Any] | None = None

        def close(at: int) -> None:
            nonlocal cur
            if cur is None:
                return
            if at > cur["start"]:
                fam, dom = names.get(cur["code"], (cur.get("process_name", cur["code"]), "?"))
                execs.append(Execution(
                    session=session, code=cur["code"], name=fam, domain=dom,
                    start=cur["start"], end=at, case_id=cur.get("case_id"),
                    variant=cur.get("process_variant"), phase=cur.get("phase", 1)))
            cur = None

        for e in lines:
            ev = e["event"]
            t = _ms(e["ts_utc"])
            if ev in OPEN_EVENTS:
                close(t)
                cur = {"code": e.get("process_code") or e.get("current_process"),
                       "start": t, "case_id": e.get("case_id"),
                       "process_variant": e.get("process_variant"),
                       "process_name": e.get("process_name"),
                       "phase": e.get("phase", 1)}
            elif ev in CLOSE_EVENTS:
                close(t)
            elif ev == "session_ended":
                close(t)
        if cur is not None:
            close(cur["start"] + 1)

        # Pass 2 - attach variant from gt_manifest by (code, case_id) where the
        # stream did not carry one, and prefer the manifest's end_ts when it
        # exists and is not wilder than the reconstructed one.
        by_case = {(x["code"], x.get("case_id")): x for x in mexecs}
        for x in execs:
            m = by_case.get((x.code, x.case_id))
            if m:
                x.variant = x.variant or m.get("variant")
                x.phase = m.get("phase", x.phase)
        execs.sort(key=lambda x: x.start)
        out[session] = execs
    return out


def gt_manifest_intervals() -> dict[str, list[tuple[int, int, str]]]:
    """Only the executions where gt_manifest gives both timestamps (for cross-check)."""
    root = DATASETS["A"]
    out: dict[str, list[tuple[int, int, str]]] = {}
    for session in sorted(os.listdir(root)):
        sdir = os.path.join(root, session)
        p = os.path.join(sdir, "gt_manifest.json")
        if not os.path.exists(p):
            continue
        rows = []
        m = json.load(open(p, encoding="utf-8"))
        for proc in m.get("processes", []):
            for x in proc.get("executions", []):
                if x.get("start_ts") and x.get("end_ts"):
                    rows.append((_ms(x["start_ts"]), _ms(x["end_ts"]), proc["code"]))
        rows.sort()
        out[session] = rows
    return out


if __name__ == "__main__":
    import statistics
    gt = load_gt()
    mani = gt_manifest_intervals()
    n = sum(len(v) for v in gt.values())
    durs = [(x.end - x.start) / 1000 for v in gt.values() for x in v]
    print(f"sessions={len(gt)} reconstructed executions={n}")
    print(f"duration s: median={statistics.median(durs):.1f} mean={statistics.mean(durs):.1f} "
          f"min={min(durs):.1f} max={max(durs):.1f}")
    # overlap check
    ov = sum(1 for v in gt.values() for a, b in zip(v, v[1:]) if b.start < a.end - 1)
    print(f"overlapping consecutive executions: {ov}")
    # agreement with gt_manifest where it gives an end_ts
    diffs, matched = [], 0
    for s, rows in mani.items():
        idx = {(x.start // 1000, x.code): x for x in gt.get(s, [])}
        for a, b, c in rows:
            k = (a // 1000, c)
            if k in idx:
                matched += 1
                diffs.append(abs(idx[k].end - b) / 1000)
    print(f"manifest executions with both ts: {sum(len(v) for v in mani.values())}, "
          f"matched by start: {matched}")
    print(f"|end_ts difference| s: median={statistics.median(diffs):.2f} "
          f"p90={sorted(diffs)[int(.9*len(diffs))]:.2f} max={max(diffs):.1f} "
          f"within_2s={100*sum(1 for d in diffs if d <= 2)/len(diffs):.1f}%")
