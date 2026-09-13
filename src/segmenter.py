"""Anchor-anchored context segmentation (AACS).

The method in one paragraph
---------------------------
Every business process in these logs is executed against one screen of one
back-office web system, and each individual case on that screen is opened by
clicking a worklist row and closed by clicking an action button.  So we

  (1) resolve, for every event, *which system + which screen* the browser is on,
      carrying that context forward across the Excel / Word / Notepad detours
      that make up most of the wall clock;
  (2) find the *case cycles* -- row-open ... action-button-commit -- inside each
      context; each cycle is the core of one execution;
  (3) place the boundary between two consecutive cores at a fixed fraction of
      the dead time between them (measured on dataset A), and leave a hole
      instead of interpolating when that dead time is long enough to be a
      genuine interruption;
  (4) fall back to portal-excursion cycles where the browser extension was
      disconnected and no DOM anchors exist;
  (5) drop everything that never touched a work screen.

Nothing here is trained on dataset A's process names.  The only two numbers
taken from dataset A are the boundary fraction and the interruption threshold,
both of which are expressed relative to the session's own rhythm so they carry
across a dataset with a different tempo.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any

from features import resolve_contexts, enrich_side_apps, case_anchor, l2_case_anchors


# ---- tuned on dataset A (see reports/step1_segmentation_report.md) ----------
# A GT execution does not start at its row-click and does not end at its commit:
# measured over dataset A's 2,009 executions, the row-open lands 4.66 s after the
# execution starts (p10 3.11 / p90 5.55) and the commit lands 3.27 s before it
# ends (p10 2.62).  Relative to the median core (commit - open = 20.9 s) that is
# a lead of 0.223 and a tail of 0.156.  Expressing them as fractions of the
# *session's own* median core is what lets the same constants work on dataset B,
# whose cases run ~5x faster.
LEAD_FRAC = 0.21          # segment starts this x ref before the row-open
TAIL_FRAC = 0.22          # segment ends this x ref after the commit (last core only)
BOUNDARY_FRAC = 0.44      # if lead+tail will not fit, split the dead time here
# Dead time is asymmetric.  Measured over dataset A: 1,844 of 1,946 consecutive
# GT executions abut to within 50 ms, and the quiet stretches (>15 s of no
# meaningful action) sit *inside* an execution, after its commit -- 84 minutes of
# them in Chrome alone.  Only 34 minutes in the whole dataset falls in a genuine
# hole between two executions.  So the default is: the segment that just
# committed owns the dead time until the next segment's lead-in begins.
ABSORB_MULT = 14.0        # ... but never absorb more than this x ref; beyond that
                          #     the stretch is treated as an un-owned interruption
MIN_EVENTS = 6            # a segment with fewer events than this is not a unit of work
MIN_DURATION_MS = 3000
REOPEN_MERGE_MS = 2500    # two row-opens this close are one re-selection, not two cases


@dataclass
class Core:
    """The DOM-visible core of a single case: worklist row -> action button."""
    open_ts: int
    commit_ts: int
    ctx: tuple[str, str]
    case_key: str | None
    verb: str | None
    kind: str = "anchor"   # 'anchor' | 'excursion' (L3-less fallback)


def _reference_span(cores: list["Core"]) -> float:
    """The session's own case length, used to scale every margin.

    Prefer the median open->commit span of the DOM cores.  When only point cores
    exist (extension-less sessions) that span is zero, so fall back to a fraction
    of the median spacing between consecutive cores -- the same quantity one step
    removed.  20 s is the last resort and matches dataset A's overall median.
    """
    real = [c.commit_ts - c.open_ts for c in cores if c.commit_ts > c.open_ts]
    if real:
        return max(statistics.median(real), 1_000.0)
    gaps = [b.open_ts - a.open_ts for a, b in zip(cores, cores[1:]) if b.open_ts > a.open_ts]
    if gaps:
        return max(min(statistics.median(gaps) * 0.6, 60_000.0), 3_000.0)
    return 20_000.0


@dataclass
class Segment:
    session: str
    start: int
    end: int
    ctx: tuple[str, str]
    n_events: int
    kind: str
    case_key: str | None = None
    verb: str | None = None


# --------------------------------------------------------------------------- #
# 1. case cores
# --------------------------------------------------------------------------- #
def _anchor_cores(events: list[dict[str, Any]]) -> list[Core]:
    """Pair row-open anchors with the commit that closes them."""
    cores: list[Core] = []
    pending: dict[str, Any] | None = None

    for e in events:
        a = case_anchor(e)
        if a is None:
            continue
        kind, key = a
        ctx = e.get("ctx")
        if ctx is None:
            continue
        if kind == "open":
            if pending is not None:
                same_ctx = pending["ctx"] == ctx
                near = e["ts"] - pending["last_open"] <= REOPEN_MERGE_MS
                if same_ctx and (near or pending["key"] == key):
                    # re-selecting the same row / correcting a mis-click
                    pending["last_open"] = e["ts"]
                    continue
                # an open with no commit before it: the previous case was
                # abandoned or its commit was not captured -- close it here.
                cores.append(Core(pending["ts"], e["ts"], pending["ctx"],
                                  pending["key"], None))
            pending = {"ts": e["ts"], "last_open": e["ts"], "ctx": ctx, "key": key}
        else:  # commit
            if pending is not None and pending["ctx"] == ctx:
                cores.append(Core(pending["ts"], e["ts"], ctx, pending["key"], key))
                pending = None
            elif pending is not None:
                # commit on a different screen than the open we are holding:
                # close the held one, and treat this commit as its own core.
                cores.append(Core(pending["ts"], pending["last_open"], pending["ctx"],
                                  pending["key"], None))
                pending = None
                cores.append(Core(e["ts"], e["ts"], ctx, None, key))
            else:
                cores.append(Core(e["ts"], e["ts"], ctx, None, key))
    if pending is not None:
        cores.append(Core(pending["ts"], pending["last_open"], pending["ctx"],
                          pending["key"], None))
    cores.sort(key=lambda c: c.open_ts)
    return cores


def _l2_cores(events: list[dict[str, Any]], covered: list[tuple[int, int]]) -> list[Core]:
    """Cores for stretches where no DOM anchor exists.

    12.8% of dataset A's executions carry no `browser_click` at all, and 88% of
    those sit in a session where the browser extension never connected (7 of 63
    sessions in A, 1 of 15 in B).  There the only trace of the worklist click is
    an L2 `mouse_click` with the browser in the foreground -- see
    `features.l2_open_anchors`.

    These cores are points, not intervals: without the DOM we can see where a
    case *starts* but not where its action button was pressed.  `_expand` closes
    them against the next core's lead-in, which is the correct model anyway
    (dataset A's executions abut).
    """
    def is_covered(ts: int) -> bool:
        return any(a <= ts <= b for a, b in covered)

    anchors, family = l2_case_anchors(events)
    cores: list[Core] = []
    for e in anchors:
        if is_covered(e["ts"]) or e.get("ctx") is None:
            continue
        cores.append(Core(e["ts"], e["ts"], e["ctx"], None, None, kind=f"l2-{family}"))
    return cores


# --------------------------------------------------------------------------- #
# 2. cores -> segments
# --------------------------------------------------------------------------- #
def _expand(session: str, events: list[dict[str, Any]], cores: list[Core]) -> list[Segment]:
    if not cores:
        return []
    ts = [e["ts"] for e in events]
    t0, t1 = ts[0], ts[-1]

    ref = _reference_span(cores)                      # this session's own tempo

    lead, tail = LEAD_FRAC * ref, TAIL_FRAC * ref
    absorb_cap = ABSORB_MULT * ref

    # ---- 1. starts: a tight lead-in before the worklist row is clicked ------
    starts: list[int] = []
    for i, c in enumerate(cores):
        s_ = int(c.open_ts - lead)
        if i:
            s_ = max(s_, cores[i - 1].commit_ts + 1)   # never precede the last commit
        starts.append(max(t0, s_))

    # ---- 2. ends: absorb the trailing dead time up to the next lead-in ------
    bounds: list[tuple[int, int]] = []
    for i, c in enumerate(cores):
        if i + 1 < len(cores):
            gap = starts[i + 1] - c.commit_ts
            if gap <= 0:
                end = max(c.commit_ts, starts[i + 1] - 1)
            elif gap <= absorb_cap:
                end = starts[i + 1] - 1
            else:
                # too long to be in-process think time: leave the excess unowned
                end = int(c.commit_ts + max(tail, absorb_cap * 0.5))
        elif c.commit_ts > c.open_ts:
            end = int(c.commit_ts + tail)
        else:
            # point core (L2 fallback): no visible commit, so close it after one
            # median case length rather than immediately.
            end = int(c.open_ts + ref)
        bounds.append((max(t0, starts[i]), min(t1, max(end, starts[i] + 1))))

    segs: list[Segment] = []
    for c, (a, b) in zip(cores, bounds):
        if b <= a:
            b = a + 1
        n = sum(1 for t in ts if a <= t <= b)
        segs.append(Segment(session, a, b, c.ctx, n, c.kind, c.case_key, c.verb))
    return segs


def _drop_noise(segs: list[Segment]) -> list[Segment]:
    """Reject anything too small or too sparse to be a unit of work."""
    return [s for s in segs
            if s.n_events >= MIN_EVENTS and (s.end - s.start) >= MIN_DURATION_MS]


def _fix_overlaps(segs: list[Segment]) -> list[Segment]:
    segs = sorted(segs, key=lambda s: (s.start, s.end))
    for a, b in zip(segs, segs[1:]):
        if b.start < a.end:
            mid = (a.end + b.start) // 2
            a.end, b.start = mid, mid
    return [s for s in segs if s.end > s.start]


def segment_session(session: str, events: list[dict[str, Any]],
                    use_fallback: bool = True,
                    screen_map: dict | None = None) -> list[Segment]:
    resolve_contexts(events, screen_map)
    enrich_side_apps(events)
    cores = _anchor_cores(events)
    if use_fallback:
        ref = int(_reference_span(cores))
        # Suppress the L2 fallback wherever a DOM anchor already speaks for the
        # case, plus a margin, so the two mechanisms never double-count.
        covered = [(c.open_ts - ref, c.commit_ts + ref) for c in cores]
        cores = sorted(cores + _l2_cores(events, covered), key=lambda c: c.open_ts)
    segs = _expand(session, events, cores)
    return _fix_overlaps(_drop_noise(segs))


def segment_dataset(sessions: dict[str, list[dict[str, Any]]],
                    use_fallback: bool = True,
                    screen_map: dict | None = None) -> dict[str, list[Segment]]:
    return {s: segment_session(s, evs, use_fallback, screen_map)
            for s, evs in sessions.items()}
