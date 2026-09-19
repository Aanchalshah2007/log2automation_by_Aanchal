## Name - Shah Aanchal Sachinkumar
## University - Indian Institute of Technology, Kharagpur 
## Department - Aerospace Engineering
## Personal Email ID - aanchalshah2007@gmail.com
## Institute Email ID - aanchalshah2007.24@kgpian.iitkgp.ac.in

# Operation logs → automation proposal

The client runs a desktop agent that records every keystroke, click
and application switch from back-office staff (HR, Finance, Logistics). Nothing in the
log says which business process an operation belongs to. The job is to recover the units
of work, decide where automation pays, and build something that runs.

The assignment as given is in **[`docs/TASK.md`](docs/TASK.md)**; the data specification is
in **[`docs/DATA_SCHEMA.md`](docs/DATA_SCHEMA.md)**. Both are the provided material,
unmodified.

---

## Start here

**▶ [`reports/FINAL_REPORT.md`](reports/FINAL_REPORT.md) is the main report** — the
consolidated read covering all three steps: the ranking and its reasoning, what was built
and why, what stays manual, the expected impact and its caveats, and the rollout risks.
The per-step reports below are the depth behind it.

| Deliverable | Where it lives |
|---|---|
| **Step 1 — recovered units of work** | [`segments.jsonl`](segments.jsonl) — 684 segments, 15 sessions, 12 processes · method and validation in [`reports/step1_segmentation_report.md`](reports/step1_segmentation_report.md) |
| **Step 2 — analysis + prioritised candidates** | [`reports/step2_analysis.md`](reports/step2_analysis.md) · every metric in [`reports/step2_process_metrics.csv`](reports/step2_process_metrics.csv) and [`reports/step2_metrics.json`](reports/step2_metrics.json) |
| **Step 3 — working prototype** | `src/mock_portal/` · `src/automation/` · `src/app.py` · build notes in [`reports/step3_build_notes.md`](reports/step3_build_notes.md) |
| **The consolidated report** | [`reports/FINAL_REPORT.md`](reports/FINAL_REPORT.md) |
| **Working log** | [`WORKLOG.md`](WORKLOG.md) — day by day: what was tried, what failed, and why |

---

## Status

| Step | State | Output |
|---|---|---|
| **1 — Recover units of work** | **Complete** | [`segments.jsonl`](segments.jsonl) · [report](reports/step1_segmentation_report.md) |
| **2 — Analyse and prioritise automation candidates** | **Complete** | [report](reports/step2_analysis.md) · [metrics table](reports/step2_process_metrics.csv) |
| **3 — Build the automation tool** | **Complete** — working prototype | [build notes](reports/step3_build_notes.md) · `src/mock_portal/` · `src/automation/` · `src/app.py` |

All three steps are complete. Step 3 is a **working prototype against a reconstructed mock
of the client's screen**, not a production deployment — what is real, what is mocked and
what stays manual is stated in the final report and in the build notes.

**Step 1 headline.** 684 segments across all 15 dataset-B sessions, 12 discovered
processes. Validated on dataset A against its ground truth: boundary F1 0.858 at a 2 s
tolerance, mean temporal IoU 0.865, 91.0% of executions matched at IoU ≥ 0.5, and 15
process labels recovered with no supervision (ARI 0.912 overall, 0.993 on the 56 of 63
sessions where the browser extension was connected). A 21-session holdout scores better
than the 42-session dev split it was tuned on.

**Step 2 headline.** Twelve processes measured on 43 quantities each, scored on two
deliberately separate axes: `Client_ROI = Impact x Automatability x Client_Feasibility`
(the ranking) and `Build_Fit` (whether a convincing prototype fits in the days left — a
fact about my week, not the client's business, so it never enters the ranking).
**`fin_purchase_order_management` (発注管理) ranks first, and stays first in all three
robustness re-runs** — with the conflated `hr_expense_and_pay_change` label split 50/50,
with the extension-less session dropped, and with thin OCR evidence discarded — by a
margin of 1.4x-2.2x. It is also the **third** most buildable process in the set
(`build_fit` 0.796, behind `hr_attendance_leave_request` 0.965 and `ops_it_access_request`
0.854), so it is the Step-3 target with nothing deferred to get there. The volume leader
(134 cases, 26.5 of 163 segmented minutes) places second: it writes to payroll and tax withholding, and
step 1 established it is two business objectives sharing one worklist.

**Step 3 headline.** A human-in-the-loop prototype for 発注管理: a reconstructed mock of
the screen, a **deterministic, config-driven** Playwright engine that runs the observed
motif per case (open row → write the templated note → **re-read the note field to confirm
it landed** → **commit once** → **verify by re-reading the row's ステータス**), and a
Streamlit review UI — with the portal embedded live beside it — where a
person approves, corrects or flags each case before anything commits. **No LLM runs
anywhere in the runtime**, and `llm_in_runtime: false` is recorded on every audit record.
Adding a second process is a new JSON definition, not new code — one full definition
(発注管理) ships working, one stub (勤怠・休暇申請) proves the shape extends. On the headline
run (**Run A**: reset → 3 live approvals → 15 batched, portal epoch `755859baf586` in
`build/audit_log.jsonl`) **14 of 18 cases automated and 4 went to the exception queue** —
the 4 deliberately unautomatable ones — removing **≈56% of hands-on time (relative)**. A
second run (**Run B**, epoch `bc555a988b9f`) scored **13/5** because a reviewer's edit
failed the field-schema check and was stopped at precheck before any write; see
[`reports/FINAL_REPORT.md`](reports/FINAL_REPORT.md) §3.3. All 4 seeded failures land in the
queue rather than committing; replaying the whole job set over an already-processed worklist attempts
**zero** commits on an already-committed row. The embedded portal repaints on every
commit rather than on a manual reload, so rows flip 未処理 → 登録済み one at a time as the
engine works through them, and the **QUEUED FOR HUMAN** counter is a link to the four
refused cases — each named with the code it was refused on and the reason in words.
What is mocked, what stays manual, and what
was designed rather than observed are all stated in
[`reports/step3_build_notes.md`](reports/step3_build_notes.md).

---

## Repository layout

```
README.md                             this file
WORKLOG.md                            daily log: what was tried, what failed, why
segments.jsonl                        STEP 1 DELIVERABLE - one segment per line

docs/
  TASK.md                             the assignment (provided, unmodified)
  DATA_SCHEMA.md                      data specification (provided, unmodified)

reports/
  step1_segmentation_report.md        method, validation, failure cases, limitations
  step2_analysis.md                   STEP 2 REPORT - process analysis + ranking
  step2_process_metrics.csv           per-process metrics and every scoring factor
  step2_metrics.json                  the same, machine-readable, + robustness re-runs
  validation_A.json                   every dataset-A metric, machine-readable
  tuned_constants.json                the four fitted constants, sweep vs shipped
  discovery_B.json                    dataset-B process discovery + split/merge tests

src/
  common.py          event cache, portal (system, route) resolution
  groundtruth.py     rebuild dataset-A ground truth from gt.jsonl
  features.py        context channels, case anchors, L2 fallback anchors
  screenmap.py       learn screen-name -> route from the data's own screen text
  segmenter.py       the method: case cores -> segments
  labels.py          readable process labels
  evaluate.py        boundary / IoU / coverage / label-consistency metrics
  fingerprint.py     behavioural fingerprints (label consistency checks only)

  validate_a.py      full dataset-A validation + ablations   -> reports/
  tune.py            parameter sweep with a held-out split   -> reports/
  discover_b.py      dataset-B process discovery             -> reports/
  run_b.py           produce segments.jsonl

  roi.py             STEP 2 scoring model: Client_ROI and Build_Fit
  rank_b.py          STEP 2 measurement + ranking              -> reports/
  report_tables.py   renders the generated tables in the step-2 report
  verify_step2.py    235 checks: every report table vs the generated artefacts
  qa_segments.py     14 output checks; exits non-zero on failure
  run_eval_a.py      quick dataset-A scoreboard

  diag_*.py          the diagnostics behind each design decision (see below)

  --- STEP 3, purely additive ---
  mock_portal/       the local 発注管理 screen (source AND destination)
    server.py          stdlib HTTP server; holds case state so the read-back is real
    cases.py           synthetic case seed, incl. the 4 deliberately failing cases
    static/            index.html / app.js / styles.css — the reconstructed screen;
                       the embedded copy repaints off /api/rev when state moves
  automation/        the engine
    engine.py          Playwright runner: read -> precheck -> write -> commit once -> VERIFY
    definitions/       one per process; fin_purchase_order_management.json is live,
                       hr_attendance_leave_request.stub.json proves the shape extends
    setup_browser.sh   no-root fallback if `playwright install --with-deps` cannot run
  app.py             the Streamlit review UI: approve / edit / flag, live counters,
                     the exception queue, and the portal embedded live beside it

requirements-step3.txt                step 3 only; steps 1-2 stay stdlib-only
build/                                derived cache, git-ignored, regenerated on demand
```

The `diag_*.py` scripts are kept deliberately. Each one is the measurement that settled a
design question, and the report cites them: `diag_signal.py` (is portal context enough?
no — 61.6% of boundaries), `diag_anchor.py` (where do case anchors sit inside an
execution?), `diag_gap.py` (who owns the dead time between executions?),
`diag_l2.py` / `diag_cycle.py` / `diag_fallback.py` (what survives when the browser
extension is down?), `diag_long.py` (why do long executions score badly?),
`diag_failures.py` (the failure-mode breakdown), `diag_b_coverage.py` (how much of
dataset B is reachable at all?).

---

## Running it

Python 3.10+. **No third-party dependencies for Step-1 and Step-2** — standard library only.

The two provided dataset directories must sit at the repository root under their original
names (`dataset_a-20260913T153639Z-1-001/`, `dataset_b-20260913T153602Z-1-001/`). They are
git-ignored: 4.4 GB of provided data does not belong in the repo.

```bash
cd src

python3 validate_a.py     # dataset A: metrics, ablations, label/GT contingency
python3 run_b.py          # writes ../segments.jsonl
python3 qa_segments.py     # 14 checks on the deliverable
python3 rank_b.py         # step 2: metrics + ranking -> ../reports/
python3 verify_step2.py   # 235 checks: the step-2 report against those artefacts

python3 tune.py           # optional: re-run the parameter sweep
python3 discover_b.py     # optional: re-run process discovery on B
```

---

## Run the prototype (step 3)

Two processes, started in this order, plus the engine on its own if you want it.
**Run every command from the repository root.** Step 3 is the only part of this repository
with third-party dependencies.

**Once, to set up:**

```bash
pip install -r requirements-step3.txt      # playwright + streamlit
python3 -m playwright install chromium     # add --with-deps on Linux (needs sudo)
```

That is the whole setup on a clean machine.

*Fallback only:* if `--with-deps` cannot run because `sudo` is unavailable — the symptom is
`error while loading shared libraries: libnspr4.so` — run
`bash src/automation/setup_browser.sh`. It downloads the `.deb` packages chromium needs and
unpacks them under the git-ignored `build/pwdeps/`, which `engine.py` adds to
`LD_LIBRARY_PATH` itself. **This is a local workaround for a no-root Linux box and is not
part of a normal install** — on a machine where `playwright install --with-deps chromium`
succeeds, `build/pwdeps/` is never created and never needed.

**1 — the mock portal** (terminal 1). The 発注管理 screen, acting as both the source and
the destination. **This process is the single source of truth for the portal's row
state** — it holds it in memory, there is no state file, and it refuses to start if
another portal is already serving the same port (two portals behind one URL was a real
bug; see build notes §5c). Its banner prints the `server_id` that every audit record is
stamped with.

```bash
python3 src/mock_portal/server.py --port 5233 --cases 18
#  -> http://127.0.0.1:5233/   (open it to watch the worklist change)
```

**2 — the review UI** (terminal 2). This is the demo surface, and it launches the engine
itself as a subprocess for each approved case.

```bash
streamlit run src/app.py
#  -> http://localhost:8501   (Streamlit's default; pass --server.port to change it)
```

Demo flow: press **RESET DEMO** in the sidebar, then approve cases one at a time. The
portal is embedded live on the right — watch the ステータス column flip 未処理 → 登録済み
as each case commits. **No manual refresh is needed**: the embedded copy watches the
portal's `/api/rev` and repaints only when the portal's state actually moves — once per
case, including during the batch, so the rows flip one by one. Watch the engine trace on
the left go
`writing the note → ✓ note confirmed in the DOM → committing (once, no retry) →
verifying… → ✓ 登録済み confirmed`. Then press **Run remaining as batch**. Use **EDIT**
on at least one case — the value you type is the value that commits, and the audit log
records both. Four of the eighteen cases are deliberately unautomatable and land in the
exception queue instead of committing; that number is the point.

The counters (**worklist / awaiting review / automated / queued**) are derived from the
portal's own state plus this run's audit log on every redraw, so they always reconcile:
`total = pending + automated + queued`. Reseeding the portal in a terminal does not
desync the dashboard — it rebinds on the next interaction. **QUEUED FOR HUMAN** is
clickable: it jumps to the exception queue, which lists every refused case with its case
id, worklist row, failure code (`STATUS_NOT_COMMITTABLE`, `VERIFY_FAILED`,
`REQUIRED_FIELD_MISSING`, `ENUM_UNRECOGNISED`), the reason in words, how many times
commit was pressed, and whether verify ever confirmed anything.

**3 — the engine on its own** (optional). It is a standalone CLI and does not need
Streamlit; this is how it would run from a scheduler.

```bash
python3 -c "import json; json.dump([{'case_id': f'P10-07054374-{i:03d}', 'row': i,
  'action': 'approve', 'overrides': {}, 'review_seconds': 0.0} for i in range(1, 19)],
  open('build/jobs.json', 'w'))"

python3 src/automation/engine.py \
    --definition src/automation/definitions/fin_purchase_order_management.json \
    --jobs   build/jobs.json \
    --audit  build/audit_log.jsonl
#  add --headed --slow-mo 400 to watch it drive a visible browser
```

If a run fails to start — the portal is down, or chromium will not launch — the engine
writes one `ENGINE_STARTUP_FAILED` record per job rather than exiting silently, so no
case is ever lost between the review UI and the audit log.

Progress is JSON lines on stdout; one audit record per case lands in
`build/audit_log.jsonl`. Everything derived — the audit log, the job files, the
screenshots in `build/screens/` — stays in the git-ignored `build/` directory.

`reports/step3_build_notes.md` states what genuinely works, what is mocked, what stays
manual after deployment, how the time-saved ratio is computed, and the risks carried
over from step 2 §7.5 and §8.2.

The first run projects both datasets into `build/events_{A,B}.jsonl` (~90 s, ~90 MB) and
every later run reads that cache. Delete `build/` to force a rebuild.

---

## Method in one paragraph

Every process in these logs is worked against one screen of one back-office web system,
and each case on that screen is opened by clicking a worklist row and closed by clicking
an action button. So: resolve which system and screen the browser is on for every event
(from the URL, the DOM element, or the window title plus the OCR breadcrumb — whichever
survives), carry that context across the Excel/Word/Notepad detours that consume most of
the wall clock, find the row-open → commit case cores inside it, and place boundaries
using margins scaled to the session's own case length. Background activity never acquires
a context, so it never becomes a segment. No machine learning, no dataset-A labels
transferred to dataset B — the process identities in B are discovered from B's own
rendered screen text. Full reasoning, including what was tried and rejected, in
[`reports/step1_segmentation_report.md`](reports/step1_segmentation_report.md).
