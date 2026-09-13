# Name - Shah Aanchal Sachinkumar
# University - Indian Institute of Technology, Kharagpur 
# Department - Aerospace Engineering
# Personal Email ID - aanchalshah2007@gmail.com
# Institute Email ID - aanchalshah2007.24@kgpian.iitkgp.ac.in

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
| 2 — Analyse and prioritise automation candidates | Not started | — |
| 3 — Build the automation tool | Not started | — |

**Step 1 headline.** 684 segments across all 15 dataset-B sessions, 12 discovered
processes. Validated on dataset A against its ground truth: boundary F1 0.858 at a 2 s
tolerance, mean temporal IoU 0.865, 91.0% of executions matched at IoU ≥ 0.5, and 15
process labels recovered with no supervision (ARI 0.912 overall, 0.993 on the 56 of 63
sessions where the browser extension was connected). A 21-session holdout scores better
than the 42-session dev split it was tuned on.

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
  qa_segments.py     14 output checks; exits non-zero on failure
  run_eval_a.py      quick dataset-A scoreboard

  diag_*.py          the diagnostics behind each design decision (see below)

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

python3 tune.py           # optional: re-run the parameter sweep
python3 discover_b.py     # optional: re-run process discovery on B
```

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
