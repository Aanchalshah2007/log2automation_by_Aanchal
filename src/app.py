"""Step-3 review UI — the human-in-the-loop surface, and the demo surface.

    streamlit run src/app.py

Shows every pending case with a per-field source tag, gives the reviewer three
functional actions (approve / edit-then-approve / flag), runs the deterministic
engine against the mock portal, and keeps the counters that matter honest:
how many cases were automated, how many were handed back to a human, and how much
hands-on time that removed — as a ratio, never as hours.

Nothing in this file calls a model either. The reviewer decides; the engine executes.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import streamlit as st
import streamlit.components.v1 as components

REPO = pathlib.Path(__file__).resolve().parents[1]
DEFS = REPO / "src" / "automation" / "definitions"
BUILD = REPO / "build"
AUDIT = BUILD / "audit_log.jsonl"
JOBS = BUILD / "jobs.json"

st.set_page_config(page_title="発注管理 — automation review", layout="wide")


# ---------------------------------------------------------------- helpers
def load_definitions() -> dict[str, dict]:
    out = {}
    for p in sorted(DEFS.glob("*.json")):
        try:
            out[p.name] = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            st.error(f"{p.name}: {exc}")
    return out


def portal_state(base_url: str) -> dict | None:
    try:
        with urllib.request.urlopen(base_url.rstrip("/") + "/api/state", timeout=3) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return None


def portal_reset(base_url: str, n: int) -> dict | None:
    """Reseed the ACTUAL portal server and read the result back from it.

    This is a POST to the portal's own reset endpoint followed by a fresh GET of its
    state — it resets the process that owns the rows, and then confirms what that
    process now holds. It never touches Streamlit's own variables; those are dropped
    separately by rebind() once the new epoch is observed.
    """
    body = json.dumps({"cases": n}).encode()
    req = urllib.request.Request(base_url.rstrip("/") + "/api/reset", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        ack = json.loads(urllib.request.urlopen(req, timeout=5).read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return None
    after = portal_state(base_url)          # read it back from the portal itself
    if after is None:
        return None
    return {"epoch": after.get("epoch", ""),
            "server_id": after.get("server_id", ""),
            "pid": after.get("pid"),
            "cases": len(after.get("cases", [])),
            "committable": sum(1 for c in after.get("cases", [])
                               if c["row_cells"]["status"] == "未処理"),
            "ack_server_id": ack.get("server_id", "")}


def run_engine(defn_file: str, jobs: list[dict], log_box,
               expect_server: str = "", base_url: str = "") -> str:
    """Run the engine as a subprocess, stream its progress into `log_box`, and
    return the run_id it reported.

    The engine is a separate process on purpose: it is the deliverable, this UI
    is a client of it, and it has to be runnable headless from a scheduler with
    no Streamlit anywhere in sight.
    """
    JOBS.parent.mkdir(parents=True, exist_ok=True)
    JOBS.write_text(json.dumps(jobs, ensure_ascii=False), encoding="utf-8")

    # EVERY path here is a separate LIST ELEMENT and shell=False. Nothing is ever
    # f-strung into one command string, because this repository lives under
    # "C:\Users\Aanchal Shah\..." and any string-joined command line splits at that
    # space. sys.executable — not "python" — so the child is the same interpreter
    # Streamlit is running on, with the same packages.
    cmd = [sys.executable,
           str((REPO / "src" / "automation" / "engine.py").resolve()),
           "--definition", str((DEFS / defn_file).resolve()),
           "--jobs", str(JOBS.resolve()),
           "--audit", str(AUDIT.resolve())]
    if base_url:
        # Drive the portal THIS UI is reading, not whatever the definition's
        # target.base_url happens to say.
        cmd += ["--base-url", base_url]
    if expect_server:
        # The engine abandons the run rather than write to a portal this UI is not
        # the one reviewing. Two portals once shared 127.0.0.1:5233 (build notes §5c).
        cmd += ["--expect-server", expect_server]

    lines: list[str] = []
    run_id = ""
    proc = subprocess.Popen(cmd, shell=False,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace",
                            bufsize=1, cwd=str(REPO.resolve()))

    # Drain stderr on its own thread.
    #
    # THIS IS THE FIX FOR THE BUG THAT MADE EVERY CASE FAIL. Reading stdout to
    # completion first and only then calling proc.stderr.read() deadlocks the moment
    # the child writes more than one pipe buffer (65536 bytes on this kernel) to
    # stderr: the child blocks in write(), so it stops producing stdout, so the
    # parent blocks in its stdout loop, so nobody ever drains stderr. Chromium
    # under WSL reaches 64 KB of stderr easily — Fontconfig, dbus and GPU warnings.
    # The engine would emit run_start, write the note for no case, and hang; the UI
    # saw no audit records at all. Reproduced deterministically in a 20-line probe.
    err_chunks: list[str] = []

    def _drain_stderr() -> None:
        if proc.stderr is None:
            return
        for line in proc.stderr:
            err_chunks.append(line)

    err_thread = threading.Thread(target=_drain_stderr, daemon=True)
    err_thread.start()

    STEP_LABEL = {
        "read_row": "reading worklist row",
        "open_row": "opening the case",
        "read_detail": "reading the detail pane",
        "apply_edits": "applying the reviewer's correction",
        "precheck": "checking the case against the definition",
        "write_note": "writing the note into #rt-note",
        "confirming_note": "re-reading the note field…",
        "note_confirmed": "✓ note confirmed in the DOM",
        "commit": "committing (once, no retry)",
        "verifying": "verifying… re-reading the row's ステータス",
    }

    assert proc.stdout is not None
    for raw in proc.stdout:
        raw = raw.strip()
        if not raw:
            continue
        try:
            ev = json.loads(raw)
        except json.JSONDecodeError:
            continue

        if ev["ev"] == "run_start":
            run_id = ev["run_id"]
            lines.append(f"_run `{run_id}` · definition `{ev['definition']}` "
                         f"v{ev['definition_version']} · {ev['n']} case(s) · "
                         f"LLM in runtime: **{ev['llm_in_runtime']}**_")
        elif ev["ev"] == "portal_identity":
            lines.append(f"&nbsp;&nbsp;_portal `{ev['portal_server_id']}` "
                         f"epoch `{ev['portal_epoch']}` at {ev['url']}_")
        elif ev["ev"] == "step":
            label = STEP_LABEL.get(ev["step"], ev["step"])
            extra = f" — `{ev['detail']}`" if ev.get("detail") else ""
            lines.append(f"&nbsp;&nbsp;`{ev['case_id']}`  {label}{extra}")
        elif ev["ev"] == "case_start":
            lines.append(f"**{ev['case_id']}** (row {ev['row']}, {ev['action']})")
        elif ev["ev"] == "case_done":
            if ev["outcome"] == "automated":
                lines.append(f"&nbsp;&nbsp;:green[**✓ {ev.get('status_after')} confirmed**] "
                             f"— {ev.get('detail','')}")
            else:
                lines.append(f"&nbsp;&nbsp;:red[**→ exception queue · {ev['code']}**] "
                             f"— {ev.get('detail','')}")
        elif ev["ev"] == "run_end":
            lines.append(f"_run finished — {ev['automated']} automated, "
                         f"{ev['queued']} queued_")

        log_box.markdown("\n\n".join(lines[-26:]))

    proc.wait()
    err_thread.join(timeout=5)
    err = "".join(err_chunks)
    if proc.returncode != 0:
        st.error(f"The automation engine exited with code {proc.returncode} and "
                 f"processed nothing. No case was marked handled.\n\n"
                 f"```\n{err[-2500:]}\n```")
    elif not run_id:
        st.error("The automation engine produced no run — nothing was written to the "
                 "portal and no case was marked handled.\n\n"
                 f"```\n{err[-2500:]}\n```")
    ss.last_log = "\n\n".join(lines)
    return run_id


def read_audit(*, run_id: str = "", portal_epoch: str = "") -> list[dict]:
    """Audit records, filtered by run or by the portal worklist they were written
    against. The log is append-only and outlives every browser session."""
    if not AUDIT.exists() or not (run_id or portal_epoch):
        return []
    out = []
    for line in AUDIT.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if run_id and r.get("run_id") != run_id:
            continue
        if portal_epoch and r.get("portal_epoch") != portal_epoch:
            continue
        out.append(r)
    return out


def dispatch(defn_file: str, jobs: list[dict], log_box,
             expect_server: str = "", base_url: str = "") -> None:
    """Run the jobs and fold the resulting audit records into the session.

    A case counts as handled only if the engine actually returned a record for it.
    The previous version marked every dispatched case handled unconditionally, so a
    run that died on startup made 18 cases vanish from the dashboard while the portal
    still held them — the state desync in build notes §5.2. The audit log is the one
    source of truth about what happened to a case; this function no longer guesses.
    """
    run_id = run_engine(defn_file, jobs, log_box, expect_server, base_url)
    got = read_audit(run_id=run_id)
    # Re-derive the whole decided set from the log for the worklist the portal is
    # currently serving, rather than appending to a session-local list. A browser
    # reload therefore cannot forget work already done to this worklist and offer
    # an already-committed case for approval again.
    ss.records = read_audit(portal_epoch=ss.epoch) if ss.epoch else got
    missing = {j["case_id"] for j in jobs} - {r["case_id"] for r in got}
    if missing:
        st.warning(f"{len(missing)} case(s) came back with no result and were left "
                   f"pending: {', '.join(sorted(missing))}")


# ---------------------------------------------------------------- state
#
# ONE SOURCE OF TRUTH, in two halves that cannot drift apart:
#   * the PORTAL owns the cases and their statuses. Nothing is cached here.
#   * the AUDIT LOG owns what happened to each case. `ss.records` holds this
#     demo's slice of it, and `decided()` derives everything else from it.
#
# There is deliberately no separate "handled" set any more. The old one was a
# third opinion that could disagree with both, and did: a run that failed on
# startup added 18 ids to it while producing no records, so the dashboard showed
# an empty system while the portal still held 18 未処理 cases. Counters are now
# computed from state on every rerun and are never carried across one.
ss = st.session_state
ss.setdefault("records", [])        # audit records produced in this demo
ss.setdefault("epoch", None)        # the portal worklist this demo is bound to
ss.setdefault("editing", None)
ss.setdefault("shown_at", {})
ss.setdefault("edits", {})
ss.setdefault("last_log", "")
ss.setdefault("reset_note", "")


def decided() -> dict[str, dict]:
    """case_id -> the latest audit record for it in this demo."""
    out: dict[str, dict] = {}
    for r in ss.records:
        out[r["case_id"]] = r
    return out


def rebind(epoch: str) -> None:
    """Bind this session to a worklist and drop everything from the previous one.

    Called whenever the portal's epoch differs from ours — which covers pressing
    Reset in the sidebar, restarting server.py in a terminal, and reconnecting a
    browser tab to a portal that was reseeded while the tab was closed.
    """
    ss.epoch = epoch
    # The audit log — not session memory — says what has happened to this worklist.
    ss.records = read_audit(portal_epoch=epoch) if epoch else []
    ss.editing = None
    ss.shown_at = {}
    ss.edits = {}
    ss.last_log = ""


# ---------------------------------------------------------------- sidebar
definitions = load_definitions()
active = {k: v for k, v in definitions.items() if v.get("state") == "active"}
stubs = {k: v for k, v in definitions.items() if v.get("state") != "active"}

with st.sidebar:
    st.markdown("### Process definition")
    if not active:
        st.error("no active definition found in src/automation/definitions/")
        st.stop()
    defn_file = st.selectbox("active", list(active), index=0,
                             format_func=lambda k: active[k]["screen_name"] + f"  ({k})")
    defn = active[defn_file]
    st.caption(f"`{defn['definition_id']}` v{defn['definition_version']}")

    st.markdown(
        f"**selector prefix contract**\n\n"
        f"- row `{defn['selectors']['row_open'].format(n='N')}`\n"
        f"- note `{defn['selectors']['note']}`\n"
        f"- commit `{defn['selectors']['commit']}`\n"
    )

    if stubs:
        st.markdown("### Also defined")
        for name, s in stubs.items():
            st.caption(f"`{name}` — **{s.get('state')}**. {s['screen_name']}. "
                       f"Adding it is this file plus a mock, not new engine code; "
                       f"the engine refuses to run a stub.")

    st.divider()
    base_url = st.text_input("mock portal", defn["target"]["base_url"])
    n_seed = st.number_input("cases to seed on reset", 5, 60, 18)
    if st.button("RESET DEMO", use_container_width=True, type="secondary"):
        res = portal_reset(base_url, int(n_seed))
        if res:
            rebind(res["epoch"])   # the portal reseeded; bind to the new worklist
            ss.reset_note = (f"Portal `{res['server_id']}` (pid {res['pid']}) reseeded: "
                             f"{res['cases']} cases, {res['committable']} in 未処理.")
            st.rerun()
        else:
            st.error("portal is not answering — start it first (see README)")

    if ss.reset_note:
        st.caption(ss.reset_note)

    st.divider()
    st.caption("No LLM runs anywhere in this prototype. "
               "The engine is deterministic and config-driven; the judgment is the "
               "reviewer's. See reports/step3_build_notes.md.")


# ---------------------------------------------------------------- header
st.title("発注管理 — human-in-the-loop automation")
st.caption("You approve a case · a deterministic script fills the portal and verifies the "
           "write · anything it cannot verify goes to a human. No AI model at runtime.")

state = portal_state(base_url)
if state is None:
    st.error(
        f"The mock portal at {base_url} is not running.\n\n"
        "```bash\npython3 src/mock_portal/server.py --port 5233\n```"
    )
    st.stop()

# Bind to the worklist the portal is actually serving. If it has been reseeded —
# by the RESET button, or by someone restarting server.py in a terminal — this
# session's records belong to a worklist that no longer exists, so they go. This
# is the check that makes "the dashboard is empty but the portal has 18 cases"
# impossible rather than merely unlikely.
portal_epoch = state.get("epoch", "")
portal_server_id = state.get("server_id", "")
if ss.epoch != portal_epoch:
    stale = bool(ss.records)
    rebind(portal_epoch)
    if stale:
        st.info("The portal was reseeded, so this dashboard reloaded from it. "
                "Counters below are for the worklist the portal is holding now.")

# ---------------------------------------------------------------- counters
# DERIVED, on this rerun, from two authoritative sources and nothing else:
#   * the PORTAL's live state  -> which cases exist and what status each row holds
#   * the AUDIT LOG            -> what the automation attempted and what happened
# No counter is ever incremented or decremented. `automated` additionally requires
# the portal to AGREE that the row reached its committed status, so an audit record
# alone can never inflate it.
cases = state["cases"]
status_now = {c["case_id"]: c["row_cells"]["status"] for c in cases}
committed_status = defn["row_schema"]["status"]["expect_after_commit"]
committable_from = defn["row_schema"]["status"]["commit_allowed_from"]

verdicts = decided()
total = len(cases)

automated_ids = {
    cid for cid, r in verdicts.items()
    if r["outcome"] == "automated" and status_now.get(cid) == committed_status
}
queued_ids = {cid for cid, r in verdicts.items() if r["outcome"] == "queued"}
# An audit record claiming success that the portal does not corroborate is a real
# disagreement, not a counter to quietly round off. It is surfaced, never hidden.
disputed_ids = {
    cid for cid, r in verdicts.items()
    if r["outcome"] == "automated" and cid not in automated_ids
}
decided_ids = automated_ids | queued_ids | disputed_ids
pending_cases = [c for c in cases if c["case_id"] not in decided_ids]

records = ss.records
automated = len(automated_ids)
queued = len(queued_ids)
pending = len(pending_cases)
processed = automated + queued + len(disputed_ids)
committable = sum(1 for c in cases if c["row_cells"]["status"] in committable_from)

if disputed_ids:
    st.error(
        f"**State disagreement.** {len(disputed_ids)} case(s) are recorded as automated "
        f"in the audit log but the portal does not show them as {committed_status}: "
        f"{', '.join(sorted(disputed_ids))}. They are counted as neither automated nor "
        f"queued. This usually means the engine drove a different portal process than "
        f"this dashboard is reading."
    )

# The invariant, checked every redraw and shown rather than asserted away.
if total != pending + automated + queued + len(disputed_ids):
    st.error(
        f"**Counter invariant violated**: worklist {total} != awaiting {pending} + "
        f"automated {automated} + queued {queued} + disputed {len(disputed_ids)}. "
        f"The numbers below are not trustworthy; press RESET DEMO."
    )

baseline_s = float(defn["baseline"]["median_manual_cycle_s"])
auto_s = sum(r.get("automation_seconds", 0.0) for r in records)
review_s = sum(r.get("review_seconds", 0.0) for r in records)

# A queued case saves nothing. The reviewer's time was still spent on it AND the
# whole manual cycle still has to happen afterwards. Charging it the full manual
# cycle is what makes the exception count cost something in this number.
before_s = baseline_s * processed
after_s = (
    sum(verdicts[cid].get("automation_seconds", 0.0)
        + verdicts[cid].get("review_seconds", 0.0) for cid in automated_ids)
    + sum(verdicts[cid].get("review_seconds", 0.0) + baseline_s
          for cid in queued_ids | disputed_ids)
)
pct = (1 - after_s / before_s) * 100 if before_s else 0.0

c0, c1, c2, c3, c4 = st.columns(5)
c0.metric("IN WORKLIST", total)
c1.metric("AWAITING REVIEW", pending)
c2.metric("AUTOMATED", automated)
c3.metric("QUEUED FOR HUMAN", queued,
          delta=None if not queued else f"{queued} need a person",
          delta_color="inverse")
c4.metric("HANDS-ON TIME REMOVED", f"\u2248{pct:.0f}% (relative)" if processed else "\u2014")

# The honesty content, compressed into one collapsed expander — not softened, not
# removed. The MOCK notice, the real/mocked/synthetic table, the MEASURED vs
# ASSUMPTION tags and the full relative-ROI basis are all still here, one click away.
with st.expander("What\u2019s real here / what\u2019s mocked \u2014 click to read",
                 expanded=False):
    st.markdown("""
| | |
|---|---|
| **Genuinely works end to end** | the engine (read \u2192 precheck \u2192 write note \u2192 **confirm the note landed** \u2192 commit once \u2192 **verify by reading the row back**), the approve / edit / flag loop, the exception queue, the audit log, the relative time-saved figure |
| **[MOCKED]** | the portal itself. There is no access to the client\u2019s system. The *structure* \u2014 columns, field names, status vocabulary, note template, the `#rt-table` / `#rt-note` / `#btn-rt-ok` selector contract \u2014 is **[MEASURED]**, recovered from dataset B\u2019s logs. |
| **[MOCKED] Synthetic values** | every case value on screen is invented. The real values were never logged: clipboard events carry a length, not a payload. |
| **Still manual after deployment** | everything in the exception queue, every flagged case, and the final sign-off on whether a queued case should be forced through |
| **[ASSUMPTION] Designed, not observed** | the whole failure branch. Dataset B has 684 cases and **0 failures** (step 2 \u00a77.5), so the portal\u2019s real error behaviour is unknown. The rule is: commit once, verify, and stop. |

**Four of the eighteen seeded cases are deliberately unautomatable** and must end up in
the exception queue rather than in the portal. That number is the point of the demo, not
a defect.
""")
    st.markdown(
        f"**Time-saved basis \u2014 relative, never absolute.** "
        f"before = median manual cycle **{baseline_s:g}s** \u00d7 {processed} cases "
        f"(**[MEASURED]**: `reports/step2_process_metrics.csv`, 77 observed executions). "
        f"after = automated cases at (engine {auto_s:.1f}s + review {review_s:.1f}s) "
        f"+ queued cases charged the full manual cycle, because a queued case still has "
        f"to be done by hand \u2014 which is why exceptions cost something here. "
        f"The {baseline_s:g}s baseline comes from a test-environment recording whose dwell "
        f"is \u22481.4\u00d7 compressed, and this mock\u2019s own seconds are not on that "
        f"clock at all. The two distortions push in opposite directions and neither is "
        f"invertible, so this is a demo figure: **do not multiply it by a headcount or an "
        f"hourly rate.**"
    )
    st.caption(f"{total} in the worklist = {pending} awaiting review + {automated} "
               f"automated + {queued} queued \u2014 recomputed from the portal\u2019s own "
               f"state and this run\u2019s audit log on every redraw. "
               f"`automated` additionally requires the portal to show "
               f"{committed_status}. Authoritative portal: `{portal_server_id}` "
               f"epoch `{portal_epoch}` at {base_url} \u00b7 {committable} row(s) "
               f"currently committable.")

if processed and pct < 0:
    st.caption("Negative because the cases handled so far are mostly exceptions \u2014 "
               "a reviewed-then-queued case costs review time *and* still has to be "
               "done by hand.")

st.divider()

# ---------------------------------------------------------------- queue
# "Pending" means "this demo has not decided about it yet" — NOT "the row is 未処理".
# One seeded row starts in 完了 and must still be reviewed and then refused by the
# engine, so status is the engine's business, not the queue's.
left, right = st.columns([0.88, 1.12], gap="large")

with left:
    st.subheader("① The case you are reviewing")
    st.caption(f"{pending} of {total} left · every value below is read live from the "
               f"portal's DOM (see `source`)")

    log_box = st.empty()

    # PART E GUARD — read from the LIVE portal, not from any session variable.
    # A portal whose rows are all committed cannot produce a legitimate demo: every
    # job would be refused with STATUS_NOT_COMMITTABLE and the run would report
    # "0 automated, 18 queued, negative saving". That is a spent portal, not a result,
    # so the engine is not launched at all.
    if committable == 0:
        st.warning("Nothing committable — press RESET DEMO first")
        st.caption(f"The portal at {base_url} holds {total} rows and none is in "
                   f"{'/'.join(committable_from)}. Server `{portal_server_id}`.")

    if not pending_cases:
        st.success("Every case in the worklist has been decided. "
                   "Press **RESET DEMO** in the sidebar to run it again.")

    if pending_cases and committable > 0:
        case = pending_cases[0]
        cid = case["case_id"]
        ss.shown_at.setdefault(cid, time.time())

        st.markdown(
            f"#### `{cid}` — worklist row {case['row']}\n"
            f"{case['detail']['name'] or '—'} · {case['row_cells']['kubun']} · "
            f"{case['row_cells']['amount']} · currently **{case['row_cells']['status']}**"
        )

        detail = dict(case["detail"])
        overrides = ss.edits.get(cid, {})
        editing = ss.editing == cid

        # per-field source tags
        rows = []
        for field, rule in defn["field_schema"].items():
            value = overrides.get(field, detail.get(field, ""))
            rows.append({
                "field": field,
                "value": value or "—",
                "source": rule.get("source", "?"),
                "edited": "corrected" if field in overrides else "",
            })
        for col, idx in defn["row_columns"].items():
            if col in ("shubetsu", "status"):
                rows.append({
                    "field": f"{col} (row)",
                    "value": case["row_cells"][col],
                    "source": f"worklist row (DOM, td:nth-of-type({idx}))",
                    "edited": "",
                })
        composed_src = {**detail, **overrides}
        try:
            preview = defn["write"]["template"].format(**composed_src)
        except (KeyError, IndexError):
            preview = "(cannot compose — a template field is missing)"
        st.markdown("**Will be written to `#rt-note`** &nbsp; "
                    "<span style='color:#6b7684'>the only composed value: "
                    "`reason` in a fixed template</span>", unsafe_allow_html=True)
        st.code(preview, language=None)

        if editing:
            st.markdown("**Correct a field** — what you type here is what commits.")
            with st.form(f"edit_{cid}"):
                new = {}
                for field in defn["field_schema"]:
                    val = st.text_input(field, overrides.get(field, detail.get(field, "")))
                    if val != detail.get(field, ""):
                        new[field] = val
                cols = st.columns(2)
                if cols[0].form_submit_button("Save correction & approve",
                                              type="primary", use_container_width=True):
                    ss.edits[cid] = new
                    ss.editing = None
                    job = {"case_id": cid, "row": case["row"], "action": "approve",
                           "overrides": new, "reviewed_by": "reviewer",
                           "review_seconds": round(time.time() - ss.shown_at[cid], 2)}
                    dispatch(defn_file, [job], log_box, portal_server_id, base_url)
                    st.rerun()
                if cols[1].form_submit_button("Cancel", use_container_width=True):
                    ss.editing = None
                    st.rerun()
        else:
            st.subheader("② Your decision")
            st.caption("Nothing is written until you press one. "
                       "EDIT corrects a value first — the corrected value is what commits.")
            b1, b2, b3 = st.columns(3)
            if b1.button("APPROVE", type="primary", use_container_width=True,
                         key=f"ap_{cid}"):
                job = {"case_id": cid, "row": case["row"], "action": "approve",
                       "overrides": overrides, "reviewed_by": "reviewer",
                       "review_seconds": round(time.time() - ss.shown_at[cid], 2)}
                dispatch(defn_file, [job], log_box, portal_server_id, base_url)
                st.rerun()
            if b2.button("EDIT", use_container_width=True, key=f"ed_{cid}"):
                ss.editing = cid
                st.rerun()
            if b3.button("FLAG", use_container_width=True, key=f"fl_{cid}"):
                job = {"case_id": cid, "row": case["row"], "action": "flag",
                       "flag_reason": "flagged by the reviewer — not automated",
                       "reviewed_by": "reviewer",
                       "review_seconds": round(time.time() - ss.shown_at[cid], 2)}
                dispatch(defn_file, [job], log_box, portal_server_id, base_url)
                st.rerun()

        st.caption("Every field, and where it was read from")
        st.dataframe(rows, use_container_width=True, hide_index=True)


    st.divider()
    # The batch covers everything still undecided, including the case on screen.
    rest = list(pending_cases)
    if rest:
        if st.button(f"▶ Run remaining {len(rest)} as batch", use_container_width=True,
                     disabled=committable == 0):
            jobs = [{"case_id": c["case_id"], "row": c["row"], "action": "approve",
                     "overrides": {}, "reviewed_by": "batch", "review_seconds": 0.0}
                    for c in rest]
            dispatch(defn_file, jobs, log_box, portal_server_id, base_url)
            st.rerun()
        st.caption("Batch cases get no individual review, so they cost 0 review seconds.")

    if ss.last_log:
        st.markdown("##### Engine trace")
        st.caption("Every step the script took, as it reported it.")
        with st.container(height=260):
            st.markdown(ss.last_log)

with right:
    st.subheader("③ The portal, live")
    if pending_cases:
        st.caption(f"← the engine fills this portal now · **watch row "
                   f"{pending_cases[0]['row']}** flip 未処理 → 登録済み")
    else:
        st.caption("← the live portal the engine drove · synthetic values, measured structure")

    # "Did the portal actually change?" — answered by pointing at the row, not by prose.
    last = ss.records[-1] if ss.records else None
    if last and last["outcome"] == "automated":
        st.success(f"**Row {last['row']} changed: {last['status_before']} → "
                   f"{last['status_after']}**, confirmed by reading the row back.")
    elif last and last["outcome"] == "queued":
        st.warning(f"**Row {last['row']} did not change — correct.** Stopped at "
                   f"*{last['stage']}* (`{last['code']}`), "
                   f"{last['commit_attempts']} commit attempt(s).")

    components.iframe(base_url.rstrip("/") + "/?embed=1", height=700, scrolling=True)


    st.divider()
    st.subheader("④ Exception queue")
    q = [r for r in records if r["outcome"] == "queued"]
    st.caption("Empty — nothing was refused yet." if not q else
               f"{len(q)} case(s) not automated · each one is now manual work.")
    for r in q:
        st.error(f"**{r['case_id']}** (row {r['row']}) · `{r['code']}` (at *{r['stage']}*)\n\n"
                 f"{r['detail']}\n\n"
                 f"commit attempts: **{r['commit_attempts']}** · "
                 f"verify confirmed: **{r['verify_confirmed']}**")

    st.subheader("Automated")
    a = [r for r in records if r["outcome"] == "automated"]
    if not a:
        st.caption("None yet.")
    else:
        st.dataframe(
            [{"case": r["case_id"],
              "status": f"{r['status_before']} → {r['status_after']}",
              "verified": "✓" if r["verify_confirmed"] else "✗",
              "edited": ", ".join(r["edits"]) or "—",
              "engine s": r["automation_seconds"]} for r in a],
            use_container_width=True, hide_index=True)

# ---------------------------------------------------------------- audit
st.divider()
st.subheader("Audit log")
st.caption("One record per case — read, edited, written, committed, verified, timed.")
if records:
    st.dataframe(
        [{"time": time.strftime("%H:%M:%S", time.localtime(r["started_at"])),
          "case": r["case_id"],
          "action": r["human_action"],
          "outcome": r["outcome"],
          "code": r["code"],
          "commits": r["commit_attempts"],
          "verified": r["verify_confirmed"],
          "status": f"{r['status_before']} → {r['status_after']}",
          "edits": json.dumps(r["edits"], ensure_ascii=False) if r["edits"] else "",
          "wrote": (r["written"] or "")[:60],
          "review s": r["review_seconds"],
          "engine s": r["automation_seconds"],
          "definition": f"{r['definition_id']} v{r['definition_version']}"}
         for r in records],
        use_container_width=True, hide_index=True)
    st.download_button("Download full audit log (JSONL)",
                       "\n".join(json.dumps(r, ensure_ascii=False) for r in records),
                       file_name="audit_log.jsonl")
else:
    st.caption("Nothing yet.")
