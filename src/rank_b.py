"""Step 2 -- measure every process in dataset B and rank it for automation.

Input : ../segments.jsonl        (the step-1 deliverable)
        build/events_B.jsonl     (the projected event cache, via common.py)
        ../reports/discovery_B.json  (step-1's optional-step split test)

Output: ../reports/step2_process_metrics.csv   one row per process, all factors
        ../reports/step2_metrics.json          the same, machine-readable,
                                               plus three robustness re-runs

Everything in the CSV is either measured from B's events or comes from the two
assumption tables in roi.py.  Nothing is carried over from dataset A.

Run:  cd src && python3 rank_b.py
"""
from __future__ import annotations

import bisect
import collections
import csv
import datetime as dt
import json
import os
import re
import statistics

from common import load_sessions, REPORTS, ROOT
import roi

SEGMENTS = os.path.join(ROOT, "segments.jsonl")
DISCOVERY = os.path.join(REPORTS, "discovery_B.json")

# B's extension-less session.  Its 49 segments carry step-1's degraded route
# labels (the dataset-A analogue of this population scores route accuracy 0.64),
# so they are counted in the headline numbers and then removed again in a
# robustness re-run.  See reports/step1_segmentation_report.md section 9.
DEGRADED_SESSION = "ses_20260701-192455-NEELA9BAF"

# The one label step 1 flagged as two business objectives sharing one worklist.
CONFLATED = "hr_expense_and_pay_change"
CONFLATED_SPLIT = {                     # [O] worklist row counts, see split_evidence()
    "hr_expense_claim_P1": 0.5,
    "hr_pay_change_P4": 0.5,
}

# Word documents divide into policy and reference.  A 規定 (kitei, regulation) or
# 手続き (tetsuzuki, procedure) is read and then judged; a 一覧 (ichiran, list) is
# looked up.  Only the first is a human decision.
RE_REGULATION = re.compile(r"kitei|tetsuzuki|checklist", re.I)
RE_REFERENCE = re.compile(r"ichiran", re.I)
# Word windows that name no document (`Opening - Word`, `Resume Reading`, `Word`)
# are chrome, not content, and are attributed to neither.
RE_WORD_CHROME = re.compile(r"^(Opening|Resume Reading|Word|Excel)\b", re.I)

# Declared per-case handling categories rendered into the Word processing
# record.  Preference order: the field that names the *handling pattern* beats
# the field that names the record type.
VARIANT_MARKERS = ["処理区分", "採用区分", "費目", "種別"]
VARIANT_MIN_OBS = 20

# The worklist itself renders a 種別 column per row: 定常 (routine) or 調整
# (adjustment -- the case needs a hand).  This is the most direct variant signal
# in the data, because it is the flag the operator reads before deciding how to
# handle the row.  It is read from the worklist OCR, so its coverage follows the
# OCR sampling and is thin on the screens that were visited in few sessions;
# `worklist_variant_sessions` in the metrics table reports that coverage.
ROUTINE_TOKEN, ADJUST_TOKEN = "定常", "調整"

RE_PORTAL = re.compile(r"127\.0\.0\.1:(\d+)/#/([a-z-]+)")
RE_ROW = re.compile(r"tbody")
RE_NOTE = re.compile(r"^#\w+-note")
RE_COMMIT = re.compile(r"^#btn-\w+-ok")
RE_PCODE_ROW = re.compile(r"(P\d+)-\d+-(\d+)")

MOCKABLE_APPS = {"Microsoft Edge", "Notepad"}

# [A] A companion application or reference document counts towards the build
#     surface only if it recurs in at least this share of the process's cases.
#     Without a floor, one operator opening Teams once during 56 leave requests
#     would be charged to the process definition as a permanent integration.
SURFACE_MIN_CASE_SHARE = 0.10


# --------------------------------------------------------------------------- #
# joining segments to the events inside them
# --------------------------------------------------------------------------- #
def parse_iso(s: str) -> int:
    return int(dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
               .replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


def foreground_timeline(evs: list[dict]) -> list[tuple[int, str | None, str | None]]:
    """(ts, app, window) whenever either changes.

    `context.active_app` lags the real foreground by one step on a large share
    of app_switch events (common.py), so the app is tracked from the app_switch
    payload and the window title from window_title_change, falling back to the
    context window only while the app is unchanged.
    """
    out: list[tuple[int, str | None, str | None]] = []
    app = win = None
    for e in evs:
        changed = False
        if e["type"] == "app_switch" and e.get("new_app"):
            app, win, changed = e["new_app"], None, True
        if e["type"] == "window_title_change" and e.get("new_title"):
            win, changed = e["new_title"], True
        elif e.get("window") and e["window"] != win and e.get("ctx_app") == app:
            win, changed = e["window"], True
        if changed:
            out.append((e["ts"], app, win))
    return out


def dwell(timeline, ts_index, a: int, b: int) -> collections.Counter:
    """(app, window) -> milliseconds of foreground time inside [a, b)."""
    out: collections.Counter = collections.Counter()
    if not timeline:
        return out
    i = bisect.bisect_right(ts_index, a) - 1
    cur = (timeline[i][1], timeline[i][2]) if i >= 0 else (None, None)
    t, j = a, max(i + 1, 0)
    while j < len(timeline) and timeline[j][0] < b:
        out[cur] += timeline[j][0] - t
        t, cur = timeline[j][0], (timeline[j][1], timeline[j][2])
        j += 1
    out[cur] += b - t
    return out


def load_segments(events: dict[str, list[dict]]) -> list[dict]:
    """segments.jsonl with the events, dwell and window history of each attached."""
    segs = [json.loads(l) for l in open(SEGMENTS, encoding="utf-8") if l.strip()]
    for s in segs:
        # segments.jsonl is truncated to whole seconds (step-1 report, assumption 8).
        # `_bn` is the nominal end and is what durations and dwell are measured
        # against, so the figures here match step 1's.  `_b` extends to the end of
        # that final second purely so events stamped inside it still attach.
        s["_a"] = parse_iso(s["start"])
        s["_bn"] = parse_iso(s["end"])
        s["_b"] = s["_bn"] + 999
        s["_ev"] = []

    tl = {sid: foreground_timeline(evs) for sid, evs in events.items()}
    tix = {sid: [t for t, _, _ in v] for sid, v in tl.items()}

    by_session = collections.defaultdict(list)
    for s in segs:
        by_session[s["session_id"]].append(s)

    for sid, ss in by_session.items():
        ss.sort(key=lambda x: x["_a"])
        starts = [x["_a"] for x in ss]
        for e in events.get(sid, []):
            i = bisect.bisect_right(starts, e["ts"]) - 1
            if i >= 0 and e["ts"] <= ss[i]["_b"]:
                ss[i]["_ev"].append(e)
        for s in ss:
            s["_dwell"] = dwell(tl[sid], tix[sid], s["_a"], s["_bn"])
    return segs


# --------------------------------------------------------------------------- #
# per-process measurement
# --------------------------------------------------------------------------- #
def measure(label: str, segs: list[dict], split_signal: float,
            worklist: dict | None = None) -> dict:
    n = len(segs)
    durs = [(s["_bn"] - s["_a"]) / 1000.0 for s in segs]

    reg_ms = ref_ms = excel_ms = mockable_ms = total_ms = unclassified_ms = 0
    unclassified_docs: set[str] = set()
    doc_cases: collections.Counter = collections.Counter()
    app_cases: collections.Counter = collections.Counter()
    machines: set[str] = set()
    sessions: set[str] = set()
    routes: collections.Counter = collections.Counter()
    markers: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    clip_chars = typed_chars = pastes = clips = 0
    n_row = n_note = n_commit = n_template = 0
    row_selectors: collections.Counter = collections.Counter()
    commit_ids: set[str] = set()
    positional_rows = 0
    degraded = 0

    for s in segs:
        sessions.add(s["session_id"])
        if s["session_id"] == DEGRADED_SESSION:
            degraded += 1
        seen_docs: set[str] = set()
        seen_apps: set[str] = set()

        for (app, win), ms in s["_dwell"].items():
            total_ms += ms
            if app in MOCKABLE_APPS:
                mockable_ms += ms
            w = win or ""
            if app == "Microsoft Word":
                if RE_WORD_CHROME.match(w.strip()):
                    continue                      # window chrome, not a document
                doc = re.sub(r"\s*[-\[]\s*Compatibility Mode.*", "", w).strip()
                if doc:
                    seen_docs.add(doc)
                if RE_REFERENCE.search(w):
                    ref_ms += ms
                elif RE_REGULATION.search(w):
                    reg_ms += ms
                else:
                    # A Word document matching neither pattern is NOT silently
                    # charged as judgment -- that would inflate the factor that
                    # decides half the ranking.  It is counted separately and
                    # surfaced in step2_metrics.json so the gap is visible if a
                    # future dataset introduces a differently named document.
                    unclassified_ms += ms
                    if doc:
                        unclassified_docs.add(doc)
            elif app == "Microsoft Excel":
                excel_ms += ms
                doc = re.sub(r"\s*-\s*Excel$", "", w).strip()
                if doc and not RE_WORD_CHROME.match(doc):
                    seen_docs.add(doc)
            elif app and app not in MOCKABLE_APPS:
                seen_apps.add(app)
            if app == "Notepad":
                seen_apps.add(app)
        doc_cases.update(seen_docs)
        app_cases.update(seen_apps)

        has_row = has_note = has_commit = False
        for e in s["_ev"]:
            machines.add(e.get("machine"))
            if e["type"] == "keystroke":
                k = e.get("key") or ""
                if len(k) == 1:
                    typed_chars += 1
            elif e["type"] == "shortcut" and e.get("keys") == "Ctrl+V":
                pastes += 1
            elif e["type"] == "clipboard_change":
                clips += 1
                clip_chars += e.get("clip_len") or 0

            sel = e.get("selector") or ""
            if sel:
                if RE_ROW.search(sel):
                    has_row = True
                    row_selectors[re.sub(r"nth-of-type\(\d+\)", "nth-of-type(N)", sel)] += 1
                    if "nth-of-type" in sel:
                        positional_rows += 1
                if RE_NOTE.match(sel):
                    has_note = True
                if RE_COMMIT.match(sel):
                    has_commit = True
                    commit_ids.add(sel)

            url = e.get("nav_url") or e.get("tab_url")
            if url:
                m = RE_PORTAL.search(url)
                if m:
                    routes[f"{m.group(1)}/{m.group(2)}"] += 1

            txt = e.get("text")
            if txt:
                for key in VARIANT_MARKERS:
                    for v in re.findall(key + r":\s*([^　\r\n]+)", txt):
                        markers[key][v.strip()] += 1

        n_row += has_row
        n_note += has_note
        n_commit += has_commit
        n_template += (has_row and has_note and has_commit)

    # declared per-case branching: 1 - the share taken by the dominant category
    marker_rate, marker_field, marker_values = 0.0, "", {}
    for key in VARIANT_MARKERS:
        c = markers[key]
        if c and sum(c.values()) >= VARIANT_MIN_OBS:
            tot = sum(c.values())
            marker_rate = 1.0 - c.most_common(1)[0][1] / tot
            marker_field, marker_values = key, dict(c.most_common())
            break

    route_purity = routes.most_common(1)[0][1] / sum(routes.values()) if routes else 0.0
    modal_route = routes.most_common(1)[0][0] if routes else ""
    wl = (worklist or {}).get(modal_route, {})
    wl_rate = wl.get("rate", 0.0)
    wl_sessions = wl.get("sessions", 0)
    wl_rows = wl.get("rows", 0)

    # The build surface is what the automation must integrate with *every* time,
    # not every application anyone ever alt-tabbed to.  Recurring surfaces only.
    floor = SURFACE_MIN_CASE_SHARE * n
    recurring_docs = sorted(d for d, k in doc_cases.items() if k >= floor)
    recurring_apps = sorted(a for a, k in app_cases.items() if k >= floor)
    surface = len(recurring_docs) + len(recurring_apps)

    return {
        "label": label,
        "cases": n,
        "sessions": len(sessions),
        "operators": len([m for m in machines if m]),
        "total_s": round(sum(durs), 1),
        "median_s": round(statistics.median(durs), 2),
        "p90_s": round(sorted(durs)[int(0.9 * (n - 1))], 1),
        "cv": round(statistics.pstdev(durs) / statistics.mean(durs), 3),
        "degraded_cases": degraded,
        "degraded_share": round(degraded / n, 3),

        "pastes_per_case": round(pastes / n, 2),
        "clipboard_events_per_case": round(clips / n, 2),
        "clip_chars_per_case": round(clip_chars / n, 1),
        "typed_chars_per_case": round(typed_chars / n, 1),

        "regulation_dwell_s_per_case": round(reg_ms / n / 1000, 2),
        "reference_dwell_s_per_case": round(ref_ms / n / 1000, 2),
        "unclassified_word_s_per_case": round(unclassified_ms / n / 1000, 2),
        "unclassified_word_docs": sorted(unclassified_docs),
        "excel_dwell_s_per_case": round(excel_ms / n / 1000, 2),
        "mockable_dwell_share": round(mockable_ms / total_ms, 3) if total_ms else 0.0,

        "apps_touched": 1 + len(app_cases),
        "apps_recurring": ";".join(recurring_apps),
        "reference_docs": len(doc_cases),
        "reference_docs_recurring": ";".join(recurring_docs),
        "integration_surface": surface,

        "template_conformance": round(n_template / n, 3),
        "row_click_rate": round(n_row / n, 3),
        "note_field_rate": round(n_note / n, 3),
        "commit_rate": round(n_commit / n, 3),
        "positional_row_target": positional_rows > 0 and all(
            "nth-of-type" in sel for sel in row_selectors),
        "commit_selector": sorted(commit_ids)[0] if commit_ids else "",
        "modal_route": modal_route,
        "route_purity": round(route_purity, 3),

        # Three independent channels see case branching from different angles;
        # take the strongest, because a branch any one of them can see is a
        # branch the automation has to handle.
        "variant_rate": round(max(marker_rate, split_signal, wl_rate), 3),
        "variant_marker_field": marker_field,
        "variant_marker_rate": round(marker_rate, 3),
        "variant_marker_values": marker_values,
        "optional_step_signal": round(split_signal, 3),
        "worklist_variant_rate": round(wl_rate, 3),
        "worklist_variant_sessions": wl_sessions,
        "worklist_variant_rows": wl_rows,
    }


def worklist_variant_rates(events: dict[str, list[dict]]) -> dict[str, dict]:
    """[O] screen -> share of worklist rows flagged 調整 rather than 定常.

    For each (screen, session) the most fully rendered worklist blob is taken --
    OCR captures the list partially most of the time -- and the per-session
    shares are then combined by median, which is less sensitive than a pooled
    sum to a blob that has a second tab's worklist bleeding into it (a known
    property of this OCR channel, see step-1 report section 4).
    """
    best: dict[str, dict[str, tuple[int, int]]] = collections.defaultdict(dict)
    for sid, evs in events.items():
        for e in evs:
            txt = e.get("text")
            url = e.get("nav_url") or e.get("tab_url") or ""
            if not txt:
                continue
            m = RE_PORTAL.search(url)
            if not m:
                continue
            screen = f"{m.group(1)}/{m.group(2)}"
            lines = [x.strip() for x in re.split(r"[\r\n]", txt)]
            adj = sum(1 for x in lines if x == ADJUST_TOKEN)
            rou = sum(1 for x in lines if x == ROUTINE_TOKEN)
            if adj + rou == 0:
                continue
            cur = best[screen].get(sid)
            if cur is None or adj + rou > sum(cur):
                best[screen][sid] = (adj, rou)
    out = {}
    for screen, per in best.items():
        shares = [a / (a + r) for a, r in per.values()]
        out[screen] = {
            "rate": statistics.median(shares),
            "sessions": len(shares),
            "rows": sum(a + r for a, r in per.values()),
        }
    return out


def split_evidence(events: dict[str, list[dict]]) -> dict:
    """[O] How the conflated hr/payroll-items worklist divides into P1 and P4.

    The P-code prefixes the case id in every worklist row rendered into
    `context.extracted_text`, even though step 1 could not attribute a code to
    an individual *clicked* row (the row selector is positional).  Counting the
    highest row index reached per code, per session, bounds the mix.
    """
    per_session: dict[str, dict[str, int]] = collections.defaultdict(dict)
    for sid, evs in events.items():
        for e in evs:
            txt = e.get("text")
            url = e.get("nav_url") or e.get("tab_url") or ""
            if not txt or "5132" not in url or "payroll-items" not in url:
                continue
            for code, idx in RE_PCODE_ROW.findall(txt):
                per_session[sid][code] = max(per_session[sid].get(code, 0), int(idx))
    totals: collections.Counter = collections.Counter()
    both = 0
    for sid, c in per_session.items():
        for k, v in c.items():
            totals[k] += v
        if "P1" in c and "P4" in c:
            both += 1
    return {
        "sessions_showing_both": both,
        "rows_by_code": dict(sorted(totals.items())),
        "p1_p4_row_ratio": (round(totals["P1"] / totals["P4"], 3) if totals["P4"] else None),
    }


# --------------------------------------------------------------------------- #
# ranking
# --------------------------------------------------------------------------- #
def rank(metrics: list[dict]) -> list[dict]:
    mx = max(m["cases"] * m["median_s"] for m in metrics)
    rows = []
    for m in metrics:
        f = roi.score(m, mx)
        rows.append({**m, **f.as_dict()})
    rows.sort(key=lambda r: -r["client_roi"])
    return rows


def split_conflated(metrics: list[dict]) -> list[dict]:
    """Robustness re-run: treat the conflated label as two processes.

    Only the case count changes -- both halves are worked on the same screen,
    with the same selectors, the same paste behaviour and the same documents,
    so every per-case measurement is inherited unchanged.  That is the point of
    the test: it isolates the effect of the frequency being halved.
    """
    out = []
    for m in metrics:
        if m["label"] != CONFLATED:
            out.append(dict(m))
            continue
        for name, share in CONFLATED_SPLIT.items():
            h = dict(m)
            h["label"] = name
            h["cases"] = round(m["cases"] * share)
            h["total_s"] = round(m["total_s"] * share, 1)
            h["degraded_cases"] = round(m["degraded_cases"] * share)
            # [A] the pay-change half writes to payroll and tax, the expense half
            # does not; sensitivity is scored per half rather than inherited.
            roi.SENSITIVITY.setdefault(name, 0.60 if "pay_change" in name else 0.45)
            out.append(h)
    return out


def drop_degraded(events, split_signal, worklist) -> list[dict]:
    """Robustness re-run: recompute everything with the extension-less session out."""
    segs = [s for s in load_segments(events) if s["session_id"] != DEGRADED_SESSION]
    by_label = collections.defaultdict(list)
    for s in segs:
        by_label[s["label"]].append(s)
    return [measure(L, ss, split_signal.get(L, 0.0), worklist)
            for L, ss in by_label.items()]


def drop_thin_worklist(metrics: list[dict], min_sessions: int = 3) -> list[dict]:
    """Robustness re-run: ignore the worklist 種別 channel where it rests on
    fewer than `min_sessions` sessions of OCR coverage."""
    out = []
    for m in metrics:
        c = dict(m)
        if c["worklist_variant_sessions"] < min_sessions:
            c["variant_rate"] = round(max(c["variant_marker_rate"],
                                          c["optional_step_signal"]), 3)
        out.append(c)
    return out


CSV_COLUMNS = [
    "rank", "label", "client_roi", "impact", "automatability", "client_feasibility",
    "build_fit",
    "cases", "sessions", "operators", "total_s", "median_s", "p90_s", "cv",
    "degraded_cases", "degraded_share",
    "repeatability", "copy_paste_ratio", "variant_rate", "judgment_step",
    "structured_target", "stable_selectors", "low_branching", "sensitivity",
    "loop_completeness", "evidence_density", "mock_fidelity", "selector_determinism",
    "pastes_per_case", "clipboard_events_per_case",
    "clip_chars_per_case", "typed_chars_per_case",
    "regulation_dwell_s_per_case", "reference_dwell_s_per_case",
    "unclassified_word_s_per_case",
    "excel_dwell_s_per_case", "mockable_dwell_share",
    "apps_touched", "apps_recurring", "reference_docs", "reference_docs_recurring",
    "integration_surface",
    "template_conformance", "row_click_rate", "note_field_rate", "commit_rate",
    "positional_row_target", "commit_selector", "modal_route", "route_purity",
    "variant_marker_field", "variant_marker_rate", "optional_step_signal",
    "worklist_variant_rate", "worklist_variant_sessions", "worklist_variant_rows",
]


def main() -> None:
    events = load_sessions("B")

    discovery_raw = json.load(open(DISCOVERY, encoding="utf-8"))
    # discovery_B.json is keyed by screen (system/route); map it onto labels.
    segs_all = load_segments(events)
    by_label = collections.defaultdict(list)
    for s in segs_all:
        by_label[s["label"]].append(s)

    screen_of_label: dict[str, str] = {}
    for L, ss in by_label.items():
        c: collections.Counter = collections.Counter()
        for s in ss:
            for e in s["_ev"]:
                url = e.get("nav_url") or e.get("tab_url")
                m = RE_PORTAL.search(url) if url else None
                if m:
                    c[m.group(0)] += 1
        if c:
            port, route = RE_PORTAL.search(c.most_common(1)[0][0]).groups()
            from common import PORT_SYSTEM
            screen_of_label[L] = f"{PORT_SYSTEM.get(port, port)}/{route}"
    split_signal = {L: discovery_raw["split_separation"].get(screen_of_label.get(L, ""), 0.0)
                    for L in by_label}

    worklist = worklist_variant_rates(events)
    metrics = [measure(L, ss, split_signal[L], worklist) for L, ss in by_label.items()]
    ranked = rank(metrics)

    os.makedirs(REPORTS, exist_ok=True)
    csv_path = os.path.join(REPORTS, "step2_process_metrics.csv")
    with open(csv_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for i, r in enumerate(ranked, 1):
            w.writerow({**{k: (round(v, 4) if isinstance(v, float) else v)
                           for k, v in r.items()}, "rank": i})

    ranked_split = rank(split_conflated(metrics))
    ranked_nodeg = rank(drop_degraded(events, split_signal, worklist))
    ranked_thin = rank(drop_thin_worklist(metrics))

    out = {
        "headline": {
            "processes": len(metrics),
            "cases": sum(m["cases"] for m in metrics),
            "sessions": len({s["session_id"] for s in segs_all}),
            "operators": len({e.get("machine") for evs in events.values() for e in evs} - {None}),
            "segmented_minutes": round(sum(m["total_s"] for m in metrics) / 60, 1),
        },
        "conflation_evidence": split_evidence(events),
        "ranking": ranked,
        "robustness_conflated_split": [
            {k: r[k] for k in ("label", "client_roi", "impact", "automatability",
                               "client_feasibility", "build_fit", "cases")}
            for r in ranked_split],
        "robustness_without_degraded_session": [
            {k: r[k] for k in ("label", "client_roi", "impact", "automatability",
                               "client_feasibility", "build_fit", "cases")}
            for r in ranked_nodeg],
        "robustness_without_thin_worklist_evidence": [
            {k: r[k] for k in ("label", "client_roi", "impact", "automatability",
                               "client_feasibility", "build_fit", "variant_rate")}
            for r in ranked_thin],
    }
    json_path = os.path.join(REPORTS, "step2_metrics.json")
    json.dump(out, open(json_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # ---- console summary ----
    h = out["headline"]
    print(f"dataset B: {h['cases']} cases, {h['processes']} processes, "
          f"{h['sessions']} sessions, {h['operators']} operators, "
          f"{h['segmented_minutes']} min segmented\n")
    print(f"{'#':>2} {'process':32s} {'ROI':>6s} {'Imp':>5s} {'Aut':>5s} {'Fea':>5s} "
          f"{'Fit':>5s} {'cases':>5s} {'med_s':>6s} {'var':>5s} {'judg':>5s} {'deg':>5s}")
    for i, r in enumerate(ranked, 1):
        print(f"{i:2d} {r['label']:32s} {r['client_roi']:6.4f} {r['impact']:5.2f} "
              f"{r['automatability']:5.2f} {r['client_feasibility']:5.2f} "
              f"{r['build_fit']:5.2f} {r['cases']:5d} {r['median_s']:6.1f} "
              f"{r['variant_rate']:5.2f} {r['judgment_step']:5.2f} {r['degraded_share']:5.2f}")

    print("\nrobustness -- conflated label split 50/50:")
    for i, r in enumerate(ranked_split[:5], 1):
        print(f"  {i}. {r['label']:34s} {r['client_roi']:.4f}")
    print("robustness -- extension-less session removed:")
    for i, r in enumerate(ranked_nodeg[:5], 1):
        print(f"  {i}. {r['label']:34s} {r['client_roi']:.4f}")
    print("robustness -- worklist 種別 channel dropped where <3 sessions of OCR:")
    for i, r in enumerate(ranked_thin[:5], 1):
        print(f"  {i}. {r['label']:34s} {r['client_roi']:.4f}")
    print(f"\nconflation evidence: {out['conflation_evidence']}")
    print(f"\nwrote {csv_path}\nwrote {json_path}")


if __name__ == "__main__":
    main()
