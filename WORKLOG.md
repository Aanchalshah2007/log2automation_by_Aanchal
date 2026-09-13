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
