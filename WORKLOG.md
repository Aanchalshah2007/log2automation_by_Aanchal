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

It has the highest `Client_ROI` and the second-highest `Build_Fit`, making it the right Step-3 target without sacrificing the client's objective.

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
