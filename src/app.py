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
import time
import urllib.error
import urllib.request

import streamlit as st

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


def portal_reset(base_url: str, n: int) -> bool:
    body = json.dumps({"cases": n}).encode()
    req = urllib.request.Request(base_url.rstrip("/") + "/api/reset", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=5).read()
        return True
    except (urllib.error.URLError, OSError):
        return False


def run_engine(defn_file: str, jobs: list[dict], log_box) -> str:
    """Run the engine as a subprocess, stream its progress into `log_box`, and
    return the run_id it reported.

    The engine is a separate process on purpose: it is the deliverable, this UI
    is a client of it, and it has to be runnable headless from a scheduler with
    no Streamlit anywhere in sight.
    """
    JOBS.parent.mkdir(parents=True, exist_ok=True)
    JOBS.write_text(json.dumps(jobs, ensure_ascii=False), encoding="utf-8")

    cmd = [sys.executable, str(REPO / "src" / "automation" / "engine.py"),
           "--definition", str(DEFS / defn_file),
           "--jobs", str(JOBS),
           "--audit", str(AUDIT)]

    lines: list[str] = []
    run_id = ""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", bufsize=1, cwd=str(REPO))

    STEP_LABEL = {
        "read_row": "reading worklist row",
        "open_row": "opening the case",
        "read_detail": "reading the detail pane",
        "apply_edits": "applying the reviewer's correction",
        "precheck": "checking the case against the definition",
        "write_note": "writing the note",
        "wrote": "wrote",
        "commit": "committing (once, no retry)",
        "verifying": "verifying…",
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

    err = (proc.stderr.read() if proc.stderr else "") or ""
    proc.wait()
    if proc.returncode != 0:
        st.error(f"engine exited {proc.returncode}\n\n```\n{err[-2500:]}\n```")
    ss.last_log = "\n\n".join(lines)
    return run_id


def read_audit(run_id: str) -> list[dict]:
    """The audit records this run wrote, in order. The log itself is append-only
    and outlives the session, so it is always filtered by run_id."""
    if not AUDIT.exists() or not run_id:
        return []
    out = []
    for line in AUDIT.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("run_id") == run_id:
            out.append(r)
    return out


def dispatch(defn_file: str, jobs: list[dict], log_box) -> None:
    """Run the jobs, fold the resulting audit records into the session, and mark
    the cases handled."""
    run_id = run_engine(defn_file, jobs, log_box)
    ss.records += read_audit(run_id)
    ss.handled |= {j["case_id"] for j in jobs}


# ---------------------------------------------------------------- state
ss = st.session_state
ss.setdefault("records", [])        # audit records produced in this session
ss.setdefault("handled", set())     # case_ids already sent to the engine
ss.setdefault("editing", None)
ss.setdefault("shown_at", {})
ss.setdefault("edits", {})
ss.setdefault("last_log", "")


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
    if st.button("Reset portal & session", use_container_width=True):
        if portal_reset(base_url, int(n_seed)):
            ss.records, ss.handled, ss.editing = [], set(), None
            ss.shown_at, ss.edits = {}, {}
            st.rerun()
        else:
            st.error("portal is not answering — start it first (see README)")

    st.divider()
    st.caption("No LLM runs anywhere in this prototype. "
               "The engine is deterministic and config-driven; the judgment is the "
               "reviewer's. See reports/step3_build_notes.md.")


# ---------------------------------------------------------------- header
st.title("発注管理 — human-in-the-loop automation")

state = portal_state(base_url)
if state is None:
    st.error(
        f"The mock portal at {base_url} is not running.\n\n"
        "```bash\npython3 src/mock_portal/server.py --port 5233\n```"
    )
    st.stop()

with st.expander("What is real here, and what is not — read this first", expanded=False):
    st.markdown(f"""
| | |
|---|---|
| **Genuinely works end to end** | the engine (read → precheck → write → commit once → **verify by read-back**), the approve / edit / flag loop, the exception queue, the audit log, the relative time-saved figure |
| **Mocked** | the portal itself. There is no access to the client's system. The *structure* — columns, field names, status vocabulary, note template, the `#rt-table` / `#rt-note` / `#btn-rt-ok` selector contract — is recovered from dataset B's logs. |
| **Synthetic** | every case value on screen. The real values were never logged: clipboard events carry a length, not a payload. |
| **Still manual after deployment** | everything in the exception queue, every flagged case, and the final sign-off on whether a queued case should be forced through |
| **Designed, not observed** | the whole failure branch. Dataset B has 684 cases and 0 failures (step 2 §7.5), so the portal's real error behaviour is unknown. The rule is: commit once, verify, and stop. |
""")

# ---------------------------------------------------------------- counters
records = ss.records
processed = len(records)
automated = sum(1 for r in records if r["outcome"] == "automated")
queued = sum(1 for r in records if r["outcome"] == "queued")

baseline_s = float(defn["baseline"]["median_manual_cycle_s"])
auto_s = sum(r.get("automation_seconds", 0.0) for r in records)
review_s = sum(r.get("review_seconds", 0.0) for r in records)

# A queued case saves nothing. The reviewer's time was still spent on it AND the
# whole manual cycle still has to happen afterwards. Charging it the full manual
# cycle is what makes the exception count cost something in this number.
before_s = baseline_s * processed
after_s = (
    sum(r.get("automation_seconds", 0.0) + r.get("review_seconds", 0.0)
        for r in records if r["outcome"] == "automated")
    + sum(r.get("review_seconds", 0.0) + baseline_s
          for r in records if r["outcome"] == "queued")
)
pct = (1 - after_s / before_s) * 100 if before_s else 0.0

c1, c2, c3, c4 = st.columns(4)
c1.metric("Cases processed", processed)
c2.metric("AUTOMATED", automated)
c3.metric("QUEUED FOR HUMAN", queued,
          delta=None if not queued else f"{queued} need a person",
          delta_color="inverse")
c4.metric("Hands-on time removed", f"≈{pct:.0f}%" if processed else "—",
          help="relative, not absolute — see the note below")

st.caption(
    f"**Time-saved basis.** before = median manual cycle **{baseline_s:g}s** × {processed} cases "
    f"(MEASURED: `reports/step2_process_metrics.csv`, 77 observed executions). "
    f"after = automated cases at (engine {auto_s:.1f}s + review {review_s:.1f}s) + queued cases "
    f"charged the full manual cycle, because a queued case still has to be done by hand. "
    f"**Reported as a ratio on purpose.** The {baseline_s:g}s baseline comes from a "
    f"test-environment recording whose dwell is ≈1.4× compressed, and this mock's own "
    f"seconds are not on that clock at all. The two distortions push in opposite directions "
    f"and neither is invertible, so this is a demo figure. Do not multiply it by a headcount "
    f"or an hourly rate."
)
if processed and pct < 0:
    st.caption("The figure is negative because the cases handled so far are mostly "
               "exceptions. That is the metric working: a case that is reviewed and then "
               "queued costs the reviewer's time *and* still has to be done by hand.")

st.divider()

# ---------------------------------------------------------------- queue
cases = state["cases"]
pending = [c for c in cases
           if c["row_cells"]["status"] == "未処理" and c["case_id"] not in ss.handled]
# A case already in a terminal status is not pending, but one seeded row starts in
# 完了 on purpose. Surface it, because the engine has to refuse it.
blocked = [c for c in cases
           if c["row_cells"]["status"] != "未処理" and c["case_id"] not in ss.handled
           and c["case_id"] not in {r["case_id"] for r in records}]

left, right = st.columns([3, 2], gap="large")

with left:
    st.subheader("Pending cases")
    st.caption(f"{len(pending)} awaiting review · reviewed one at a time, then the rest "
               f"as a batch")
    if blocked:
        st.caption(f"{len(blocked)} further case(s) are not in 未処理 and are included in "
                   f"the batch on purpose — the engine has to refuse them rather than "
                   f"commit over a row that is already closed.")

    log_box = st.empty()

    if not pending and not blocked:
        st.success("Nothing pending. Reset the portal from the sidebar to run the demo again.")

    if pending:
        case = pending[0]
        cid = case["case_id"]
        ss.shown_at.setdefault(cid, time.time())

        st.markdown(f"#### `{cid}` — row {case['row']}")

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
        st.dataframe(rows, use_container_width=True, hide_index=True)

        composed_src = {**detail, **overrides}
        try:
            preview = defn["write"]["template"].format(**composed_src)
        except (KeyError, IndexError):
            preview = "(cannot compose — a template field is missing)"
        st.markdown("**Will be written to `#rt-note`** &nbsp; "
                    "<span style='color:#6b7684'>source: derived — "
                    "`write.template` applied to the fields above</span>",
                    unsafe_allow_html=True)
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
                    dispatch(defn_file, [job], log_box)
                    st.rerun()
                if cols[1].form_submit_button("Cancel", use_container_width=True):
                    ss.editing = None
                    st.rerun()
        else:
            b1, b2, b3 = st.columns(3)
            if b1.button("APPROVE", type="primary", use_container_width=True,
                         key=f"ap_{cid}"):
                job = {"case_id": cid, "row": case["row"], "action": "approve",
                       "overrides": overrides, "reviewed_by": "reviewer",
                       "review_seconds": round(time.time() - ss.shown_at[cid], 2)}
                dispatch(defn_file, [job], log_box)
                st.rerun()
            if b2.button("EDIT", use_container_width=True, key=f"ed_{cid}"):
                ss.editing = cid
                st.rerun()
            if b3.button("FLAG", use_container_width=True, key=f"fl_{cid}"):
                job = {"case_id": cid, "row": case["row"], "action": "flag",
                       "flag_reason": "flagged by the reviewer — not automated",
                       "reviewed_by": "reviewer",
                       "review_seconds": round(time.time() - ss.shown_at[cid], 2)}
                dispatch(defn_file, [job], log_box)
                st.rerun()

    st.divider()
    rest = [c for c in pending[1:]] if pending else []
    rest += blocked
    if rest:
        if st.button(f"▶ Run remaining {len(rest)} as batch", use_container_width=True):
            jobs = [{"case_id": c["case_id"], "row": c["row"], "action": "approve",
                     "overrides": {}, "reviewed_by": "batch", "review_seconds": 0.0}
                    for c in rest]
            dispatch(defn_file, jobs, log_box)
            st.rerun()
        st.caption("Batch cases get no individual review, so they are charged 0 review "
                   "seconds — and the seeded failures in them still land in the queue.")

    if ss.last_log:
        with st.expander("Engine trace — last run", expanded=False):
            st.markdown(ss.last_log)

with right:
    st.subheader("Exception queue")
    q = [r for r in records if r["outcome"] == "queued"]
    if not q:
        st.caption("Empty. Cases arrive here when the definition does not recognise "
                   "something, or when the verify read-back does not confirm the write.")
    for r in q:
        st.error(f"**{r['case_id']}** · `{r['code']}` (at *{r['stage']}*)\n\n"
                 f"{r['detail']}\n\n"
                 f"commit attempts: **{r['commit_attempts']}** · "
                 f"verify: **{r['verify_confirmed']}**")

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
st.caption("One record per case: what was read out of the DOM, what the reviewer "
           "changed, what was written, whether a commit was attempted and how many "
           "times, whether the read-back confirmed it, and when.")
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
