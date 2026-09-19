# Operation logs → automation proposal — final report

**Shah Aanchal Sachinkumar** · IIT Kharagpur, Aerospace Engineering
Dataset A + Dataset B · seven working days · 2026-09-13 → 2026-09-19

This is the consolidated read. It states the recommendation, what was built, what stays
manual, what the numbers do and do not support, and what will bite on rollout. The depth
behind each section lives in the per-step reports, which it references rather than repeats:

| For depth on | Read |
|---|---|
| How units of work were recovered, and its validation | [`step1_segmentation_report.md`](step1_segmentation_report.md) · [`validation_A.json`](validation_A.json) |
| The measurement, the scores, the ranking, the limits | [`step2_analysis.md`](step2_analysis.md) · [`step2_process_metrics.csv`](step2_process_metrics.csv) · [`step2_metrics.json`](step2_metrics.json) |
| What was built, what is mocked, every bug found while running it | [`step3_build_notes.md`](step3_build_notes.md) |
| What was tried, what failed, and why, day by day | [`../WORKLOG.md`](../WORKLOG.md) |

**Evidence tagging used throughout.** Every claim is marked:

- **[MEASURED]** — computed from the provided logs. The file it comes from is named.
- **[ENGINEERING ASSUMPTION]** — a design decision made where the data is silent. Not evidence.
- **[MOCKED]** — reconstructed or invented for the prototype, because the real thing was unavailable.
- **[MANUAL]** — stays a human's job after deployment.

---

## 1. Executive summary

Dataset B holds **684 cases across 15 sessions, 4 operators and 163.4 segmented minutes,
covering 12 distinct business processes** — none of it labelled in the logs.
**[MEASURED]** (`step2_metrics.json`, `segments.jsonl`, verified by `src/qa_segments.py`:
14 checks, all pass).

The highest-return automation opportunity is **`fin_purchase_order_management` (発注管理)** —
purchase-order registration in the finance system. It ranks **1st of 12 on Client_ROI
(0.166)**, and it holds 1st place across **all four ranking views** (the base plus three robustness re-runs) by a margin of
**1.4×–2.2×** over the runner-up. **[MEASURED]** (`step2_process_metrics.csv`,
`step2_metrics.json`).

It is not the biggest pile of work. **The highest-volume process placed 2nd**, and the
reason it lost is the central finding of the analysis: volume is not the same as
opportunity once feasibility is measured rather than assumed.

What was built is a **working human-in-the-loop prototype**: a deterministic, config-driven
Playwright engine that runs the observed motif per case — open the row → write a templated
note → **re-read the note to confirm it landed** → **commit once, no retry** → **verify by
re-reading the row's status** — behind a Streamlit review surface where a person approves,
corrects or flags every case before anything commits. **No LLM runs at runtime**, and
`llm_in_runtime: false` is recorded on **every** audit record of both runs below
**[MEASURED]**.

On the **headline run (Run A)**: **14 automated, 4 refused to a human exception queue** —
the 4 deliberately-unautomatable seeded cases — removing **≈56% of hands-on time**
(relative; see §5.2 for what that does and does not mean). **[MEASURED]**

**Two things this is not.** The portal it drives is a **[MOCKED]** reconstruction — there
was no access to the client's system — and every case value on screen is **[MOCKED]**
synthetic, because the logs recorded clipboard event *length* and never content. The
prototype therefore demonstrates that **the procedure is automatable**. It does not
demonstrate that the client's real data is clean enough to run through it.

---

## 2. Step 2 — analysis, prioritised candidates, and the reasoning

### 2.1 Two scores, deliberately kept apart

**Client_ROI = Impact × Automatability × Client_Feasibility** — the client's ranking.

- `Impact` — share of observed hands-on time
- `Automatability = repeatability × copy_paste_ratio × (1 − variant_rate) × (1 − judgment_step)`
- `Client_Feasibility = structured_target × stable_selectors × low_branching × (1 − sensitivity)`

**Build_Fit = loop_completeness × evidence_density × mock_fidelity × selector_determinism** -
whether a convincing prototype fits in the days I had left.

**Build_Fit never enters Client_ROI.** It is a fact about my week, not about the client's
business. Keeping them separate is what stops "easiest for me to demo" from quietly
becoming "best for the client" — and it changed a real decision (§2.4).

### 2.2 The ranking — all twelve **[MEASURED]** (`step2_process_metrics.csv`)

| # | Process | Client_ROI | Impact | Autom. | Feas. | *Build_Fit* | Cases | Total s |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| **1** | **`fin_purchase_order_management`** | **0.1659** | 0.5746 | 0.6157 | 0.4688 | *0.7964* | 77 | 838 |
| 2 | `hr_expense_and_pay_change` | 0.0898 | **1.0000** | 0.4042 | 0.2221 | *0.7404* | **134** | **1589** |
| 3 | `hr_attendance_leave_request` | 0.0755 | 0.3419 | 0.4786 | 0.4611 | *0.9653* | 56 | 575 |
| 4 | `ops_inventory_management` | 0.0705 | 0.4545 | 0.3223 | 0.4809 | *0.7536* | 67 | 847 |
| 5 | `fin_invoice_approval` | 0.0496 | 0.7782 | 0.3412 | 0.1867 | *0.5151* | 74 | 1368 |
| 6 | `ops_contract_management` | 0.0380 | 0.8005 | 0.2001 | 0.2371 | *0.4634* | 59 | 1144 |
| 7 | `ops_it_access_request` | 0.0368 | 0.2849 | 0.5325 | 0.2427 | *0.8540* | 40 | 471 |
| 8 | `hr_benefits_application` | 0.0323 | 0.2849 | 0.3762 | 0.3017 | *0.7467* | 35 | 447 |
| 9 | `hr_onboarding` | 0.0311 | 0.7056 | 0.2337 | 0.1885 | *0.4883* | 65 | 1180 |
| 10 | `fin_budget_variance_analysis` | 0.0295 | 0.1140 | 0.4893 | 0.5296 | *0.1462* | 8 | 154 |
| 11 | `fin_payment_processing` | 0.0235 | 0.5020 | 0.2394 | 0.1956 | *0.5311* | 37 | 650 |
| 12 | `fin_manager_expense_approval` | 0.0212 | 0.3799 | 0.2557 | 0.2187 | *0.5274* | 32 | 540 |

### 2.3 The key point: the volume leader placed 2nd, and why that is the right answer

`hr_expense_and_pay_change` has **1.7× the case count (134 vs 77) and 1.9× the total time
(1589 s vs 838 s)** of the recommended target, and scores the maximum **Impact 1.00**. It
still lost, on the two factors that decide whether volume is *reachable*: **[MEASURED]**

| | Target (#1) | Volume leader (#2) |
|---|---:|---:|
| Impact | 0.5746 | **1.0000** |
| Automatability | **0.6157** | 0.4042 |
| Client_Feasibility | **0.4688** | 0.2221 |
| `sensitivity` | 0.20 | **0.60** |
| `variant_rate` | 0.167 | 0.308 |
| **Client_ROI** | **0.1659** | 0.0898 |

Two things crushed it:

**Sensitivity.** It writes to payroll and tax withholding. `sensitivity` is scored **0.60**
against the target's 0.20, and it enters feasibility as `(1 − sensitivity)`. A process where
a wrong write changes somebody's pay is not a first automation. *(The sensitivity table is
the one **unmeasured** input in the model — see §6.6.)*

**The P1/P4 conflation.** Step 1 established this single label covers **two business
objectives sharing one positional worklist**: `P1-…` rows (expense settlement) interleaved
with `P4-…` rows (pay changes). The P-code appears in the detail pane of only **5 of 684
segments**, and the row selector is positional, so a code cannot be attributed to an
individual clicked row. **[MEASURED]** An automation treating that worklist as one queue
would silently apply expense-claim handling to a pay change.

I bounded it rather than speculating. The P-code *does* prefix every worklist row rendered
into `context.extracted_text`, and **in all 8 sessions where both codes appear the screen
carries exactly 12 P1 rows and 12 P4 rows - 96 and 96, a ratio of 1.000** **[MEASURED]**
(`conflation_evidence` in `step2_metrics.json`). The worst case is a clean 50/50 split.

**The recommendation survives all four views** **[MEASURED]** (`step2_analysis.md` §5):

| Ranking view | 1st | 2nd | Margin |
|---|---|---|---:|
| Base (as one process) | `fin_purchase_order_management` 0.166 | `hr_expense_and_pay_change` 0.090 | 1.8× |
| Conflated label split 50/50 | `fin_purchase_order_management` 0.207 | `hr_attendance_leave_request` 0.094 | 2.2× |
| Extension-less session removed | `fin_purchase_order_management` 0.207 | `hr_expense_and_pay_change` 0.122 | 1.7× |
| Thin worklist 種別 evidence dropped | `fin_purchase_order_management` 0.184 | `hr_attendance_leave_request` 0.129 | 1.4× |

Splitting the conflated label only pushes it *further* down — the two halves land 4th and
below — so the answer does not depend on resolving a question Step 1 could not resolve.

### 2.4 Where keeping the two scores separate changed the decision

`hr_attendance_leave_request` has the **highest Build_Fit in the set (0.9653)** — it was the
easiest thing to build. Its Client_ROI is **0.0755, under half** the target's. It was not
chosen. It ships as a **stub definition** instead, which is the honest use of it: proof the
architecture extends, not a substitute for the recommendation.

---

## 3. Step 3 — what was built, and the scope

### 3.1 Why this process

`fin_purchase_order_management` is **the highest-Client_ROI process that is also
buildable** — ranked **1st of 12 on Client_ROI (0.1659)** and **3rd of 12 on Build_Fit
(0.7964)**, behind only `hr_attendance_leave_request` (0.9653) and `ops_it_access_request`
(0.8540). No trade-off was needed to get a working prototype. **[MEASURED]**


Its whole input surface is inside the portal, which is what makes it automatable without an
integration project: **[MEASURED]** (`step2_process_metrics.csv`)

| Signal | Value | Why it matters |
|---|---:|---|
| `paste_source_in_portal` | **0.947** | ~95% of clipboard content is copied from inside the portal itself |
| `paste_source_document` | **0.000** | **nothing** comes out of Word — no document-understanding problem |
| `copy_paste_ratio` | 0.9634 | the case arrives via the clipboard, not typed from a person's head |
| `variant_rate` | 0.167 | one dominant handling pattern |
| `judgment_step` | 0.070 | almost no discretionary decision inside the loop |
| `template_conformance` | 0.896 | the note written at the end follows a fixed template |
| `sensitivity` | 0.20 | a purchase order against a registered supplier is operational and reversible |
| median cycle | **11.0 s** | over **77 observed executions** in 9 sessions |

The `paste_source_document 0.000` is the decisive one. Four of the lower-ranked processes
have 31–38% of their clipboard content copied out of Word — those need a document pipeline
before any automation is possible. This one does not.

### 3.2 Why this scope — shared foundation, per-process definition

**One process built end-to-end, plus the foundation that makes the second one configuration
rather than code.**

**[MEASURED]** All twelve processes in dataset B share **one DOM contract with five selector
prefixes**. Hard-coding selectors for a single screen would throw away eleven-twelfths of
the work and save nothing, because the first definition has to be written either way.

So the split is:

- **The engine** (`src/automation/engine.py`) — process-agnostic. Reads, prechecks, writes,
  confirms, commits once, verifies, queues.
- **The definition** (`src/automation/definitions/*.json`) — per process: selectors, row
  columns, field schema, enums, the note template, the status vocabulary, the baseline.

Adding a second process is a **new JSON file and a mock, not new engine code**. The shipped
evidence for that claim is `hr_attendance_leave_request.stub.json`, which is present,
declared `state: stub`, and which **the engine refuses to run** — the shape is proven
without pretending a second process is finished.

### 3.3 What the prototype does, per case

```
read row → precheck → write note → confirm the note landed → commit ONCE → verify by re-reading the row
                ↓ any failure at any stage
         exception queue, nothing committed, a human owns it
```

**Two runs are reported, not one.** A single staged number says nothing about whether the
system behaves sensibly twice. Every figure in this report is tied to one of these two, and
each is reproducible from its own audit records.

| | **Run A — headline** | **Run B — robustness** |
|---|---|---|
| How it was produced | reset → **3 live approvals → 15 batched** | reset → **4 live approvals → 14 batched** |
| Cases | 18 | 18 |
| **Automated / queued** | **14 / 4** | **13 / 5** |
| Hands-on time removed | **≈56%** (before 198.0 s → after 87.6 s) | ≈41% (before 198.0 s → after 116.5 s) |
| `llm_in_runtime` | `false` on all 18 | `false` on all 18 |
| Source | `build/audit_log.jsonl`, portal epoch **`755859baf586`** | `build/audit_log.jsonl`, portal epoch **`bc555a988b9f`** |

**[MEASURED]**, both. A portal epoch identifies one seeded worklist, so it is the unit of a
run; each spans several engine invocations (the live approvals and then the batch).

**Run A — the 4 queued are exactly the 4 seeded-unautomatable cases:**

- **14 automated** — each with `note_confirmed: true`, `commit_attempts: 1`, `verify_confirmed: true`
- **4 queued** — `REQUIRED_FIELD_MISSING` (row 6), `STATUS_NOT_COMMITTABLE` (row 11),
  `ENUM_UNRECOGNISED` (row 14), `VERIFY_FAILED` (row 17)

The `VERIFY_FAILED` case is the one that matters most: the portal **accepted the commit
click, showed a toast, and changed nothing**. The engine caught it by re-reading the row,
recorded `commit_attempts: 1, verify_confirmed: false`, **did not retry**, and queued it.
An automation that equated "I clicked commit" with "the transaction succeeded" would have
reported that case as done.

**Run B — why it differs, and why that is the system working.** Run B queued a **fifth**
case that is **not** one of the seeded four: `P10-07054374-002` (row 2), code
**`PATTERN_MISMATCH`** at stage `precheck`, with **`commit_attempts: 0`**. **[MEASURED]**

Its cause is in the record: the reviewer used **EDIT** and typed `emp_id` as `V30018`. The
definition's field schema requires `^V\d{4}$` — four digits, not five — so the precheck
refused the case **before any write reached the portal**.

That is an **unscripted** failure: nobody seeded it, and it came from the human, not the
machine. The guard caught it anyway, at the earliest stage, with zero commit attempts. Run B
is therefore **evidence that the defensive path generalises beyond the failures it was
designed against** — which is the whole claim of §6.2 — and not an inconsistency with Run A.
It also shows the cost side honestly: one more exception drops the saving from ≈56% to
≈41%, because a queued case is charged the full manual cycle (§5.2).

---

## 4. Why this implementation form

**Deterministic Playwright script + JSON process definitions + a human review UI.**

### 4.1 Why not an AI agent at runtime

The task warns against defaulting to an agent, and the measurements say the same thing. This
loop is **data entry**: click a row, write one templated sentence, click commit.
**[MEASURED]** `variant_rate` 0.167, `copy_paste_ratio` 0.963, `paste_source_in_portal`
0.947, `template_conformance` 0.896.

**There is no natural-language understanding in that loop for a model to contribute.** What
a model *would* contribute is non-determinism into a write path, when the client's
requirement is the opposite: the same input must produce the same write on every run, and
the audit trail must say why each value was written.

It would also make the failure story strictly worse. A model is *capable* of guessing its
way through an unrecognised case — which is exactly the behaviour that must not exist when
the portal's error semantics are unknown (§6.2). A deterministic engine that stops is safer
than a capable one that improvises.

**The two phases, kept distinct — there is no contradiction between them:**

| Phase | AI / ML used? | Evidence |
|---|---|---|
| **Analysis & discovery** (steps 1–2) | **No model of any kind.** Process identities in dataset B are discovered from B's own rendered screen text; the readable label is a **fixed transliteration table** of the screen names the portal renders (`src/labels.py`). No clustering model, no embeddings, no LLM. | `requirements-step3.txt` lists only `playwright` and `streamlit`; steps 1–2 are standard-library only |
| **Runtime** (step 3) | **None.** The engine is deterministic and config-driven. | `llm_in_runtime: false` on every audit record of both runs |
| **Building the project** | **Yes** — Claude Code read Japanese screen text, drafted code and drafted these reports. | Declared per day in `WORKLOG.md` |

So "no LLM" is a statement about **what ships and what runs**, not a claim that no AI was
used to write it. The first two rows are the product; the third is the toolchain.

### 4.2 Why not the other forms

| Alternative | Why not |
|---|---|
| **Pure RPA / recorded browser automation** | Brittle without access to the real system, and it has no place to put the verify-and-queue logic. The fragile part here is **positional row selectors** (§6.1) — a recorder bakes that in with no detector. |
| **n8n / Power Automate** | Both handle the happy path. Neither gives a review surface where a human corrects a field *before* it commits, and both bury the verify-and-stop rules in a GUI. The governance questions in §6.5 are answered by reading a definition file and ~590 lines of Python, not by reading a flowchart. |
| **A packaged desktop app** | Packaging, signing and update cost for a prototype whose purpose is to prove a procedure is automatable. The engine already runs headless from a scheduler — that is the deployment shape that matters. |
| **A single-purpose hard-coded script** | Throws away the shared DOM contract across all twelve processes (§3.2) and saves nothing. |

### 4.3 Human-in-the-loop, not human-on-the-loop

Nothing commits without a person pressing **APPROVE**, **EDIT** (correct a value first — the
corrected value is what commits) or **FLAG**. That is a deliberate constraint, not a missing
feature: with the portal's failure behaviour unknown (§6.2), the reviewer *is* the
error-handling strategy for anything the definition does not recognise.

---

## 5. What stays manual, and the realistic expected impact

### 5.1 **[MANUAL]** after deployment — this does not shrink to zero

1. **The exception queue.** Every case the engine refuses — **4 of 18 in Run A, 5 of 18 in
   Run B** (§3.3) — each surfaced with its case id, worklist row, failure code, the reason
   in words, commit attempts and verify status.
2. **Flagged cases.** Anything the reviewer refuses.
3. **The review itself.** Approve / edit / flag is a person's decision, by design.
4. **The final sign-off on forcing a queued case through.** The automation never decides
   that a case it could not verify should be committed anyway.
5. **Ownership of the queue.** An automation with no named human behind it silently becomes
   a backlog. This is a client decision (§6.5).

### 5.2 Expected impact — a **relative ratio**, not a production ROI

```
before = median manual cycle × cases
after  = Σ automated (engine seconds + review seconds)
       + Σ queued    (review seconds + FULL manual cycle)
```

A queued case is charged the **entire** manual cycle on top of its review time, because it
saves nothing — a person still does the whole case. This is why the exception count costs
something in the number rather than being quietly excluded.

**The headline figure, and the one run it comes from:**

> **≈56% of hands-on time removed.** Run A — `before = 11.0 s × 18 = 198.0 s`,
> `after = 87.6 s`, **14 automated / 4 queued**. **[MEASURED]**
> Produced as: **reset → 3 live approvals → 15 batched**, recorded in
> `build/audit_log.jsonl` under portal epoch `755859baf586` (4 engine invocations).

**Run B, for comparison:** ≈41% (`after = 116.5 s`, **13 automated / 5 queued**), portal
epoch `bc555a988b9f`. The whole 15-point gap is the one extra exception — a queued case is
charged the full manual cycle, so the fifth exception costs 11.0 s of "before" that never
converts. **That sensitivity is the honest shape of this metric**: it falls as soon as the
system refuses more work, which is exactly what it should do.

The figure also moves with **how much a person actually reviewed**. Review seconds are
charged in full, so a run reviewed case-by-case scores lower than one mostly batched, and a
batch-only invocation with **zero** review time charged scores higher than either. Build
notes §2.7 and §5c.9 record other runs of this shape in the ≈56–58% band. **Quote Run A, and
say which run it is.**

**Three reasons this must not be quoted as a production ROI:**

1. **[MEASURED]** The **11.0 s baseline is real** — the median over **77 observed
   executions** (`step2_process_metrics.csv`). But it comes from a **test-environment
   recording whose waits are compressed by a known-ish factor** (`dwell_scale 1.4`, step-1
   limitation 7). Real cycles are longer, which makes the baseline — and the saving —
   **conservative**.
2. **[ENGINEERING ASSUMPTION]** The mock's own seconds are **not on that clock at all**. A
   local stdlib HTTP server with no auth, no network latency and no page weight is faster
   than the real portal, which makes the saving **optimistic**.
3. The two distortions push in **opposite directions** and neither is invertible.

**Do not multiply this percentage by a headcount or an hourly rate.** What it is good for is
putting the exception count in the same units as the benefit — which is what a client
conversation actually turns on.

**And the queue rate will be worse on real data.** The 4-in-18 exception rate is a property
of *seeded* failures. Real values will contain half-width digits where the template expects
full-width, suppliers in no enum, amounts formatted unexpectedly. Those go to the queue,
which is correct — but **nobody should plan on 4-in-18** (§6.3).

---

## 6. Rollout risks and mitigations

### 6.1 Positional row selectors — **[MEASURED]**, and only partly mitigated

**Evidence.** Every process in this portal selects its case with `tr:nth-of-type(N)` and
**no case id appears anywhere in the row's DOM** (`step2_analysis.md` §8.2). This is
universal across all twelve processes.

**Risk.** An automation built on row position is correct only while the worklist's sort
order, filter and pagination are identical to what the reviewer saw. This is **the single
most likely thing to break the build on a real screen**.

**Mitigation, and it is in the build.** The engine re-reads column 1 after locating the row
and refuses the case with `ROW_IDENTITY_MISMATCH` if the id is not the one the human
approved. The mock reproduces the positional fragility **on purpose** rather than inventing
semantic row ids the real screen does not have.

**It is a detector, not a fix.** It cannot help if two rows share an id, and it does nothing
about a worklist that re-sorts *between* the read and the commit. **The real mitigation is a
portal change — expose the case id in the row — and that is a client-side ask.**

### 6.2 Unknown error behaviour — **[ENGINEERING ASSUMPTION]**, the largest risk in the build

**Evidence: there is none, and that is the finding.** **[MEASURED]**
(`failure_path_evidence` in `step2_metrics.json`):

| Where a failed case would have to show up | Observed in 684 cases |
|---|---:|
| `browser_error` events, total | 38 |
| …inside a segmented case | **0** |
| …carrying any text | **0** |
| Error wording rendered into the portal, inside a case | **0** |
| Cases committing more than once (a retry or duplicate) | **0 of 684** |
| Cases with no observed commit at all | 57 of 684 |

All 38 `browser_error` events are empty-text and sit at the three portal roots — page load,
not case failure. The 57 no-commit cases are most consistent with a **boundary artefact**
(step 1's boundary F1 is 0.858), but the logs cannot separate "the commit fell outside the
segment" from "the operator gave up", and that is the honest statement of the gap.

**What follows.** The portal's failure behaviour **cannot be specified from this data** and
no further analysis of these logs will produce it. So the failure branch is made safe **by
construction rather than by coverage**:

> **Commit once — never retry blind. Verify the write landed by re-reading the row. Stop and
> queue for a human on anything the definition does not recognise.**

With **no case in the data committing twice**, there is no evidence anywhere that a second
commit is even idempotent — so the engine never attempts one.

**The honest asymmetry:** that branch is plausibly **a third of the build effort and 0% of
the observed logs**. Any estimate of how long a Step-3 build takes should be read with that
in mind. The ranking is undisturbed — the blind spot is identical for all twelve processes.

### 6.3 Procedure recovered, values synthetic — **[MEASURED]** structure, **[MOCKED]** values

The loop shape, selectors, field names, status vocabulary and note template are **recovered
from dataset B's own logs** and are as solid as 684 segmented cases make them.

The **content is invented, by necessity**. `clipboard_change` events record
`text_length` and **`text_content` is null in all 872 of them** — the payload was never
captured, so no method recovers the real values from these logs. **[MEASURED]**

**Consequence, stated plainly:** this prototype demonstrates that **the procedure is
automatable**. It does **not** demonstrate that **the client's actual data is clean enough
to run through it**. First contact with real data will produce a higher queue rate than
4-in-18.

### 6.4 Environment and host risks — **[MEASURED]**, and the ones that actually cost the most

Step 2 predicted the failure branch would be the expensive part. In practice the expensive
part was **the machine the thing runs on** — none of which is visible in the operation logs:

- **A space in the host username** (`C:\Users\Aanchal Shah`) broke an `os.execv` re-exec on
  Windows, where the CRT joins the argument vector into an unquoted command line. The engine
  launched nothing and every case stayed pending. Fixed by **removing the re-exec entirely**
  and OS-gating the shim (build notes §5b.5).
  **[MEASURED] This is the cleanest example in the project of a risk that exists only at
  implementation time:** a Unix re-exec idiom that is correct on POSIX silently corrupted the
  process launch on a Windows path containing a space, it is invisible in every column of the
  step-2 analysis, and it was caught only because the review UI surfaces the child process's
  stderr instead of swallowing it. **[ENGINEERING ASSUMPTION]** No amount of further log
  analysis would have predicted it — which is the argument for piloting on a client machine
  rather than a developer's.
- **A cp1252 console** could not encode the Japanese this program prints; both the engine and
  the portal died on it. Both now force UTF-8 (§5b.6).
- **Two portal processes bound to one port.** `SO_REUSEADDR` means something different on
  Windows, so a second portal started **silently** and RESET, the engine and the reviewer's
  tab could each describe a different demo (§5c).

**Mitigation, generalised:** the target identifies itself (`server_id`, `epoch`), that
identity is recorded in every audit record, and **the engine refuses to write to a portal
the reviewer is not reading**. On a real rollout "two servers behind one URL" becomes
"staging versus production" — the defence is unchanged. **[ENGINEERING ASSUMPTION]**
A rollout onto client laptops will hit this class first and hardest: localised Windows
installs, OneDrive-redirected home folders with spaces, deep corporate paths. **The
mitigation is not cleverer code — it is running it on a machine that is not the
developer's before calling it done.**

### 6.5 Governance — **[ENGINEERING ASSUMPTION]**, and these are the client's to settle

Three questions the logs cannot answer, unchanged from step 2 §7.5 and **not** solved by this
build, because they are not engineering questions:

1. **Who owns the exception queue?** An automation with no named human behind it becomes a
   silent backlog.
2. **What does the automation authenticate as?** The logs show an *operator's own session*. A
   service account with its own permissions is a different governance object from a person's
   login.
3. **What must the audit trail contain?** `sensitivity 0.20` assumes a purchase order is
   reversible — which is only true if there is a record of what was written and by which run.

The audit log (one record per case: read, edited, written, committed, verified, timed,
`portal_server_id`, `portal_epoch`, `llm_in_runtime`) is a **proposal** for the third, not an
answer to it.

### 6.6 Two further limits worth naming

- **The sensitivity table is a judgement, and it moves the answer.** **[ENGINEERING
  ASSUMPTION]** It is the only unmeasured input to Client_ROI. `fin_purchase_order_management`
  is scored 0.20 because a PO against a registered supplier is operational and reversible. **If
  the client's finance function treats any PO as committed spend, that number rises and the
  ranking must be re-run** — it is one block in `src/roi.py` for exactly that reason.
- **There is no ground truth for dataset B.** Every case count inherits step 1's boundary
  accuracy, which was measured on dataset A (**boundary F1 0.858 at 2 s, mean IoU 0.865, 91.0%
  of executions matched at IoU ≥ 0.5, label ARI 0.912**, `validation_A.json`). Those are the
  best available estimates of B's accuracy, **not measurements of it**.
- **One column family was measured that the mock does not use.** **[MEASURED]** The 発注管理
  worklist was captured with two column sets (6-column in 4 captures, 7-column in 1). The mock
  uses the 7-column family because 種別 is the branch flag. If the real screen renders the
  6-column form, that is a **definition edit, not a code change** (build notes §8.4).

---

## 7. How the seven days were spent, and why

| Day | Date | What it went on |
|---|---|---|
| **1** | 09-13 | The brief, the data schema, environment. Decision that set everything after it: **measure first, then build.** |
| **2** | 09-14 | **Step 1** — recovering units of work. Segmentation method, validation against dataset A's ground truth, `segments.jsonl`. |
| **3** | 09-15 | **Step 2** — measuring 12 processes on 43 quantities each, the two scores, the ranking, the robustness re-runs. **Recommendation made.** |
| **4** | 09-16 | **Step 2 self-audit before building.** Read the report back against the brief's feasibility questions; found two gaps and closed both — asserted paste-source became **measured** (§3.1), and the happy-path blind spot became an explicit section (§7.5). **Target locked here.** |
| **5–6** | 09-17/18 | **Step 3 build** — mock portal, engine, review UI, definitions, audit log. A real share of these two days went to **making it run end-to-end** rather than to features (§6.4). |
| **7** | 09-19 | Verification and this report. Re-ran the checkers, consolidated four reports into one, fixed the README for a fresh clone. |

**Where the target was locked, and why.** At the **end of Step 2, after the Day-4
self-audit** — before a line of Step-3 code. Locking it there is what keeps the ranking
honest: choosing the process *after* starting to build invites picking whatever turned out
to be convenient. It is also why `hr_attendance_leave_request` was **not** chosen despite
having the best Build_Fit in the set (§2.4).

**On the Day 5–6 split.** The three bugs in §6.4 — host username, console codepage, duplicate
portal — cost a material share of the build. That is recorded rather than tidied away because
it is the most transferable finding in the project: **the analysis predicted the wrong
expensive thing.** Step 2 argued the failure branch would dominate; the environment did.

**Verification run on Day 7** **[MEASURED]**:

- `src/qa_segments.py` — **14 checks, all pass**. 684 segments, 15 sessions, 12 labels; no
  overlaps, no duplicates, no impossible durations; 163 of 176 recorded minutes (93%).
- `src/verify_step2.py` — **235 checks, 0 mismatches** between the step-2 report and the
  generated artefacts.

---

## 8. Honest summary

| | |
|---|---|
| **Genuinely works, end to end** | the engine's full read → precheck → write → confirm-note → commit-once → verify-by-read-back loop; approve / edit / flag with EDIT changing what commits; the exception queue with all four seeded failures landing in it; no double-commit, verified by replay; counters derived from portal state + audit log; the relative time-saved figure; the audit log |
| **[MOCKED]** | the portal (no access to the client's system) and **every case value** (never logged — `text_content` null in all 872 clipboard events) |
| **[MEASURED] and real** | the *structure* — columns, field names, status vocabulary, note template, the `#rt-table` / `#rt-note` / `#btn-rt-ok` selector contract — recovered from dataset B's own logs |
| **[MANUAL] after deployment** | the exception queue, flagged cases, the review itself, and the decision to force a queued case through |
| **[ENGINEERING ASSUMPTION]** | the entire failure branch — **0 failures in 684 observed cases** — and all three governance questions |
| **Explicitly deferred** | the other eleven processes; the second definition exists as a stub the engine refuses to run |
| **Two runs, not one staged number** | **Run A 14/4 (≈56%)** and **Run B 13/5 (≈41%)**, both traceable to their portal epoch in `build/audit_log.jsonl` (§3.3). Run B's fifth exception was **unscripted** — a reviewer edit caught at precheck with zero commit attempts |

**The recommendation.** Automate `fin_purchase_order_management` first, with a human in the
loop, on a deterministic engine that stops rather than guesses. **Resolve the P1/P4 split
before touching `hr_expense_and_pay_change`**, and get the case id exposed in the worklist
row before trusting positional selectors at volume.
