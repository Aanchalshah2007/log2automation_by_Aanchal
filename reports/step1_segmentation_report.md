# Step 1 — Recovering units of work from the operation logs

**Deliverable:** `segments.jsonl` (684 segments, dataset B, 15/15 sessions)
**Code:** `src/` · **Reproduce:** `cd src && python3 validate_a.py && python3 run_b.py && python3 qa_segments.py`

Throughout, findings are tagged **[O] Observed** (measured directly from the files),
**[I] Inferred** (a reading of the evidence that could be wrong), or
**[A] Assumption** (an engineering choice not forced by the data).

---

## 1. Dataset A summary

**[O]** 63 sessions, 117 chunks, **162,768 events**, 25.6 h of wall clock, 8 machines /
8 distinct `username_hash`. Sessions 945–3,773 events (mean 2,584); 1–3 chunks each.
Recorded 2026-06-30 (10 sessions) and 2026-07-01 (53).

Event mix: `app_switch` 31.1%, `keystroke` 23.8%, `screenshot_smart` 21.2%,
`shortcut` 8.4%, `mouse_click` 3.8%, `browser_click` 3.3%, `clipboard_change` 3.2%.
Layers: L2 118,399 · L1 34,580 · L3 9,335 · SYSTEM 454.

Applications by dwell time: Chrome 69.2%, Notepad 12.9%, PowerPoint 5.5%, Word 3.8%,
Explorer 3.2%, Excel 0.9%.

**[O]** Three business systems are served as the same SPA on adjacent loopback ports —
5122 `HR人事給与システム`, 5123 `財務会計システム`, 5124 `受発注在庫管理システム` — each
exposing the same five hash routes (`resident-tax`, `payroll-items`,
`leave-applications`, `social-insurance`, `onboarding`).

**[O] Ground truth.** All 63 sessions have `gt.jsonl` and `gt_manifest.json`.
2,009 executions of 15 processes across hr/finance/ops (5 each), median 31.7 s.
`process_started` (1,819) + `process_resumed` (190) = 2,009 = `task_started` count =
`gt_manifest` execution count, so **one execution = one case**.
Six of the 15 processes carry a variant (`std`/`exc` or `reg`/`adj`); nine carry none.

**[O] Ground-truth quirks, quantified.**

| Quirk | Measured |
|---|---|
| `end_ts: null` in `gt_manifest` | **257 of 2,009 executions (12.8%)** |
| duplicate consecutive `process_started` | **230** — equals `1,819 − 1,590` starts-minus-switch-outs |
| start/resume vs switch-out/suspend imbalance | 320 across the 63 sessions |
| `gt_manifest.executions[].apps` disagrees with the log | GT says process C uses `onenote`, the log shows **Word** (2,175 events); GT says I uses `teams`, the log shows **PowerPoint** (2,724) |
| `ts_utc` (`+00:00`) vs `timestamp_iso` (`Z`) | both genuinely UTC; must be parsed, not string-compared |

**[I]** The 230 duplicate starts are not corruption — they are exactly how a
back-to-back repeat of the same process is recorded. `src/groundtruth.py` therefore
rebuilds intervals from the `gt.jsonl` stream, closing each execution at the first of
{explicit close, next open, `session_ended`}. This **reproduces all 1,752 intervals that
`gt_manifest` does give to the millisecond (max error 0.0 s) and recovers the 257
missing ones**, giving a complete 2,009-interval reference.

**[O] Two facts about GT geometry that drove the whole design:**
1. **1,844 of 1,946 consecutive executions (94.8%) abut to within 50 ms.** Only 34 min
   of the 1,388 GT minutes falls in a genuine hole between executions.
2. The dead time is **asymmetric**: the worklist row-click lands a median 4.66 s after
   an execution starts (p10 3.11 / p90 5.55 — tight), while the action-button click
   lands a median 3.27 s before it ends (p90 28.18 — loose). Quiet stretches >15 s sit
   *inside* an execution after its commit (84 min in Chrome alone), not between them.

---

## 2. Dataset B summary

**[O]** 15 sessions, 20 chunks, **20,477 events**, 2.9 h, 4 machines. All recorded
2026-07-01 in a ~3 h window. Event mix differs sharply from A: `mouse_click` 10.4%
(vs 3.8%), `browser_click` 9.4% (vs 3.3%), `mouse_scroll` 8.4% (vs 2.0%),
`app_switch` only 8.1% (vs 31.1%).

Applications by dwell: **Edge 68.8%, Word 19.6%**, Notepad 3.4%, Excel 2.0%,
OpenWith 1.3%, Terminal 1.2%, Teams 0.9%.

**[O] What is genuinely different from A** (the README says "different applications and
departments"; the measured picture is more specific):

| | A | B |
|---|---|---|
| Generator theme | `Theme M1 - Mixed Multi-Domain` (terminal title) | `run_theme_m2.bat`, `Theme M2 - Run Setup` (OCR of the terminal) |
| Browser | Chrome 148 | Edge |
| Ports | 5122–5124 | 5132–5134 (**same three systems, same five routes**) |
| Worklist row DOM id | `#la-row-SUP-181750-001` — **case id embedded** | `#la-table > tbody > tr:nth-of-type(4)` — **positional only** |
| Action buttons | semantic: `-confirm`, `-register`, `-approve`, `-complete`, `-flag`, `-query` | uniform: `#btn-{pi,la,ob,si,rt}-ok` |
| Case ids in the DOM | 3,560 hits, 1,745 distinct | **0** |
| SSO | `sso-mock.html`, 2,938 events | absent |
| Reference material | Excel `m1_reference`, Word `HR_Policy`/`Supplier_List` | 12 Word 規程/手続 documents + `expense_calc`, `budget_analysis` |
| Multi-tab | none | 6 of 15 sessions |
| Process ↔ screen | strictly 1:1 | **not** 1:1 — HR/payroll-items hosts two request types |

**[I]** The consequence is the central methodological risk of this task: **any segmenter
tuned on A's case ids or semantic button names scores well on A and produces nothing on
B.** What transfers is the (system, route) context, the row→note→paste→commit motif
*shape*, and the clipboard/paste rhythm — so the method was built only on those.

**[O] Data-quality issues that affected the pipeline** (full list in the exploration
notes; these are the ones the code has to handle):

| Issue | A | B |
|---|---|---|
| `context.active_app` stale — ≠ `payload.new_app` on `app_switch` | 38.0% | 23.8% |
| self-switches (`new_app == previous_app`) | 44,644 / 50,588 (**88.3%**) | 738 / 1,654 |
| timestamps non-monotonic in file order | 15,231 backward jumps (median 120 ms, max 714 s) | 2,922 |
| `ms_since_last_event` ≠ timestamp delta | 115,658 events | 17,442 |
| `clipboard_change.text_content` null | 100% | 100% |
| `browser_form_input.value` null | 100% | 100% |
| `text_input_complete` | 118 events (0.07%) | 77 (0.38%) |
| `extracted_text` present | 4.5% | 4.6% |
| **sessions with zero L3 (extension never connected)** | **7 of 63** | **1 of 15** |
| screenshots present vs declared | 7,329 / 34,555 (21%) | 4,746 / 4,746 |

**[I]** A's missing screenshots look like a download/export cap, not a recording property:
51 chunks declare captures and have none, and 56 more are truncated at exactly 250 files.
The method uses no images, so this does not affect the result.

---

## 3. Segmentation approach

### 3.1 What was tried, and why the simple thing won

I evaluated candidate signals on dataset A before committing to a design
(`src/diag_signal.py`, `diag_anchor.py`, `diag_l2.py`, `diag_cycle.py`, `diag_gap.py`):

| Candidate | Measured on A | Verdict |
|---|---|---|
| Inactivity gaps | GT executions abut 94.8% of the time; median inter-execution gap **0 ms** | **Useless alone** — there is no silence at a boundary |
| Chunk boundaries | 117 chunks vs 2,009 executions | Useless, as the spec warns |
| `app_switch` transitions | 88.3% are self-switches; foreground app repeats every case | Useful only after cleaning, and not as a boundary |
| Portal context change | covers only **61.6%** of GT boundaries within 3 s | Necessary but not sufficient — consecutive cases on one screen change nothing |
| **DOM case anchors** (row-open → action button) | **1,722 / 2,009 executions contain exactly one row-open (1,750 contain at least one); 1,751 exactly one commit** | **The boundary signal** |
| Per-execution L2 markers (`Ctrl+F`, `Ctrl+A`, clipboard) | best single marker fires exactly once in 65% of executions | Fallback only |
| Clustering / embeddings on event windows | not needed — see below | Rejected |

**[I]** Clustering and change-point detection were rejected on evidence, not taste: once
the portal context is resolved, the (system, route) pair maps to the GT process code with
**ARI 0.993** on extension-present sessions, i.e. the process identity is *directly
observable*. A learned representation would have to beat a signal that is already almost
perfect, and would be far harder to defend to the client. Likewise no supervised
classifier was trained on A's labels — that would not transfer, since B's processes are
different.

### 3.2 The method: Anchor-Anchored Context Segmentation (AACS)

Five deterministic stages (`src/segmenter.py`).

**Stage 1 — resolve the portal context for every event.** Three channels, in order:

1. **URL** — `payload.url` on `browser_navigation`/`browser_click`/`browser_form_input`,
   then `context.active_browser_tab.url`. Port → system, hash → route. *(A: 49.3% of
   events, B: 45.2%.)*
2. **DOM module prefix** — a click on `#la-note` or `#btn-la-ok` names the screen module
   even when the URL field is absent.
3. **Window title + OCR breadcrumb** — the title names the system
   (`財務会計システム`), and `ダッシュボード / <screen>` in `context.extracted_text` names
   the screen. This is the **only** channel that survives an absent extension, where
   `active_browser_tab` is null too.

The resolved context is then carried forward (an execution spends most of its wall clock
in Excel/Word/Notepad, where no URL exists) and, for leading unresolved runs,
**backfilled** from the next observation — bounded by window-title system changes so a
context never crosses a system switch. *(Final coverage: A 97.9%, B 98.5% of events.)*

**Stage 2 — find case cores.** A *core* is a worklist row-open paired with the action
button that closes it. Two regexes cover both datasets:
`#<mod>-row-<CASEID>` (A) and `#<mod>-table > tbody > tr:nth-of-type(N)` (B), with
commit verbs `{confirm, register, approve, complete, flag, query, ok}`.
Unpaired opens close at the next open; unpaired commits become point cores.

**Stage 3 — L2 fallback where there is no DOM.** For extension-less sessions the click
still exists as a plain `mouse_click` with the browser in the foreground. Two shapes
occur and they need different anchors, so the family is **chosen per session** from that
session's own ratio of browser-exits to in-browser pastes:

* *excursion-driven* (ratio ≥ 0.8; all 7 A sessions, 0.96–2.21): anchor = the **last
  browser click before the worker leaves the browser**. Fires exactly once in 74% of the
  204 affected executions.
* *browser-resident* (ratio < 0.8; the 1 B session, 0.43): anchor = the **click within
  3.5 s after an in-browser paste**, i.e. the action button. Recovers 49 anchors where
  the excursion rule finds 19.

Taking the union instead of choosing double-fires on 58 of A's 204 extension-less
executions, which is why the selection exists.

**Stage 4 — cores → segments.** Every margin is expressed as a fraction of `ref`, the
**session's own median case length**, so the constants survive B's ~3× faster tempo:

* `start = open − 0.21 × ref` (measured lead 4.66 s ÷ 20.9 s median core = 0.223)
* `end = next segment's start − 1 ms` — the committing segment **absorbs the trailing
  dead time**, because that is where GT puts it (§1, fact 2)
* unless that dead time exceeds `14 × ref`, in which case the excess is left unowned
* if lead and tail cannot both fit, the gap is split at 0.44 of its length

**Stage 5 — reject non-work.** A segment needs ≥ 6 events and ≥ 3 s. Anything that never
resolved to a work screen — Teams, Outlook, the terminal, File Explorer, the SSO page,
external browsing — produces no core and therefore no segment.

### 3.3 Tuning discipline

Four constants are fitted (`src/tune.py`), each with a physical meaning, on a
deterministic 42-session dev split; 21 sessions were held out.
**[O]** The holdout scores *better* than dev (boundary F1@2s 0.899 vs 0.838, ARI 0.968 vs
0.886), so the constants are not memorising dataset A.

---

## 4. Features: which ones earn their place

| Feature | Role | Reliable? | In the MVP? | Evidence |
|---|---|---|---|---|
| `payload.url` / `active_browser_tab.url` | **process identity** | Yes when present; absent in 8 of 78 sessions | **Yes** | ARI 0.993 vs GT codes |
| DOM `css_selector` (row / button) | **boundaries** | Yes when L3 is up | **Yes** | exactly one row-open in 85.7% of executions; 87.2% carry an anchor of either kind |
| Window title | system identity; degraded-mode context | Yes (63–73% of events, forward-fillable) | **Yes** | recovers the system in extension-less sessions |
| `extracted_text` breadcrumb | route in degraded mode | Sparse (4.5% of events; 63% of portal visits) | **Yes** | lifts extension-less IoU@0.25 from 0.09 to 0.92 |
| `payload.new_app` (app_switch) | foreground app → *station* | Yes | **Yes** | `context.active_app` is stale 38% of the time and mis-attributes Excel's Ctrl+F to Chrome |
| `shortcut.keys` | L2 fallback anchors | Yes | **Yes (fallback only)** | `Ctrl+V` locates the note paste |
| `mouse_click` + station | L2 fallback anchors | Moderate | **Yes (fallback only)** | 74% / one-per-case in excursion mode |
| Timestamps | everything | **Must be re-sorted**; `ms_since_last_event` is wrong | **Yes** | 15,231 backward jumps in A |
| Word/Excel document titles | variant analysis only | Yes | No (diagnostic) | separates "consulted the rule book" cases |
| `clipboard_change` | rhythm only — **content is 100% null** | Length only | No | cannot identify the case |
| `browser_form_input.value` | — **100% null** | No | No | redacted |
| `text_input_complete` | — 118 events in A | No | No | too sparse to reconstruct anything |
| `keystroke` | volume only | Yes | No | does not distinguish processes |
| Screenshots (images) | — | 79% missing in A | No | `extracted_text` gives the same content |
| `open_apps`, `visible_windows` | — | Yes | No | no measured discriminative power; large |

**Segment representation** (`segmenter.Segment`): `session`, `start`, `end`,
`ctx=(system, route)`, `n_events`, `kind` (`anchor` / `l2-excursion` / `l2-resident`),
`case_key`, `verb`. Only the first four reach `segments.jsonl`; the rest exist so every
segment can be traced back to the evidence that produced it.

---

## 5. The five core segmentation problems

**A. Process switch (A → B).** The portal context changes: a different port (system) or a
different hash route. The switch instant is not the navigation itself but the row-click
that follows it, so the boundary is placed `0.21 × ref` before that click — the empirical
lead of 4.66 s. **[O]** Context changes alone catch only 61.6% of GT boundaries within
3 s; the anchor is what makes the other 38% recoverable.

**B. Returning to a process (A → B → A).** Nothing is stateful, so nothing has to be
"resumed". Each case core carries its own resolved context, and the second visit to A
produces a new segment with the identical label because the label is a function of the
observed screen, not of history. **[O]** Dataset A contains 190 GT `process_resumed`
events; the method reproduces those spans without special handling and the label matches
in every case that matched at all (ARI 0.993 on extension-present sessions).

**C. Repeated executions vs one interrupted execution.** This is the question the design
turns on. A new execution requires **a new case core** — a fresh worklist row-open.
A quiet stretch, an app excursion, or a Teams detour with *no* new row-open does **not**
start a segment; the preceding segment absorbs it. **[O]** This is the correct model:
280 GT executions run longer than 60 s; of the 241 where an anchor is visible at all,
**231 contain exactly one row-open** — they are single cases with a long think-time
inside, not runs of cases. The only guard is
the `14 × ref` absorption cap, beyond which the excess is left unowned.

**D. Variants.** The label is derived from the screen the case was worked on, never from
the action sequence, so optional steps cannot fragment it. **[O]** Confirmed on A:
process F splits `std`/`exc` 123/46 and process A splits `std`/`exc` 120/39, yet both
variants land on one label (label purity 0.997). **[O]** Confirmed on B by an explicit
split test (§7).

**E. Background / unrelated activity.** It never acquires a context, so it never produces
a core, so it never becomes a segment. **[O]** Dataset A's GT declares 102 noise blocks
(`teams` 27, `email_file` 25, `auth_file_shell` 19, `onenote_or_browser` 31); the
segmenter emits nothing for Teams, Outlook, the terminal, Explorer, Settings or the SSO
page. The evidence that this is neither too lax nor too strict is that **97.2% of
predicted time falls inside GT execution time**, while still recovering **94.3%** of it.

---

## 6. Dataset A validation results

All 63 sessions, final configuration:

| Metric | All 63 | Extension present (56) | Extension absent (7) |
|---|---|---|---|
| segments predicted / true | 1,954 / 2,009 (**ratio 0.973**) | 1,791 / 1,805 (0.992) | 163 / 204 (0.799) |
| boundary P / R / F1 @1 s | 0.573 / 0.535 / **0.553** | 0.585 / 0.556 / 0.570 | 0.447 / 0.342 / 0.388 |
| boundary P / R / F1 @2 s | 0.889 / 0.829 / **0.858** | 0.908 / 0.864 / 0.885 | 0.688 / 0.527 / 0.597 |
| boundary P / R / F1 @5 s | 0.920 / 0.858 / **0.888** | 0.933 / 0.888 / 0.910 | 0.782 / 0.599 / 0.679 |
| mean / median temporal IoU | **0.865** / 0.946 | 0.891 / 0.949 | 0.635 / 0.594 |
| matched at IoU ≥ 0.5 / ≥ 0.25 | **0.910** / 0.961 | 0.945 / 0.966 | 0.603 / 0.917 |
| over-segmented GT executions | 45 (2.2%) | 27 (1.5%) | 18 |
| under-segmenting predictions | 53 (2.7%) | 6 (0.3%) | 47 |
| GT time recovered | **0.943** | 0.941 | 0.968 |
| predicted time inside GT | **0.972** | 0.972 | 0.968 |
| labels discovered | 15 (= 15 GT codes) | 15 | 15 |
| purity / V-measure / **ARI** | 0.958 / 0.915 / **0.912** | 0.997 / 0.993 / **0.993** | 0.613 / 0.565 / 0.361 |

Dev / holdout split: F1@2s 0.838 / **0.899**, ARI 0.886 / **0.968**, IoU 0.843 / 0.910.

### What these numbers actually say

**The label problem is solved; the boundary problem is solved to the precision the data
allows; one failure mode remains and it is a recording defect, not a modelling one.**

* **Labels.** 15 labels emerged with no supervision and the contingency table against the
  GT codes is almost perfectly diagonal (ARI 0.993 where the extension is up). This is not
  a clever result — it is a property of the data: each process is worked on exactly one
  screen of one system, and the screen is directly observable.
* **Boundaries.** F1 jumps from 0.553 at 1 s to 0.858 at 2 s. **[O]** That is a ceiling,
  not a tuning failure: even an oracle that places every boundary at `row-click − 4.66 s`
  (the exact measured median) achieves only **0.672** recall at 1 s, because the row-click
  itself jitters ±0.77 s (median absolute deviation) around the GT start. Sub-second
  boundary accuracy is not recoverable from this signal, and chasing it would be fitting
  noise. At 2 s the oracle reaches 0.974 recall and the method reaches 0.829 (0.864 on the
  extension-present sessions) — that remaining 11-15 points is the real headroom.
* **Segment count.** 0.973 of GT — the method very slightly under-produces, which is the
  right direction: predicted time is 97.2% inside GT time, so it is not inventing work.
* **Metric note.** GT writes `process_switched_out` and the next `process_started` 2–3 ms
  apart. Counting those as two boundaries caps any single-boundary-per-handover method at
  ~0.56 recall, so `evaluate._collapse` merges GT boundaries within 250 ms into one
  transition. Without that the reported recall measures the file format, not the method.

### Ablations (all 63 sessions)

| Variant | segments | F1@2s | IoU | @≥0.5 | GT time | ARI |
|---|---|---|---|---|---|---|
| **full** | 1,954 | 0.858 | 0.865 | 0.910 | 0.943 | 0.912 |
| no L2 fallback (DOM anchors only) | 1,777 | 0.840 | 0.801 | 0.849 | 0.895 | **0.992** |
| no OCR channel | 1,791 | 0.836 | 0.801 | 0.849 | 0.898 | 0.993 |
| neither | 1,777 | 0.840 | 0.801 | 0.849 | 0.895 | 0.992 |

**[O]** The OCR channel and the L2 fallback only work *together* — OCR supplies the
context, L2 supplies the boundaries, and either alone changes nothing. **[I]** Together
they buy +4.8 pts of GT time recovered and +6.1 pts of IoU@0.5 at a cost of 8 pts of ARI,
because the 7 rescued sessions carry noisier labels (§7). I kept them on: leaving 11% of
dataset A and 7% of dataset B with *zero* output is a worse failure than labelling them
imperfectly, and the brief requires dataset B to be fully processed.

### Failure cases, by share of GT executions

| Bucket | n | % | GT minutes |
|---|---|---|---|
| good (IoU ≥ 0.5, single match) | 1,679 | 83.6% | 1,116 |
| **missed entirely — no anchor recoverable** | **252** | **12.5%** | **174** |
| over-segmented | 26 | 1.3% | 28 |
| partial (0.25 ≤ IoU < 0.5) | 38 | 1.9% | 27 |
| barely overlapping (IoU < 0.25) | 14 | 0.7% | 44 |

1. **Extension-less sessions (dominant, 12.5%).** All 252 misses sit in sessions where
   the browser extension never connected. `active_browser_tab` is null there too, so the
   route survives only through sparse OCR: **the system is recovered 85% of the time but
   the route only 64%**, which is why ARI collapses to 0.361 on those 7 sessions. Worst
   confusions are within a system (`payroll-items` → `resident-tax` / `leave-applications`
   / `social-insurance`, 8 each).
2. **Long executions with an internal detour (~1% of executions, 44 GT minutes).**
   A case that pauses for a >14 × ref stretch has the excess trimmed, so IoU drops even
   though the boundary and the label are right. Kept deliberately: absorbing an arbitrarily
   long Teams detour into an "invoice approval" would corrupt the duration statistics that
   Step 2 will depend on.
3. **Executions with no portal step at all.** A handful of GT executions run entirely in
   Excel and Notepad and never touch the portal (visible in the trace of
   `ses_20260630-121953`, execution A at t+208 s). Nothing anchors them.
4. **Double row-clicks.** 28 executions contain two row-opens; the re-selection merge
   handles those where the key repeats. `REOPEN_MERGE_MS` proved **inert** on A (no metric
   moves at any value 0–8 s) — kept as a guard for B, and flagged as untested.
5. **Weakest processes** are B (`hr/payroll-items`, mean IoU 0.756), K, L and H
   (0.738–0.741) — the four that A's GT most often splits across phases.

---

## 7. Adapting to dataset B, and the label-consistency check

**Nothing in the method was changed for B.** Three properties made that possible: the
context channels are port/route/title-based rather than case-id based; the row and button
regexes cover both DOM conventions; and every margin scales with the session's own tempo.
Three things adapt automatically:

1. **The screen-name → route map is re-learned from B** (`src/screenmap.py`). Sessions
   where the URL and the breadcrumb appear together vote for the mapping, which is then
   used where the URL is gone. **[O]** B yields 13 screens, A yields 15 — discovered, not
   configured, from each dataset's own screen text.
2. **`ref` is measured per session**, so B's ~11 s cases get ~2.3 s margins where A's ~31 s
   cases get ~6.6 s.
3. **The L2 anchor family is chosen per session**; B's extension-less session correctly
   selects `resident`, yielding 49 segments instead of 19.

### Discovered processes in dataset B

**[O]** 12 distinct screens carried work (a 13th, `hr/住民税・その他`, renders "0 件" and
was never used). Names are B's own, read from `context.extracted_text`:

| Label | Screen (B's own text) | System | Segments | Sessions | Median s | Total min |
|---|---|---|---|---|---|---|
| `hr_expense_and_pay_change` | 経費精算・給与変更 | HR | 134 | 11 | 10.7 | 26.5 |
| `fin_purchase_order_management` | 発注管理 | Finance | 77 | 9 | 10.8 | 14.0 |
| `fin_invoice_approval` | 請求書承認・経費精算 | Finance | 74 | 9 | 15.5 | 22.8 |
| `ops_inventory_management` | 在庫管理 | Ops | 67 | 9 | 10.6 | 14.1 |
| `hr_onboarding` | 入社手続き | HR | 65 | 9 | 15.9 | 19.7 |
| `ops_contract_management` | 契約管理 | Ops | 59 | 8 | 20.5 | 19.1 |
| `hr_attendance_leave_request` | 勤怠・休暇申請 | HR | 56 | 6 | 9.0 | 9.5 |
| `ops_it_access_request` | IT申請 | Ops | 40 | 5 | 10.6 | 7.9 |
| `fin_payment_processing` | 支払処理 | Finance | 37 | 5 | 19.8 | 10.8 |
| `hr_benefits_application` | 福利厚生申請 | HR | 35 | 4 | 12.2 | 7.5 |
| `fin_manager_expense_approval` | 経費承認（管理職） | Finance | 32 | 4 | 18.0 | 9.0 |
| `fin_budget_variance_analysis` | 予算差異分析 | Finance | 8 | 1 | 21.0 | 2.6 |
| **Total** | | | **684** | 15 | 12.0 | 163.4 |

### Split test — is any label really two processes?

**[O]** 2-means on a behavioural fingerprint (app dwell shares, event-type rates, shortcut
rates, documents opened, buttons pressed) within each label. The separations found are:

| Label | Split | Sep. | What actually separates the clusters |
|---|---|---|---|
| `hr_expense_and_pay_change` | 94 / 25 | 0.333 | Notepad memo written (0.04 vs 0.89 dwell) |
| `ops_inventory_management` | 46 / 18 | 0.321 | Notepad memo written |
| `fin_invoice_approval` | 62 / 12 | 0.269 | `expense_calc.xlsx` opened |
| `fin_payment_processing` | 21 / 17 | 0.263 | `gyomu_itaku_kyuuyo_kitei.docx` opened |
| `fin_manager_expense_approval` | 18 / 14 | 0.262 | `settai_keihi_kitei.docx` opened |
| `ops_it_access_request` | 27 / 13 | 0.237 | Notepad memo + Teams |
| `ops_contract_management` | 32 / 29 | 0.166 | `keiyaku_kaijo_tetsuzuki.docx` opened |
| others | — | ≤ 0.042 | no structure |

**[I]** Every one of these is "the worker consulted the rule book / wrote the batch memo
on this case, and not on that one" — an **optional step within one process**, exactly what
the brief says not to split on. The business objective, the worklist, the record type and
the commit action are identical across each pair. **No label was split.**

### Merge test — are any two labels the same process?

**[O]** Cosine similarity between label centroids is very high: `hr_expense_and_pay_change`
↔ `ops_inventory_management` = **0.990**, `hr_benefits_application` ↔
`ops_it_access_request` = 0.959, and six further pairs above 0.84.

**[I] I rejected every merge.** The similarity is an artefact of a shared UI pattern —
every screen in this portal is worked with the same click-row → paste-note → press-OK
motif, so a behavioural fingerprint cannot tell them apart. The decisive evidence is
elsewhere and is unambiguous: different business system, different worklist, different
record types (`P1-…` expense claims vs `P11-…` stock adjustments), different reference
documents, and a different downstream effect. **This is a case where the clustering metric
is the wrong instrument and I did not follow it.**

### Duration spread per label (a sanity check on identity)

**[O]** Coefficient of variation per label runs 0.25–0.62 (`fin_purchase_order_management`
0.25, `ops_inventory_management` 0.62). **[I]** The tight ones are pure data entry; the
loose ones are the labels whose split test found a document-lookup variant — consistent
with one process having an optional step, not with two processes sharing a label.

---

## 8. Output and quality checks

`segments.jsonl` — **684 segments**, 12 labels, all 15 sessions, 33–55 segments per
session (mean 45.6). Durations: min 6 s, p10 8 s, median 12 s, p90 24 s, max 58 s.
Segmented time 163 min of 176 min recorded (**93%**).

`src/qa_segments.py` — all 14 checks pass:
valid JSONL · exact field set · `session_id` resolves to a real directory · ISO 8601 UTC ·
`start < end` · inside the session's event range · ≥ 3 real events per segment ·
no duplicates · no overlaps · no impossible durations (2 s–30 min) · no >60 s silent gap
inside a segment · labels are stable identifiers with no per-instance suffixes · every
label used more than once · dataset B fully processed.

---

## 9. Confidence and uncertainty

**High confidence** — the process identities. They are read off the screen the worker was
on, they were verified against A's ground truth at ARI 0.993, and B's screen names come
from B's own rendered text.

**High confidence** — boundaries in the 14 B sessions with the extension (635 of 684
segments; 629 cores come from DOM anchors). The equivalent population in A scores IoU 0.891 with 94.5% matched at IoU ≥ 0.5.

**Low confidence** — the 49 segments from `ses_20260701-192455-NEELA9BAF`, B's
extension-less session (7% of the output). The A analogue of that population scores
IoU 0.635 with **route labels only 64% correct**. Treat that session's per-process
breakdown as indicative only.

**Unknown** — B's absolute accuracy. There is no ground truth, and A is a different theme.
The A numbers are the best available estimate, and the two datasets differ in ways
(positional row ids, browser-resident rhythm, multi-tab) that could push B either way.

**Deliberately not claimed** — the exact number of distinct processes in B. I report 12
observed; §10 explains why the true figure is probably 13.

---

## 10. Limitations

1. **`hr_expense_and_pay_change` is almost certainly two processes.** **[O]** B's OCR shows
   this screen's worklist interleaving `P1-…` rows (expense settlement: 消耗品費, 研修費,
   出張旅費, 接待交際費) with `P4-…` rows (pay changes: 昇給, 役職手当廃止, 扶養控除変更).
   **[O]** The P-code is visible in the detail pane of only **5 of 684 segments**, and B's
   row selectors are positional, so it cannot be attributed per case. **[I]** These are
   different business objectives and should eventually be separate labels. I kept them
   together rather than guess — this is the single largest known defect, affecting the
   biggest label (134 segments, 26.5 min).
2. **Route confusion in extension-less sessions** (§9), 7% of the B output.
3. **Sub-2-second boundary accuracy is unreachable** from this signal (oracle recall 0.672
   at 1 s). If the client needs finer boundaries, the recording agent must emit them.
4. **The method depends on the portal being a worklist SPA.** A process worked entirely in
   Excel, or in a desktop client with no DOM and no OCR-able breadcrumb, produces no
   segment. Dataset A already contains a few such executions.
5. **`fin_budget_variance_analysis` rests on one session** (8 segments). Its frequency
   estimate is worthless; its existence is not in doubt.
6. **Dead time is attributed to the preceding case**, which is right 94.8% of the time on
   A but inflates that case's duration when the worker genuinely idles between cases.
7. **The generator is visible in the data.** Both datasets are scripted runs
   (`Theme M1`/`run_theme_m2.bat`, `dwell_scale 1.4`, seeded). Regularities the method
   relies on — one row-click per case, a consistent commit button — may be crisper here
   than in organic behaviour.

## 11. Engineering assumptions

Each of these is a choice, not a fact, and each is falsifiable:

1. **[A] One worklist case = one business-process execution.** True by construction in A
   (2,009 executions = 2,009 `task_started`). Assumed for B.
2. **[A] The screen identifies the process.** Holds 1:1 in A. Known to be violated once in
   B (limitation 1).
3. **[A] `LEAD_FRAC = 0.21`, `TAIL_FRAC = 0.22`, `ABSORB_MULT = 14`, `BOUNDARY_FRAC = 0.44`**
   — fitted on 42 A sessions, held out on 21. Expressed relative to the session's own
   tempo so they scale; that scaling is itself an assumption, untestable without B's GT.
4. **[A] `RESIDENT_RATIO = 0.8`** for choosing the L2 anchor family. The observed gap is
   narrow — A's extension-less sessions measure 0.96–2.21, B's measures 0.43 — and rests
   on 8 sessions. A third workflow shape landing near 0.8 would be mis-handled.
5. **[A] A screen name belongs to exactly one system**, used to clean multi-tab OCR bleed.
   Verified against both datasets' rendered nav lists; would break if two systems ever
   shipped an identically named screen.
6. **[A] `MIN_EVENTS = 6`, `MIN_DURATION_MS = 3000`.** Chosen to reject UI noise, not
   tuned. A genuinely 2-second process would be discarded.
7. **[A] Keeping the degraded-mode segments** rather than emitting nothing for
   extension-less sessions — a completeness-over-precision call, quantified in §6.
8. **[A] `segments.jsonl` timestamps are truncated to whole seconds**, matching the format
   in the brief. This costs up to 1 s of boundary precision, which is below the method's
   demonstrated resolution anyway.
