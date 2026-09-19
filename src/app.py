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

import html
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


# The only hand-written CSS in this file. It buys two things that Streamlit has no
# widget for: a counter you can click, and an exception queue compact enough to sit
# above the fold instead of below a 700px iframe.
UI_CSS = """
<style>
a.xq-jump{display:block; text-decoration:none !important; color:inherit;
  border:1px solid rgba(255,75,75,.40); border-radius:.5rem;
  background:rgba(255,75,75,.07); padding:.30rem .65rem .45rem; height:100%;}
a.xq-jump:hover{background:rgba(255,75,75,.16); border-color:rgba(255,75,75,.85);}
a.xq-jump .l,a.xq-jump .v,a.xq-jump .d{display:block;}
a.xq-jump .l{font-size:.875rem; color:rgba(49,51,63,.7); line-height:1.5;}
a.xq-jump .v{font-size:2.25rem; font-weight:600; line-height:1.15; color:inherit;}
a.xq-jump .d{font-size:.82rem; font-weight:600; color:#ff4b4b; line-height:1.3;}
a.xq-jump.quiet{border-color:rgba(49,51,63,.18); background:transparent;}
a.xq-jump.quiet .d{color:rgba(49,51,63,.55); font-weight:400;}

.xq{border-left:4px solid #ff4b4b; background:rgba(255,75,75,.06);
  border-radius:.25rem; padding:.45rem .7rem; margin-bottom:.4rem;}
.xq .h{display:flex; flex-wrap:wrap; gap:.45rem; align-items:baseline;}
.xq .id{font-family:monospace; font-weight:700; font-size:.95rem;}
.xq .row{font-size:.8rem; color:rgba(49,51,63,.7);}
.xq .code{font-family:monospace; font-size:.75rem; font-weight:700; color:#fff;
  background:#ff4b4b; border-radius:.25rem; padding:.05rem .35rem;}
.xq .stage{font-size:.75rem; color:rgba(49,51,63,.7);}
.xq .why{font-size:.86rem; margin:.2rem 0 .15rem;}
.xq .meta{font-size:.76rem; color:rgba(49,51,63,.65); font-family:monospace;}
.xq .bad{color:#c1121f; font-weight:700;}
</style>
"""


def queue_cards(queued_records: list[dict]) -> str:
    """The exception queue, as one HTML block.

    One card per refused case carrying everything a person needs in order to pick
    it up: which case, which worklist row, what the engine refused on, why in
    words, how many times it pressed commit, and whether a verify ever confirmed
    anything. Rendered as a single markdown call so the four cards sit together
    rather than four blocks apart.
    """
    out = []
    for r in queued_records:
        verified = {True: "yes", False: '<span class="bad">no</span>'}.get(
            r.get("verify_confirmed"), "\u2014 never reached")
        attempts = r.get("commit_attempts", 0)
        out.append(
            '<div class="xq">'
            f'<div class="h"><span class="id">{html.escape(str(r["case_id"]))}</span>'
            f'<span class="row">worklist row {html.escape(str(r["row"]))}</span>'
            f'<span class="code">{html.escape(str(r["code"] or "?"))}</span>'
            f'<span class="stage">refused at <b>{html.escape(str(r["stage"] or "?"))}'
            f'</b></span></div>'
            f'<div class="why">{html.escape(str(r["detail"] or ""))}</div>'
            f'<div class="meta">commit attempts <b>{attempts}</b> &middot; '
            f'verify confirmed <b>{verified}</b> &middot; '
            f'{html.escape(str(r.get("human_action", "")))} by '
            f'{html.escape(str(r.get("reviewed_by", "")))}</div>'
            '</div>'
        )
    return "".join(out)


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

st.markdown(UI_CSS, unsafe_allow_html=True)

c0, c1, c2, c3, c4 = st.columns(5)
c0.metric("IN WORKLIST", total)
c1.metric("AWAITING REVIEW", pending)
c2.metric("AUTOMATED", automated)
# QUEUED is the only counter that is a link, because it is the only one that stands
# for work somebody still has to do. It jumps to the list of exactly which cases.
# Spans, not divs, and on one line: Streamlit renders this through a markdown
# parser that closes an anchor around any block-level child, which turned the card
# into four separate links stacked on top of each other.
c3.markdown(
    f'<a class="xq-jump{"" if queued else " quiet"}" href="#exception-queue" '
    f'title="jump to the cases that could not be automated">'
    f'<span class="l">QUEUED FOR HUMAN</span>'
    f'<span class="v">{queued}</span>'
    f'<span class="d">'
    f'{f"{queued} need a person \u2014 see which \u25be" if queued else "none yet"}'
    f'</span></a>',
    unsafe_allow_html=True)
c4.metric("HANDS-ON TIME REMOVED", f"\u2248{pct:.0f}% (relative)" if processed else "\u2014")

# ---------------------------------------------------------------- exception queue
# Directly under the counter that points at it, NOT at the bottom of the page.
# "4 need a person" is the honest half of this prototype's result, so the four cases
# it refers to are named on the same screen as the number, with the reason each one
# was refused. Nothing here changes how a case is queued — this is the same audit
# record the engine wrote, read out in full.
st.subheader("\u2463 Exception queue \u2014 what stays manual",
             anchor="exception-queue")
queued_records = [r for r in records if r["outcome"] == "queued"]
if not queued_records:
    st.caption("Empty \u2014 nothing has been refused yet. Cases land here when the "
               "engine will not commit them, and each one is then a person\u2019s work.")
else:
    st.caption(f"{len(queued_records)} of the {processed} decided case(s) were **not** "
               f"automated. Each is charged the full manual cycle in the figure above, "
               f"because each still has to be done by hand.")
    st.markdown(queue_cards(queued_records), unsafe_allow_html=True)

# The honesty content, in one collapsed expander — not softened, not removed.
# Five labelled disclosures and the three numbers they qualify. Every figure quoted
# here is checkable: 11s/77 executions is the `fin_purchase_order_management` row of
# reports/step2_process_metrics.csv, and 872/872 null `text_content` is a count over
# dataset B's own clipboard_change events.
with st.expander("What’s real here / what’s mocked — click to read",
                 expanded=False):
    st.markdown(f"""
**[WORKING] The automation, end to end**  
Read → precheck → write → confirm → commit once → verify by re-reading the row.
Review loop, exception queue, audit log and time-saved figure all function.

**[MOCKED] The portal — but its structure is real**  
No client-system access, so the screen is a reconstruction. Its structure — columns,
field names, status vocabulary, note template, the
`#rt-table` / `#rt-note` / `#btn-rt-ok` selector contract — is recovered from dataset B.

**[MOCKED] The case values — synthetic by necessity**  
Dataset B logged clipboard *length*, never payload — `text_content` is null in all 872
events. Real values were never captured, so no method recovers them: a limit of the
data, correctly identified.

**[MANUAL] What stays human after deployment**  
Exceptions, flagged cases and the final sign-off. An uncertain case is stopped, never
forced through.

**Time saved — [MEASURED] baseline, [ASSUMPTION] mock clock**  
The {baseline_s:g}s manual cycle is measured: 77 observed executions in Step 2. The
mock’s own seconds are not the client’s, so the figure below is a relative demo
result, not a production ROI.
""")
    st.markdown(
        f"| | |\n|---|---|\n"
        f"| **Baseline** | {baseline_s:g}s median manual cycle "
        f"× {processed} case{'' if processed == 1 else 's'} |\n"
        f"| **Demo result** | {automated} automated + {queued} human exception"
        f"{'' if queued == 1 else 's'} |\n"
        f"| **Relative time saved** | ≈{pct:.0f}% |"
        if processed else
        "| | |\n|---|---|\n"
        f"| **Baseline** | {baseline_s:g}s median manual cycle |\n"
        "| **Demo result** | — nothing decided yet |\n"
        "| **Relative time saved** | — |"
    )

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

# THE PORTAL IS DRAWN FIRST, before the left column, and that ordering is the fix
# for the frame that only refreshed on the first case.
#
# `dispatch()` runs the engine SYNCHRONOUSLY inside the left column and blocks this
# script for the whole run. Streamlit paints elements in the order the script
# produces them, so while the old ordering was left-then-right the frame on screen
# during a run was the one left over from the PREVIOUS rerun — stale, greyed out,
# and in the batch case never repainted until all fourteen cases were finished.
# Emitting it before the block means the frame the reviewer watches is live for the
# whole run; the page inside it then keeps itself current off /api/rev, so every
# commit lands on screen as it happens, one row at a time, with no manual reload.
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

    # The ?v= is a cache-buster, not decoration. Streamlit keeps an iframe whose src
    # is byte-identical mounted across reruns, which is usually what you want — but
    # it also means a frame that somehow missed a live update would keep showing the
    # snapshot it took at first render for the rest of the session. Tying the src to
    # the worklist and to how many cases have been decided guarantees a genuine
    # re-fetch whenever this dashboard's own view of the portal has moved, and
    # guarantees nothing more often than that, so there is no reload flicker.
    embed_url = (base_url.rstrip("/")
                 + f"/?embed=1&v={portal_epoch or 'none'}-{len(records)}")
    components.iframe(embed_url, height=700, scrolling=True)
    st.caption("This frame re-reads the portal whenever the portal’s state changes "
               "— it is not a snapshot.")

    st.divider()
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
