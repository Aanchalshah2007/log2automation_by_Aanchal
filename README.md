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

## Status

| Step | State | Output |
|---|---|---|
| **1 — Recover units of work** | **Complete** | [`segments.jsonl`](segments.jsonl) · [report](reports/step1_segmentation_report.md) |
| **2 — Analyse and prioritise automation candidates** | **Complete** | [report](reports/step2_analysis.md) · [metrics table](reports/step2_process_metrics.csv) |
| **3 — Build the automation tool** | **Working prototype** | [build notes](reports/step3_build_notes.md) · `src/mock_portal/` · `src/automation/` · `src/app.py` |

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
margin of 1.4x-2.2x. It is also the second most buildable process in the set, so it is
the Step-3 target with nothing deferred to get there. The volume leader (134 cases, 26.5
of 163 segmented minutes) places second: it writes to payroll and tax withholding, and
step 1 established it is two business objectives sharing one worklist.

**Step 3 headline.** A human-in-the-loop prototype for 発注管理: a reconstructed mock of
the screen, a **deterministic, config-driven** Playwright engine that runs the observed
motif per case (open row → write the templated note → **commit once** → **verify the
write landed by re-reading the row's ステータス**), and a Streamlit review UI where a
person approves, corrects or flags each case before anything commits. **No LLM runs
anywhere in the runtime**, and `llm_in_runtime: false` is recorded on every audit record.
Adding a second process is a new JSON definition, not new code — one full definition
(発注管理) ships working, one stub (勤怠・休暇申請) proves the shape extends. Of 18 seeded
cases, 4 are deliberately unautomatable and all 4 land in the exception queue rather than
committing; replaying the whole job set over an already-processed worklist attempts
**zero** commits on an already-committed row. What is mocked, what stays manual, and what
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
    static/            index.html / app.js / styles.css — the reconstructed screen
  automation/        the engine
    engine.py          Playwright runner: read -> precheck -> write -> commit once -> VERIFY
    definitions/       one per process; fin_purchase_order_management.json is live,
                       hr_attendance_leave_request.stub.json proves the shape extends
    setup_browser.sh   no-root fallback if `playwright install --with-deps` cannot run
  app.py             the Streamlit review UI (approve / edit / flag + live counters)

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

Python 3.10+. **No third-party dependencies** — standard library only.

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

Three processes, started in this order. Step 3 is the only part of this repository with
third-party dependencies.

**Once, to set up:**

```bash
pip install -r requirements-step3.txt
python3 -m playwright install --with-deps chromium
```

If that last command fails because `sudo` is unavailable (the symptom is
`error while loading shared libraries: libnspr4.so`), run
`bash src/automation/setup_browser.sh` instead. It unpacks what chromium needs into the
git-ignored `build/` directory and `engine.py` picks it up on its own.

**1 — the mock portal** (terminal 1). The 発注管理 screen, acting as both the source and
the destination. It holds the case state server-side, so the engine's verify step is a
real read of real state.

```bash
python3 src/mock_portal/server.py --port 5233 --cases 18
#  -> http://127.0.0.1:5233/   (open it to watch the worklist change)
```

**2 — the review UI** (terminal 2). This is the demo surface, and it launches the engine
itself as a subprocess for each approved case.

```bash
streamlit run src/app.py
#  -> http://localhost:8511
```

Demo flow: approve the first few cases one at a time, watching the engine trace go
`wrote → verifying… → ✓ 登録済み confirmed`, then press **Run remaining as batch**. Use
**EDIT** on at least one case — the value you type is the value that commits, and the
audit log records both. Four of the eighteen cases are deliberately unautomatable and
will land in the exception queue instead of committing; that number is the point.

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
