# Work Log

A short record of what I was thinking, what I tried, what did not work, and the decisions I made during the project.

---

## Day 1 - 2026-09-13
### Reading the brief and setting up

### What I was thinking

The first day was mainly about understanding the task before touching the data.

The main thing I realised was that **Step 1 is a foundation rather than just another deliverable**. If the process boundaries are wrong, then the process frequencies and time estimates in Step 2 can also be wrong, which could eventually lead to choosing the wrong automation target.

I also kept coming back to the point in the brief that **Dataset A should not simply be assumed to transfer to Dataset B**. I wanted this to influence the way I approached the project from the beginning.

### What I did

- Read the project brief and understood the three main steps.
- Read `DATA_SCHEMA.md` and noted the warnings about the data and ground truth.
- Looked through the dataset structure: 63 sessions in Dataset A and 15 in Dataset B.
- Found that the data is large (~4.4 GB), and one `events.jsonl` was already difficult to inspect directly in an editor, so I decided to use scripts for data exploration from the start.
- Set up the Git repository and made the initial commit.
- Decided to keep the raw datasets out of Git, generated/intermediate files in `build/`, code in `src/`, and results in `reports/`.

### What I deliberately did not do

I did not start building the segmentation algorithm on Day 1.

The data specification itself says that the ground truth should be verified, so I did not want to treat `gt.jsonl` as unquestionable simply because it was provided for evaluation.

I also did not choose an automation target yet. I wanted that decision to come from Dataset B rather than from an interesting-looking process I happened to notice early.

### AI usage

I used AI only for translating the Japanese process names so that I could understand the data better.

### Rough plan

My initial plan was:

- **Day 1:** understand the brief, data, and setup
- **Day 2:** Step 1 segmentation
- **Days 3–4:** Step 2 process and ROI analysis
- **Days 5–6:** build the automation prototype
- **Day 7:** testing and final report

I expected this plan to change once I started working with the actual data.

### End-of-day decision

The main decision from Day 1 was:

> **Measure first, then build.**

---

## Day 2 - 2026-09-14
### Understanding the event stream and building Step 1

### What I was thinking

Today I wanted to answer one question before building too much:

> **What does one actual process execution look like in the raw event stream?**

Since Step 1 affects everything that follows, I wanted to understand which signals were actually reliable instead of immediately choosing a complicated segmentation method.

### What I found first

I profiled the event stream and found several data-quality issues that directly affected the implementation:

- Events are not always stored in timestamp order, so I sorted them by timestamp before doing time-based analysis.
- `context.active_app` can be stale, so I used the actual application-switch information instead.
- Clipboard and browser form-input text are essentially unavailable, so I could not depend on the text entered by the user.
- Some sessions have very little browser-level information, so I needed a fallback rather than simply dropping them.
- Screenshots are incomplete, so I did not make the segmentation method dependent on them.

I also checked the ground truth before using it for evaluation. There were missing end times and duplicate start events, so I reconstructed the reference intervals from the ground-truth event stream rather than blindly trusting the provided manifest.

### What I tried

I started with relatively simple segmentation ideas:

- time gaps
- application changes
- browser activity
- fixed/interpolated boundaries
- timing combined with application/process context

These were useful as baselines, but they did not handle the actual behaviour well enough.

### What did not work

My first assumption was that a period of inactivity would usually mean that one process had ended.

That turned out to be too simplistic.

Some quiet periods occurred **inside** an execution, while consecutive executions could occur almost immediately after one another. Application switching also did not necessarily mean that the business process had changed.

I also initially focused too much on getting an exact boundary timestamp. The event timing itself has some jitter, so optimising very small boundary differences was not particularly useful.

### What changed my approach

The strongest signal in Dataset A turned out to be the **business application/portal context**. The combination of portal and route information gave a very strong indication of which process was being performed.

This was much more reliable than trying to infer the process entirely from mouse and keyboard activity.

At the same time, I checked what would transfer to Dataset B. Dataset A has useful case IDs and semantic button names that are not available in the same form in B. I therefore avoided making those signals essential to the solution.

### The main segmentation insight

The important question became not just:

> "Where is the next process?"

but:

> **"Which process should own the inactive time between two pieces of activity?"**

When I compared the predicted segments with the ground truth, I found that most consecutive executions were very close together, while some longer quiet periods were actually inside an execution.

This led me towards a **tight start + trailing absorption** approach: keep the beginning of an execution relatively tight, while allowing the process containing the final committing action to absorb trailing inactive time when the surrounding context supports it.

This gave a much better match than simply splitting the timeline at inactivity gaps.

### Handling weaker sessions

Some sessions had no useful browser extension information.

I first tried using browser -> Excel/Notepad -> browser excursions as a fallback for identifying case executions. This performed poorly, so I removed that approach.

Looking more closely at the affected sessions showed that the browser context itself was also missing. I therefore added another context channel using:

- window titles
- OCR breadcrumbs
- screen/route information learned from sessions where URL and screen information were both available

This gave the fallback a more meaningful signal instead of trying to infer a process only from application movement.

### Dataset B check

While checking B, I found that the largest process group appears to contain two different business objectives. I looked for a reliable signal to split them, but the available information was not sufficient to make that split confidently.

I decided **not to guess**. I kept the group together and documented it as a limitation rather than creating labels that I could not justify.

### Other checks

I also tested whether sequence similarity/clustering should be used to merge or split processes.

One similarity test gave very high similarity between two processes that were clearly different business workflows. The common pattern was mainly a shared interaction sequence such as clicking a row, pasting information, and confirming.

This showed me that behavioural similarity alone could produce misleading process merges, so I did not use it to redefine the labels.

### Final decisions for Step 1

- **No machine learning.** The portal context was already a very strong process signal, so adding ML would increase complexity without a clear benefit.
- **No supervised classifier trained on Dataset A labels.** Dataset B contains different processes, so I did not want to build something that depended on A's labels.
- Use relative timing rather than fixed absolute margins so the approach is more portable between datasets with different execution speeds.
- Keep a degraded fallback path for sessions with missing browser information rather than losing those sessions completely.
- Stop chasing extremely small boundary differences because the underlying event timing itself has noticeable jitter.
- Do not split processes unless there is enough evidence that they represent genuinely different workflows.

### Where the day went

Roughly:

- **40%** — measuring and understanding the data
- **35%** — building and improving the segmenter
- **15%** — handling extension-less/degraded sessions
- **10%** — validation and documentation

The initial data investigation took a significant part of the day, but it prevented me from building around signals that only existed in Dataset A.

### AI usage

Claude Code was used as an implementation and analysis assistant for diagnostic scripts, data processing, debugging, and interpretation of Japanese screen text and window titles.

I made the engineering decisions based on the observed data and validation results rather than accepting model suggestions without checking them.

### Step 1 output and repository cleanup

By the end of the day, the final `segments.jsonl` output had been generated.

During the repository setup, I initially stored `segments.jsonl` using Git LFS because I was treating it like a larger generated output. After checking the actual file size (~102 KB), I realised LFS was unnecessary and could make it less convenient for an evaluator to inspect directly on GitHub.

I therefore removed `segments.jsonl` from Git LFS and moved it back to a normal Git-tracked file. This keeps the final output simple and directly viewable in the repository, while the much larger raw datasets remain excluded from Git.

### End-of-day decision

I had a working direction for Step 1 and, more importantly, a clearer understanding of **which signals were reliable and which were misleading**.

The next step is to use the resulting segments to understand Dataset B: which processes occur, how often they occur, how much time they consume, who performs them, and which ones are actually worth automating.

---

## Day 3 - 2026-09-15
### Measuring dataset B and building the ranking


The key question was:

> **What would make an automation ranking wrong, and can I measure my way out of it?**

I started by separating the problem into **two scores**: `Client_ROI`, which answers the client's question, and `Build_Fit`, which captures my implementation constraints. I deliberately kept them separate so I would not recommend something simply because it was easier to build.

### What the Data Changed

The obvious impact formula was:

**frequency × duration × people affected**

However, the operator term did not hold up. The four recording machines covered almost all processes, but this reflected how the data was captured rather than how the work was actually staffed. I therefore reported operator count separately and excluded it from the score.

The most important distinction was inside the Word-document time. Some documents were **規定 / 手続き** (regulations or procedures requiring judgment), while `getsujitsu_teigaku_torihikisaki_ichiran` was a fixed monthly **list** that could be treated as lookup data.

Separating these changed the judgment factor for `fin_invoice_approval` from about **0.19 to 0.03**. Unknown document types were kept separate rather than guessed into either category.

I also found that measuring integrations as a union across all cases made almost every process look like a 10-way integration. Requiring a surface to recur in at least **10% of cases** fixed this and changed the top ranking.

I separately corrected a duration inflation caused by using an extended timestamp window for both event attachment and duration measurement.

### Robustness

There was one unresolved issue from Step 1: `hr_expense_and_pay_change` may actually contain two processes.

New OCR evidence showed a clean **12/12 split** between P1 and P4 rows, so I tested the worst-case 50/50 split rather than guessing.

I then reran the ranking under three different conditions, including:

- Splitting the conflated label 50/50
- Removing the degraded session
- Discarding thin worklist evidence

**The same process remained the recommendation in all four views**, with margins of **1.4×–2.2×**.

Removing the lowest-confidence session actually widened the winner's margin.

### Recommendation

The recommended target is:

**`fin_purchase_order_management` (発注管理)**

It has the highest `Client_ROI` and the third-highest `Build_Fit` (0.80, behind `hr_attendance_leave_request` 0.97 and `ops_it_access_request` 0.85), making it the right Step-3 target without sacrificing the client's objective.

The volume leader came second despite having **1.7× as many cases**.

This reinforces the central point:

> **Being the biggest pile of work is not the same as being the best thing to automate.**

`hr_attendance_leave_request` was the easiest process to build, with a `Build_Fit` of **0.97**, but its `Client_ROI` was only one-third of the winner's. I therefore deliberately did not choose it.

### Where the Day Went

Roughly:

- **45%** — Measuring Dataset B: dwell timelines, clipboard character counts, document classification, variant channels, and selector/route inventory
- **20%** — Designing the scoring model and challenging the operator term
- **20%** — Robustness re-runs and investigating the conflated process evidence
- **15%** — Writing the report and verifying every number against the generated CSV

The verification pass was worth the time: it caught **two stale figures** and the table corruption before the final result.

### AI Usage

Claude Code was used as an implementation and analysis assistant for the measurement passes over the event cache, scoring module, robustness re-runs, and interpretation of Japanese screen text and document names.

The key judgments remained mine:

- Dropping the operator term
- Separating 規定 from 一覧
- Keeping `Client_ROI` and `Build_Fit` separate
- Including the governance sensitivity table
- Refusing to hide the positional-selector risk inside a scoring factor

The sensitivity table is the only unmeasured input in the model, so I kept it in one block in `roi.py`, allowing a reviewer to change the assumption and immediately re-rank the processes.



---

## Day 4 - 2026-09-16
### Self-audit of Step 2 before starting the build

Before starting Step 3 I read the Step-2 report back against the brief's feasibility
questions — how would the data be accessed, how complex is the business logic, what
operational and governance constraints apply, what risks only surface once implementation
begins. The branching and governance questions were answered. Two were not, and both were
answerable from data I already had.

### Gap 1 - I asserted where the pasted content came from instead of measuring it

`copy_paste_ratio` carried a lot of weight in `Automatability`, and the sentence holding it
up was "content that was pasted came from somewhere a program can also read." That is an
inference, and `clipboard_change` records the answer directly: the event fires at the
*copy*, so the foreground application at that instant is the surface the content came out
of.

Measuring it turned up something I had not expected. Two channels disagree on 12.4% of the
865 in-case clipboard events, and the disagreement is one-directional - `context.active_app`
reads Edge where the foreground timeline has already moved to Notepad, which is the same
one-step lag I documented in `common.py` on Day 2. So I made the timeline the primary
channel and kept the `ctx` reading in its own column rather than picking the flattering
number: the honest portal share for the recommended target is **0.95, not 1.00**.

The column that actually decides a build turned out to be a different one. Splitting the
sources into portal / note pad / **document**:

- `fin_purchase_order_management` — **0.00 document-sourced.** No Word, no Excel, no file.
- `fin_payment_processing` 0.38, `fin_manager_expense_approval` 0.32,
  `ops_contract_management` 0.31, `hr_onboarding` 0.31 — the four processes I had already
  deferred as judgment-heavy.

I did not fit anything to produce that. `judgment_step` is a dwell measurement and this is
a clipboard count, and they land on the same four processes — a case whose handling depends
on a 規定 is a case whose text is copied out of that 規定. The note-pad share is not an
integration cost and I said so explicitly, because `ops_inventory_management` at 0.48 looks
alarming until you notice the note pad holds no data of its own.

### Gap 2 - every case I measured is a happy path, and I never said so

Four places a failed case would have to leave a trace, all empty: 38 `browser_error` events
but **0 inside a segment** and 0 carrying any text (they sit at the three portal roots -
page load, not case failure); **0** error strings rendered into the portal inside a case;
**0** of 684 cases committing twice.

So the portal's failure behaviour cannot be specified from these logs, because it was never
recorded. That is the risk the brief asks about that only surfaces once implementation
begins, and no further analysis of this data produces it.

What I could not resolve honestly: 57 of 684 cases show no commit click at all. I wanted
that to be a clean zero. It is not, and I wrote it down rather than leaving it out -
`commit_rate` tracks `template_conformance` almost exactly, which is what a boundary
artefact looks like rather than what an abandoned case looks like, but the logs do not
separate the two.

New section 7.5 states the happy-path measurement, the defensive design it forces (commit
once, verify the write landed by re-reading the row, stop and queue for a human on anything
unrecognised - tagged as an engineering assumption, not a finding), and the asymmetry I
think matters most: that error branch is plausibly a third of the build effort while being
0% of the observed logs, and it is invisible in every column of the ranking table. It does
not disturb the ranking - the blind spot is identical for all twelve processes but it
should be read alongside any estimate of how long Step 3 takes. I also added the three
governance questions the logs cannot answer (who owns the exception queue, what the agent
authenticates as, what the audit trail must contain).

### Verification

The Day-3 verification pass was manual and it caught a corrupted table late. I did not want
to repeat that, so this time the report's tables are generated (`report_tables.py`) and
checked by a script (`verify_step2.py`, 235 checks across sections 2.2, 4, 5, 3.1 and 7.5).

It immediately earned itself: it caught `0.1836` written into section 5 as `0.183` when
correct rounding is `0.184`. A figure I had verified by hand on Day 3 and read past.

**Nothing in the ranking moved.** Both additions are measurements, not new scored inputs:
0 pre-existing CSV cells changed, 0 ranking fields changed, the JSON gained one key, and
re-running `rank_b.py` produces byte-identical output.

### AI Usage

Claude Code ran the audit passes over the event cache (clipboard source cross-tab,
`browser_error` placement, commit counts) and drafted the two report additions.

The judgments were mine: making the conservative clipboard channel primary once the two
disagreed rather than quoting the 1.00, splitting the sources by *document* rather than by
"in portal / not in portal" because the document share is the one that costs a build,
writing the 57 uncommitted cases down instead of leaving them out, and keeping the
defensive error design tagged as an assumption rather than presenting it as something the
data told me.


## Day 5,6 - 2026-09-17 & 2026-09-18

### Step 3 - From feasibility to a working automation and debugging

After completing the Step-2 feasibility audit, I moved from measuring the workflow to proving that `fin_purchase_order_management` could actually be automated. I deliberately chose a deterministic, configuration-driven automation rather than introducing an LLM into the runtime path. The objective was to build the smallest system that could demonstrate the measured workflow end-to-end while remaining auditable and safe around failures.

The core workflow was reduced to:

`REVIEW → APPROVE / EDIT / FLAG → SELECT CASE → WRITE FIELD → COMMIT → RE-READ → VERIFY → DONE / HUMAN EXCEPTION`

This kept the automation aligned with the observed interaction motif rather than building unnecessary generality.

### Mock portal and realistic interaction contract

I built a one-screen Japanese `発注管理` portal containing a worklist and detail pane. The underlying case values are synthetic because the original logs do not expose the actual business values.

The portal deliberately preserves the fragile interaction characteristics identified during Step 1, including positional row selectors such as `tr:nth-of-type(N)`. This makes the prototype test the actual automation contract identified from the logs rather than an artificially clean DOM.

The automation definition is configuration-driven, with selectors and field mappings separated from the execution engine. This makes the engine reusable without turning the prototype into a generic autonomous browser agent.

### Human-in-the-loop design

I did not treat every case as automatically executable.

The Streamlit layer provides three explicit decisions:

- **APPROVE** — execute the proposed action.
- **EDIT** — modify the proposed value before execution.
- **FLAG** — route the case to a human exception queue.

I also added per-field source indicators and compact execution status so that an evaluator can understand the workflow without reading the implementation.

The main UI was intentionally kept lightweight. Detailed methodology, assumptions, synthetic-data disclosure, and limitations were moved into a collapsed honesty section so that transparency is preserved without turning the demo into a report.

### Designing for the failure mode the data could not show

The Step-2 logs showed **0 observed in-case portal failures across 684 cases**, so the logs could not tell me how a real portal would behave when a commit fails, a field is rejected, or verification disagrees.

Rather than pretending that this behaviour was measured, I implemented it as an explicit engineering assumption:

**commit once → re-read → verify → stop on uncertainty → human exception**

The engine never blindly retries a failed or ambiguous commit. This prevents a verification problem from becoming a potential double-submission.

I also added explicit startup and server-mismatch failures so that an infrastructure problem cannot silently appear as a successful business transaction.

### Debugging the system exposed problems that offline analysis could not

The first end-to-end implementation revealed several issues that were not visible in the event analysis.

The Streamlit subprocess initially deadlocked because Chromium generated enough stderr output to fill the pipe while the parent process was waiting on stdout. I fixed this by draining stderr independently.

The next issue was Windows-specific: the Python executable path contains a space because of the local username. A POSIX-style `execv` re-execution approach therefore failed on Windows. I removed the re-exec mechanism and kept process launching in normal list form using `sys.executable` with `shell=False`.

Japanese text then exposed another environment-specific issue: Windows `cp1252` could not encode the portal's Japanese output. The portal and engine were switched to explicit UTF-8 handling.

These were useful failures because they demonstrated that a workflow can be logically correct while still being operationally unreliable.

### The major architectural bug - two portals, two realities

The most important bug was a state-consistency problem rather than an automation problem.

Two portal processes could initially bind to port 5233 because of Windows socket reuse behaviour. Since the mock portal stored state in memory, the two processes had different `_STATE` objects. This meant the UI, browser, and automation engine could potentially observe different versions of reality.

I treated this as an architectural issue rather than patching individual symptoms.

The final design establishes the portal as the **single source of truth**:

- Only one portal instance can bind to the target port.
- Startup performs a pre-bind check.
- The portal exposes a unique `server_id`.
- Streamlit reads live portal state rather than maintaining an independent case state.
- The engine is pinned to the same `base_url` and expected `server_id`.
- RESET is performed through the portal itself.
- UI counters are derived from portal state plus the audit log.
- An automation is only counted as successful when the portal corroborates the resulting state.

This eliminated the possibility of the UI saying "automated" while the actual portal remained unchanged.

### Preventing false state after refresh or restart

An earlier Streamlit implementation used a session-local `handled` set. This created a subtle failure mode: if the application restarted after an automation, it could forget what had already been processed and offer the same case again.

I removed the session-local state as the authority.

Instead, the application reconstructs the current decision from **live portal state + audit records**. This makes the system restart-aware and avoids treating Streamlit memory as transactional state.

I also added an invariant check:

**Total = Pending + Automated + Human Queue**

so that counter inconsistencies become an explicit error rather than silently producing misleading UI.

### Guarding the exhausted state

I added a specific guard for the case where no `未処理` cases remain.

Instead of spawning an automation process that has nothing to do, the UI displays:

**"Nothing committable — press RESET DEMO first"**

and disables batch execution.

This prevents a common demo failure: repeatedly pressing "Run" after the dataset has already been exhausted and accidentally generating misleading execution results.

### End-to-end verification

I tested the complete system from a fresh portal reset rather than validating individual components independently.

The fresh portal contained:

**18 total cases → 17 `未処理` + 1 `完了`**

Three cases were intentionally configured to exercise exception behaviour, meaning the expected automatable population was 14.

I first tested a single live approval and verified:

`未処理 → 登録済み`

The note was written, the resulting value was re-read successfully, exactly one commit was attempted, and the portal `server_id` matched the server expected by the automation engine.

I then performed three live approvals before running the remaining cases in batch. This provided a visible demonstration of both the human-review path and the automated path.

The final result was:

- **18 total cases**
- **14 automated**
- **4 human exceptions**
- **0 awaiting**
- **~56% relative hands-on-time reduction**

The portal itself independently reported:

`14 登録済み / 3 未処理 / 1 完了`

The three remaining `未処理` cases correspond to the seeded failure conditions rather than silently disappearing.

### Testing the verification-failure path

I specifically tested `P10-07054374-017` as a verification failure.

The result was:

- `commit_attempts = 1`
- `note_confirmed = True`
- `verify_confirmed = False`
- Portal status remained `未処理`
- No retry was issued

This was important because the system did not equate **"I clicked commit"** with **"the business transaction succeeded."**

The transaction is only considered automated when the expected portal state can be verified.

### Cross-session validation

I opened a fresh browser session against the already-used portal and reproduced the same state:

**14 automated / 4 human queue / ~56% relative time reduction**

This verified that the result was not merely being held in Streamlit's session state.

The accounting invariant also held:

**18 = 0 awaiting + 14 automated + 4 human queue**

### What I deliberately did not build

I deliberately avoided adding an LLM, autonomous selector recovery, speculative retry logic, or unnecessary external integrations.

The logs already provided enough evidence to build a deterministic happy-path automation for this process. Adding an LLM would have increased complexity and reduced determinism without solving an observed problem.

Similarly, the original logs did not provide enough information to safely define real failure semantics or production governance. Those remain explicit assumptions/open questions rather than features disguised as completed functionality.

### AI Usage

Claude Code was used as an implementation and debugging assistant. It helped develop the mock portal, Playwright engine, Streamlit interface, process handling, and verification logic, and helped inspect runtime failures.

The engineering decisions remained mine: selecting the deterministic architecture, deciding that the portal should be the single source of truth, identifying the duplicate-process issue as an architectural state problem, refusing blind retries, separating measured findings from engineering assumptions, and deciding what **not** to automate.

The final quantitative claims were validated through the actual end-to-end execution rather than inferred from the interface.

### Result

By the end of Day 5 and 6, Step 3 had moved from a feasibility claim to a **working, observable, failure-aware prototype**:

**Measured workflow → deterministic automation → human review → portal action → independent verification → auditable outcome**

The prototype does not claim to be production-ready. Its purpose is to demonstrate that the highest-value measured workflow can be automated with controlled execution, explicit uncertainty handling, and a clear boundary between what the data proves and what engineering assumptions are required.

---

## Day 7 - 2026-09-19

### Assembling the deliverables

Day 7 was the day I had planned for testing and the final report, and it stayed that way.
The work was consolidating four separate reports into one an evaluator can read start to
finish (`reports/FINAL_REPORT.md`), fixing the README so a fresh clone actually runs, and
checking that the numbers I have been quoting all week still come out of the files rather
than out of my memory of them.

The detail reports stay where they are. The final report references them rather than
restating them, because the depth is the point of having them.

### Verifying the repository rather than trusting it

I ran the two checkers instead of assuming they still passed:

- `src/qa_segments.py` - **14 checks, all passed**. `segments.jsonl` holds **684 segments
  across 15 sessions and 12 process labels**, exact field set `start / end / label /
  session_id`, no overlaps, no duplicates, no impossible durations, no >60 s silent gap
  inside a segment, every `session_id` resolving to a real session directory. Segment time
  is 163 of 176 recorded minutes (93%).
- `src/verify_step2.py` - **235 checks, 0 mismatches**. Every table in the step-2 report
  reconciles against the generated artefacts.

Both numbers agree with `step2_metrics.json` (`cases 684, sessions 15, processes 12`), so
the deliverable and the analysis are describing the same thing.

Checking the ranking numbers back against the CSV also turned up a figure I had been
repeating all week. I had called `fin_purchase_order_management` the **second** most
buildable process in the set. Sorting the `build_fit` column of
`step2_process_metrics.csv` puts it **third** - 0.80, behind `hr_attendance_leave_request`
0.97 and `ops_it_access_request` 0.85. The recommendation is unaffected, because it never
rested on that ordinal: the target is chosen on `Client_ROI`, where it is first, and
`Build_Fit` only has to be high enough that nothing needed deferring. But the number was
wrong in four places - the Step-2 report §0 and §7, the README, and my own Day-3 entry
above - and I corrected all four rather than leave a figure in the deliverables that the
CSV contradicts. **I have edited the Day-3 entry, which is the one piece of back-dated editing
in this log, and this paragraph is here so that is on the record.**

### Two runs, not one number

Day 7 was meant to be testing, and the thing I most wanted to avoid was shipping a single
staged number. So the report presents two runs, both read out of `build/audit_log.jsonl`
and both identified by their portal epoch, which is the unit of one seeded worklist.

**Run A, the headline** - epoch `755859baf586`: reset, three live approvals, then the
remaining fifteen batched. **14 automated / 4 queued**, `before 198.0s -> after 87.6s`,
**~56% of hands-on time removed**. The four queued cases are exactly the four seeded
unautomatable ones.

**Run B, the robustness check** - epoch `bc555a988b9f`: reset, four live approvals, then
fourteen batched. **13 automated / 5 queued**, ~41%.

The fifth exception in Run B is the interesting one, and it is not what I assumed when I
went looking for it. I expected another verify failure. The audit record says otherwise:
`P10-07054374-002`, code **`PATTERN_MISMATCH`**, stage `precheck`, `commit_attempts: 0`,
and `edits: {'emp_id': 'V30018'}`. That was **me**, using EDIT in the review UI and typing
an employee id with five digits where the definition's schema requires `^V\d{4}$`.

I like that result more than the one I went looking for. The four seeded failures test the
branches I wrote on purpose. This one was not seeded by anybody - it was a human error
introduced at review time, and the precheck refused it before a single character reached
the portal. It is the only evidence in the project that the defensive path generalises past
the failures it was designed against, which is precisely the thing §7.5 says cannot be
demonstrated from the logs.

It also shows the metric behaving correctly rather than flatteringly: one extra exception
drops the saving from ~56% to ~41%, because a queued case is charged the full manual cycle.
A number that did not fall there would be the wrong number.

**What I did not do:** scrub the 13/5 run. Reporting only Run A would have been a better
headline and a worse piece of engineering evidence.

### What did not work - the three Step 3 bugs that cost the most

Keeping the same framing as the earlier days: these are implementation risks I lived, and
they are more useful written down than tidied away. None of them were problems with the
automation logic. All three were problems with the *environment the automation runs in*,
which is exactly the class of risk the operation logs cannot show.

**1. A space in the machine's own username stopped the engine launching.** On the
evaluation machine, APPROVE returned *"The automation engine produced no run"* and stderr
said `C:\Users\Aanchal: can't open file 'C:\...`. All 18 cases stayed pending, the portal
was untouched, and pressing 登録確定 by hand then gave 「処理内容が未入力です」 - the portal
being correct, not a second bug.

I want to record the cause accurately, because my own first guess about it was wrong. The
`subprocess.Popen` in `src/app.py` was *already* a list with `shell=False`, so it was never
the problem. The broken call was `os.execv(sys.executable, [sys.executable] + sys.argv)` in
`engine.py`, which re-exec'd the interpreter to set `LD_LIBRARY_PATH`. On POSIX `execv`
takes a real argument vector and a space is harmless; **on Windows there is no exec** - the
CRT joins the vector into one command line without quoting, so `C:\Users\Aanchal Shah\...`
split at the space and `argv[0]` became `C:\Users\Aanchal`. Two things made it reachable:
the shim was not OS-gated, and `build/pwdeps/` is a Linux artefact sitting on a path Windows
can also see, so the directory test passed there too.

The fix was to delete the re-exec rather than to quote it. Chromium is a child process and
inherits `os.environ` at spawn, so setting the variable in-process is enough; the shim is
now `if os.name != "posix": return`, and there is no exec anywhere in the program. Behind
it was the same class of bug again: a Windows console defaults to cp1252 and every string
this program prints is Japanese, so the engine died with `UnicodeEncodeError` the moment it
wrote the note, and the portal died the same way on its own startup banner. Both now force
UTF-8 before writing anything. Full write-up in build notes **§5b.5-5b.6**.

**2. RESET, the engine and the browser tab did not share one source of truth.** A run could
report *"0 automated, 18 queued, negative saving"* while the portal visibly held a fresh
worklist, and a case approved in the UI could fail to change in a separately opened tab.

`netstat` showed **two processes listening on `127.0.0.1:5233` at once**, holding entirely
different state behind the same URL - one spent (14 登録済み / 1 完了 / 3 未処理), one fresh
(17 未処理 / 1 完了). Which one a client reached was decided by the TCP stack. The cause was
mine: `allow_reuse_address = True` on the server. On Linux `SO_REUSEADDR` only relaxes
TIME_WAIT; **on Windows it genuinely lets a second process bind an already-bound address**.
Measured directly: `SO_REUSEADDR=True -> SECOND BIND SUCCEEDED`, `False -> refused, errno
10048`.

There was a second, independent half to this. Streamlit kept "what has been decided" in
`st.session_state`, so a browser reload forgot work already done to the same worklist and
then offered an already-committed case for approval again. The engine refused it correctly
with `STATUS_NOT_COMMITTABLE` - the row was 登録済み, and commit is only allowed from 未処理 -
but the visible result was **13 automated / 5 queued instead of 14 / 4**. The counter was
not lying; the dashboard had simply asked the wrong question.

I treated this as an architecture problem rather than a counter bug, which is the decision
I am most glad I made. The portal process owns row state in memory with no second copy;
the audit log owns what the automation attempted; counters are now *derived* from those two
on every redraw and never incremented. `automated` additionally requires the portal to
corroborate the audit record, a duplicate portal can no longer start, every audit record
carries `portal_server_id` and `portal_epoch`, and the engine refuses to write to a portal
the reviewer is not reading. The invariant `worklist == awaiting + automated + queued` is
rendered as a visible error if it ever fails rather than asserted away. Build notes **§5c**.

**3. The embedded portal showed a snapshot, not the portal.** The first approved case
updated the embedded frame and every case after it did not, until I reloaded by hand - so
the dashboard could say `Row 3 changed 未処理 → 登録済み, confirmed by reading the row back`
beside a frame still showing 未処理.

Two causes, and fixing only the obvious one would have left the batch broken. The page
fetched `/api/state` once at first render and the engine drives the portal in its *own*
browser, so a commit there was invisible to the frame. And `dispatch()` blocks the
Streamlit script for the whole run while Streamlit paints in script order, so with the
review column emitted first the frame on screen during a run was the greyed-out leftover
from the previous rerun - during a 14-case batch, never repainted until all 14 finished.
The portal now exposes a monotonic `rev` counter on `/api/rev`; the embedded copy re-reads
the worklist only when the server says state moved, and the portal column is emitted before
the review column. Verified in a browser: **14 of 14 rows flip one at a time with the frame
never reloaded**, and three one-at-a-time approvals each flip within ~2 s.

### What this pattern actually says

Step 2 §7.5 argued the *failure branch* would be the expensive part of a build. It was not.
What cost the most was the host: a username with a space, a console codepage, and a socket
option that means two different things on two operating systems. None of that is visible in
the operation logs the entire analysis is built on, and no further analysis of those logs
would have produced it. The mitigation is not cleverer code - it is running the thing on a
machine that is not the developer's before calling it done.

That is also why the final report keeps the failure branch tagged as an engineering
assumption rather than a measurement. **0 of 684 observed cases failed**, so every rule
about what happens on a bad case is designed, not learned.

### AI Usage

Claude Code executed and drafted: it wrote the consolidated report and README to my
outline, ran the verification scripts, implemented the `/api/rev` refresh and the exception
queue surfacing, and drove the browser-based checks. It also caught that my own account of
the Windows launch bug was wrong - I had remembered it as a quoting problem in the
`Popen`, and the artefact says the `Popen` was always a list and the culprit was the
`os.execv`. I kept the artefact's version.

The judgment calls stayed mine: treating the portal-state problem as an architecture
question rather than a counter bug, refusing blind retries when the logs show no failure to
learn from, keeping Client_ROI and Build_Fit separate so that what is convenient for me
never enters the client's ranking, insisting the time-saved number stays a relative ratio,
and deciding what to leave explicitly manual rather than automate on no evidence.
