# Work log

What I was thinking each day, what I tried, and what did not work. Dead ends are recorded
in as much detail as the things that worked — they are most of what I learned.

Generative-AI usage is recorded per day, as the brief requires.

---

## Day 1 — 2026-09-14 · Understand the data, then Step 1

**Plan for the day:** spend the morning refusing to write a segmenter. Measure first.
The failure mode I wanted to avoid is picking a method that looks principled (change-point
detection, sequence clustering, embeddings) and only later discovering the data has a
much more direct signal — or worse, that the method leans on something that exists in
dataset A and not in B.

### What I found before writing any segmenter

Both datasets are **scripted synthetic recordings**, and they say so. A's terminal window
title is `Theme M1 - Mixed Multi-Domain (HR / Finance / Ops)`; OCR of B's terminal shows
`run_theme_m2.bat` with a `Theme M2 - Run Setup` prompt (seed, speed 1.4×, scale, run
date). This matters: regularities I rely on may be crisper here than in organic behaviour,
and I noted it as a limitation rather than pretending otherwise.

The structural discovery that shaped everything: **three business systems are the same SPA
on adjacent loopback ports (A 5122–5124, B 5132–5134), each exposing the same five hash
routes.** In dataset A, `(port, route)` maps 1:1 onto the 15 ground-truth process codes —
a perfect 3 systems × 5 screens grid. Process identity is therefore *directly observable*,
not something that needs to be learned.

I then checked what does **not** transfer from A to B, because the brief warns the
departments and applications differ:

- A's worklist rows carry the case id in the DOM (`#la-row-SUP-181750-001`); **B's are
  positional** (`tr:nth-of-type(4)`). 3,560 case-id hits in A, **zero** in B.
- A's buttons are semantic (`-confirm`, `-register`, `-approve`); B collapsed them all to
  `-ok`.
- A has an SSO step, Chrome, and Excel-driven lookups; B has Edge, no SSO, and 19.6% of
  its wall clock in Word regulation documents.

So anything keyed on case ids or button verbs would have scored beautifully on A and
produced **nothing** on B. That single check justified the whole morning.

Data-quality findings that changed the code (not just the report):

- `context.active_app` is **stale on 38% of A's `app_switch` events** — it reports the app
  being switched *away from*. I initially trusted it and got nonsense: Excel's `Ctrl+F`
  attributed to Chrome, 1,293 times. Replaced with a state machine over
  `payload.new_app`.
- **88.3% of A's `app_switch` events are self-switches** (`new_app == previous_app`).
  `app_switch` count is not a measure of task switching.
- Timestamps are **not monotonic in file order** (15,231 backward jumps in A, max 714 s),
  and `ms_since_last_event` disagrees with the timestamp delta on 115,658 events. Every
  script sorts by `(ts, seq)` and recomputes gaps.
- `clipboard_change.text_content` and `browser_form_input.value` are **100% null**.
  `text_input_complete` exists on 118 events in all of A. Text content is simply not
  recoverable — I stopped looking.
- **7 of A's 63 sessions and 1 of B's 15 have zero L3 events.** This became the day's main
  engineering problem.
- A's screenshots are 79% missing (51 chunks declare captures and have none, 56 truncated
  at exactly 250 files). Looks like a download cap, not a recording property. I use no
  images, so it did not matter — but it would have wrecked an OCR-on-images approach.

### Ground truth: rebuilt rather than trusted

`gt_manifest.json` leaves `end_ts` null on **257 of 2,009 executions (12.8%)**, and
`gt.jsonl` emits 230 duplicate consecutive `process_started`. Rather than dropping 13% of
the reference, I rebuilt the intervals from the `gt.jsonl` event stream, closing each
execution at the first of {explicit close, next open, `session_ended`}.

The duplicate starts turned out not to be corruption at all: 1,819 starts − 1,590
switch-outs = 229 ≈ the 230 duplicates. **A duplicate start is exactly how a back-to-back
repeat of the same process is recorded.** The reconstruction reproduces all 1,752 intervals
the manifest does give **to the millisecond** and recovers the 257 missing ones.

### Things I tried that did not work

**1. Believing my own boundary metric.** My first score was boundary F1 0.527 at 2 s, which
I nearly accepted as "the method is mediocre". It was the metric. Ground truth writes
`process_switched_out` and the next `process_started` **2–3 ms apart**, so a set of GT
boundary timestamps has ~3,552 entries for 2,009 executions. Any method emitting one
boundary per handover is capped near 0.56 recall by construction. Added
`evaluate._collapse` to merge GT boundaries within 250 ms into one transition. Same
segmenter, F1 0.825. **Lesson: I was measuring the file format, not the method.**

**2. Tiling the timeline with a single interpolated boundary.** Placed each boundary at
44% of the dead time between one commit and the next row-open. Mean IoU 0.750. Reasonable,
but wrong about where the dead time belongs.

**3. Symmetric lead/tail margins.** Gave each segment a margin before its row-click and
after its commit, leaving a hole between. Mean IoU 0.763, F1@2s 0.825. Better, but it
under-covered long executions badly (280 executions over 60 s scored mean IoU 0.511 and
accounted for 447 of the 1,388 GT minutes).

**4. What actually fixed it — measuring who owns the dead time.** `diag_gap.py`:
**1,844 of 1,946 consecutive GT executions (94.8%) abut to within 50 ms**, and only 34
minutes in the whole dataset sits in a genuine hole. Meanwhile the quiet stretches over
15 s sit *inside* executions, after their commit (84 minutes in Chrome alone). The lead is
tight (row-click 4.66 s after the start, p90 5.55) and the tail is loose (commit 3.27 s
before the end, p90 28.18). So: keep a tight lead, and let the committing segment **absorb
all the trailing dead time**. Mean IoU 0.799 → eventually 0.865.

**5. Excursion-cycle fallback for extension-less sessions — abandoned.** For sessions with
no `browser_click`, I counted portal → Excel/Notepad → portal round trips as case cores.
It rescued **11.6% of the anchorless executions at IoU ≥ 0.25, mean IoU 0.060.** Useless.
Deleted.

**6. Discovering the real reason those sessions failed.** When the extension is absent,
`context.active_browser_tab` is **also** null — not just `browser_click`. Context
resolution went to literally 0% and those 7 A sessions and 1 B session produced **zero
segments**. The fix: a third context channel from the window title (names the system) plus
the OCR breadcrumb `ダッシュボード / <screen>` (names the screen), with the
screen-name → route map **learned from the dataset's own sessions** where the URL and the
breadcrumb appear together. That map is also what discovers B's process names, so one
mechanism solved two problems.

**7. Two wrong L2 fallback anchors before the right pair.** Reading an actual
extension-less trace against ground truth showed the row-click still exists as a plain
`mouse_click` with the browser in the foreground. First rule — *last browser click before
leaving the browser* — fires exactly once in 74% of A's affected executions. Good. Applied
to B's extension-less session it produced **19 segments where comparable sessions have
~45**, because B's work is browser-resident: the worker rarely leaves the browser. Second
rule — *click within 3.5 s after an in-browser paste* — recovers 49 there but only fires
38% of the time on A, and the **union double-fires on 58 of A's 204 anchorless
executions**. So neither is universal and the union is worse than either. Resolved by
choosing the family per session from that session's own browser-exit-to-paste ratio
(A: 0.96–2.21, B: 0.43). It works, but the gap is narrow and rests on 8 sessions — logged
as an assumption, not a finding.

**8. Two plain bugs, both caught by a metric looking impossible.** Coverage reported 143%
(broken interval union). And point cores gave `ref = median(1 ms)`, collapsing every
margin to zero so `_drop_noise` deleted every segment in exactly the sessions I had just
fixed — extension-less sessions silently went from 24 segments to 0.

**9. Trying to split B's biggest label — abandoned honestly.** B's OCR shows
`hr/payroll-items` interleaving `P1-…` expense claims with `P4-…` pay changes: two
different business objectives on one worklist. I looked for a per-case signal. The detail
pane's P-code is OCR'd in **5 of 684 segments**, and B's row selectors are positional, so
there is no join. Left as one label and wrote it up as the single largest known defect
rather than guessing.

**10. Not following the clustering metric.** The merge test says
`hr_expense_and_pay_change` ↔ `ops_inventory_management` have cosine **0.990**. They are
plainly different processes — different system, worklist, record types and downstream
effect. The similarity is an artefact of one shared click-row → paste → OK interaction
pattern. I rejected every merge and said so. The split test similarly found structure in
7 labels, all of it "consulted the rule book on this case and not that one" — optional
steps, not separate processes. No label was split.

**11. A parameter that does nothing.** `REOPEN_MERGE_MS` gives identical metrics at every
value from 0 to 8,000 ms on dataset A, because A's row ids carry the case id and the
same-key branch already handles re-selection. Kept at 2,500 as a guard for B's positional
selectors, and flagged as untested rather than presented as tuned.

### Decisions I made and would defend

- **No machine learning.** Not on principle — on measurement. Portal context alone reaches
  ARI 0.993 against the GT process codes. A learned representation would have to beat an
  almost-perfect signal and would be far harder to explain to the client.
- **No supervised classifier trained on A's labels.** B's processes are different; that
  model would be worthless there, and the brief says so explicitly.
- **All margins expressed as fractions of the session's own median case length**, so the
  constants survive B running ~3× faster. This is the main thing making the method
  portable, and it is itself an untestable assumption without B's ground truth.
- **Kept the degraded path on** even though it costs ARI (0.992 → 0.912), because it lifts
  GT time recovered from 0.895 to 0.943 and stops one B session emitting nothing at all.
  Completeness over precision, stated as a choice.
- **Stopped chasing sub-2-second boundaries.** An oracle placing every boundary at the
  exact measured lead reaches only 0.672 recall at 1 s tolerance — the row-click itself
  jitters ±0.77 s around the GT start. Further tuning there is fitting noise.

### Considered and deliberately skipped

A fourth context channel: learn left-nav click coordinates → route from sessions with L3,
apply to sessions without. It would likely lift the extension-less route accuracy from 64%
toward 90%. Skipped: it needs a cache rebuild for mouse coordinates, and it affects
1 of B's 15 sessions — roughly 2% of the final output. Wrong use of day 1.

### Where the day went

Roughly 40% measuring the data before writing anything, 35% building and rebuilding the
segmenter, 15% on the extension-less degraded path alone, 10% on validation harness and
write-up. The 40% up front paid for itself: it produced the `(port, route)` insight, and
it caught the A→B transfer trap before I had built anything on top of it.

### Generative AI usage

Claude Code (Opus 5) was the working environment for the whole day, used as an
implementation and analysis partner rather than for prose. Concretely: writing all the
diagnostic and pipeline scripts to my direction; reading Japanese screen text and window
titles to identify the business processes; and — the part with the most value —
interrogating the data on demand, so that questions like "who owns the dead time between
executions?" turned into a measurement in a couple of minutes instead of an assumption.
Every quantitative claim in the report comes from a script in `src/` that can be re-run,
not from the model's recollection. Where the model's first answer was wrong (the
excursion-cycle fallback, the boundary metric) it was the measurement that caught it, not
review of the reasoning.

### Next

Step 2 — process frequencies, cycle times, operator counts and variant patterns from
`segments.jsonl`, then a prioritised automation shortlist with feasibility and risk. Before
that I want to re-examine the P1/P4 split in `hr_expense_and_pay_change`, because it is the
largest label by volume and Step 2's ROI ordering will lean on it.
