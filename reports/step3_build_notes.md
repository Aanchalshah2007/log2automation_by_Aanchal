# Step 3 — build notes

What was built, what genuinely runs, what is a mock, what stays manual after
deployment, how the time-saved figure is calculated, and the risks this build carries
forward from step 2 §7.5 and §8.2.

Evidence is tagged the same way as the step-1 and step-2 reports:
**[MEASURED]** read out of dataset B's own events · **[ASSUMPTION]** an engineering
or policy decision I made, stated so it can be argued with.
Nothing below is tagged **[MEASURED]** unless a count from the logs backs it.

Target: **`fin_purchase_order_management` (発注管理)**. Chosen in step 2 §7 — highest
Client_ROI, Build_Fit 0.80, and 0.00 document-sourced clipboard content, so the whole
loop is DOM-in / DOM-out with no file, OCR or Word integration to build. That decision
is not revisited here.

---

## 1. What was built

Three pieces, all local, no network, no cloud service, no model.

| | |
|---|---|
| `src/mock_portal/` | the reconstructed 発注管理 screen — one screen, acting as both source and destination — plus the synthetic case seed |
| `src/automation/` | `engine.py` (Playwright, deterministic) + `definitions/*.json` — one full definition and one stub |
| `src/app.py` | the Streamlit review UI: approve / edit / flag, live counters, exception queue, audit log |

Steps 1 and 2 were not touched. Nothing in `segmenter.py`, `roi.py`, `rank_b.py`,
`evaluate.py` or any `diag_*.py` was modified, and they still import nothing outside the
standard library. The step-3 dependencies are isolated in `requirements-step3.txt`.

---

## 2. What genuinely works, end to end

All of the following was run and observed, not designed and asserted. The canonical run
is 18 seeded cases, all approved, headless, with `--no-screenshots` (the per-case PNGs
the review UI displays roughly double the wall clock and are not part of the work):

```
run_start  definition=fin_purchase_order_management v1.0.0  n=18  llm_in_runtime=false
run_end    processed=18  automated=14  queued=4  automation_seconds=10.8
```

**2.1 The engine's full motif, per case.** Read the worklist row → open the case by
clicking its 氏名 cell → read the detail pane → apply the reviewer's corrections →
check the case against the definition → compose the note → write it to `#rt-note` →
**re-read `#rt-note` and confirm the value landed** → click `#btn-rt-ok` **once** →
**re-read the row's ステータス and confirm it flipped**. There are two read-backs, not
one, and both are first-class steps: they are emitted to the UI as
`writing the note → ✓ note confirmed in the DOM → committing (once, no retry) →
verifying… → ✓ 登録済み confirmed`, and both land in the audit record as
`note_confirmed` and `verify_confirmed`. If the note does not confirm, the commit
button is never touched (§5b.4).

**2.2 The seeded failures actually land in the exception queue.** Four of the 18 cases
are deliberately unautomatable, and each one exercises a different stop condition:

| Case | Seeded defect | Caught at | Code | Commits attempted |
|---|---|---|---|---:|
| `…-006` | `reason` is blank | precheck | `REQUIRED_FIELD_MISSING` | **0** |
| `…-011` | row already in 完了 | precheck | `STATUS_NOT_COMMITTABLE` | **0** |
| `…-014` | 種別 is 保留, not in {定常, 調整} | precheck | `ENUM_UNRECOGNISED` | **0** |
| `…-017` | supplier not registered — the portal accepts the click and writes nothing | **verify** | `VERIFY_FAILED` | **1**, not retried |

`…-017` is the one that matters. Three of the four are caught by reading the case
before touching anything, which is cheap. The fourth is a portal that *accepts the
click and does nothing*, and there is no way to catch that except by reading the state
back. An automation without a verify step would have reported it as done.

**2.3 The engine never double-commits, and this was tested rather than asserted.**
Replaying the same 18 jobs over an already-processed worklist:

```
run_end  processed=18  automated=0  queued=18  (STATUS_NOT_COMMITTABLE ×15,
                                                REQUIRED_FIELD_MISSING ×1,
                                                ENUM_UNRECOGNISED ×1, VERIFY_FAILED ×1)
commits attempted in the replay: 1
```

The single commit is `…-017`, which is still legitimately in 未処理 because its first
commit never landed. Every row that *was* committed is refused. Zero rows were
committed twice across both runs.

**2.4 The approve / edit / flag loop, and EDIT genuinely edits.** Driven through the
real UI, not unit-tested around it. The audit record for an edited case:

```json
{"case_id": "P10-07054374-002",
 "human_action": "approve",
 "edits": {"reason": "年間契約：測定機器　数量 7　合計 777,777円　通常"},
 "written": "発注管理処理。年間契約：測定機器　数量 7　合計 777,777円　通常。発注書確認・登録完了。",
 "commit_attempts": 1, "verify_confirmed": true,
 "status_before": "未処理", "status_after": "登録済み"}
```

The value the human typed is the value that reached the portal. FLAG routes the case
to the queue without the browser ever opening it (`commit_attempts: 0`).

**2.5 Config-driven, verifiably.** `engine.py` contains no string beginning with `#rt-`
or `#btn-`. Every selector, column index, enum, pattern, status transition and note
template comes from the definition JSON. The stub definition proves the boundary the
only way that means anything — the engine refuses to run it:

```
$ python3 src/automation/engine.py --definition …/hr_attendance_leave_request.stub.json --jobs …
definition 'hr_attendance_leave_request' is state='stub', not 'active'.
Stub definitions describe a screen that has no mock behind it in this prototype.
The engine refuses to run one rather than pretend it did.
```

**2.6 The audit log.** One JSONL record per case in `build/audit_log.jsonl`: run id,
definition id and version, every field read out of the DOM, the reviewer's edits, the
effective values, the composed note, whether a commit was attempted and **how many
times**, whether verify confirmed, the status before and after, review seconds, engine
seconds, and timestamps. `llm_in_runtime: false` is recorded on every record.
`note_confirmed` records the pre-commit read-back separately from `verify_confirmed`.

**2.7 The whole demo, driven through the real UI.** Not the CLI — a browser clicking the
actual buttons: RESET DEMO, then APPROVE, then EDIT-and-approve with a corrected `reason`,
then APPROVE, then *Run remaining as batch*.

```
reset            18 in worklist · 18 awaiting review · 0 automated · 0 queued · —
after 3 reviewed 18 · 15 · 3 · 0
after the batch  18 ·  0 · 14 · 4 · ≈58% hands-on time removed
```

14 automated, 4 queued, every counter reconciling to 18, a positive saving, and the four
seeded failures in the queue with their reasons. The edited case committed the corrected
value, not the one the DOM held.

---

## 3. What is mocked, and what that costs

**[MOCKED] The portal.** There is no access to the client's system, and there never
was — dataset B is an operation log, not an API. So the 発注管理 screen is
reconstructed. What was reconstructed from evidence, and what was invented:

**[MEASURED] — recovered from dataset B's `context.extracted_text` and
`browser_click` / `browser_form_input` payloads on
`http://127.0.0.1:5133/#/resident-tax`:**

| | |
|---|---|
| the DOM contract | `#rt-table > tbody > tr:nth-of-type(N) > td:nth-of-type(3)` → `#rt-note` → `#btn-rt-ok`, from 69 `browser_click` and 68 `browser_form_input` events on that route |
| the row-open column | `td:nth-of-type(3)` — every row-open click on this route lands on column 3 |
| the note placeholder | `処理内容を入力…` |
| the detail-pane field names | `name` · `emp_id` · `variant` · `procedure` · `target_month` · `reason` · `コメント` |
| the worklist columns | ID · 社員ID · 氏名 · 区分 · 金額 · 種別 · ステータス |
| the note template | `発注管理処理。{reason}。発注書確認・登録完了。` — **68 distinct note values recovered, all 68 conform** |
| the reason grammar | `{発注区分}：{品目}　数量 {n}　合計 {amount}円　{flag}` |
| 発注区分 | 年間契約 21 · スポット発注 17 · 定期発注 14 · 緊急発注 9 · 発注変更 7 |
| 品目 | 8 values, and 8 supplier names, both used verbatim in the seed |
| the status vocabulary | 未確認 43 · 完了 34 · 未処理 14 · 登録済み 12 · 照合中 1 |
| the screen chrome | 財務会計システム / 2026年度 · 経理部門 / 佐藤 直樹 · 経理マネージャー / breadcrumb ダッシュボード / 発注管理 |
| the ⚠ row marker | observed on 福岡システム設計 in a 発注管理 worklist capture — reused as the unregistered-supplier flag |

**[MOCKED] The case values.** Every supplier/item/quantity/amount pairing on the screen
is invented. The real ones were never logged: `clipboard_change` events carry
`text_content: null` and only a `text_length`. The UI says this in a banner on the mock
portal and in the disclosure table in the review app. Nothing about this prototype's
correctness depends on the values being real — the automation reads whatever the DOM
says — but nothing about it demonstrates that the real values are *well-formed*, either.

**[ASSUMPTION] Three structural details the logs do not settle:**

1. **The detail pane's DOM.** Its *rendered text* was captured; its markup never was,
   because no `browser_click` ever landed inside it. The mock exposes each value as
   `[data-field='<name>']` and the definition reads it that way. On the real screen this
   is the one selector family in the definition that is a guess.
2. **The status transition.** The definition verifies 未処理 → 登録済み. Dataset B's
   発注管理 captures actually show **未確認 and 完了** on this screen (43 and 34
   readings); 未処理 / 登録済み is the wording of the sibling `payroll-items` screens
   in the same portal. Which pair is live on 発注管理 is a two-line edit in
   `row_schema.status`, and it living in the definition file rather than in code is
   exactly the point of the split. This is flagged in the definition's `_provenance`
   block, not buried here.
3. **`variant` = `V2_adjust_po`** for 調整 rows. Only `V1_routine_po` was ever captured.

**[ASSUMPTION] The whole failure branch.** See §5.

---

## 4. What remains manual after deployment

Not aspirationally manual — manual.

1. **Every case in the exception queue.** In the canonical run that is 4 of 18. On real
   volume it is whatever the real rate of blank fields, closed rows, unknown 種別 and
   silently-refused commits turns out to be, and **that rate is not knowable from these
   logs** (§5). A human opens each one in the portal and works it by hand.
2. **Every flagged case.** FLAG exists so a reviewer who does not like a case can stop
   it. Those cases are never automated.
3. **The review itself.** The demo flow reviews cases one at a time and then batches the
   rest, which is a *choice about the operating model*, not a property of the tool. If
   the client wants every case reviewed, the review time never goes away and the saving
   shrinks accordingly — the counter in the UI charges review time honestly either way.
4. **Deciding what to do with a queued case.** Forcing a queued case through is a human
   decision. There is no override in this prototype, deliberately.
5. **Owning the queue.** Step 2 §7.5 flagged this as a client governance question and it
   is still open: an exception queue with no named human behind it is a backlog with
   extra steps. The prototype cannot answer it.
6. **The 0.78 s per case in the supplier-registration procedure document**
   (`shinkuitorihikisaki_touroku_tetsuzuki`, [MEASURED]). 0.78 s of an 11 s cycle, so
   skipping it is not hiding the hard part — but it is skipped, and an operator who
   actually needed to read it still does.

---

## 5. The failure branch is designed, not learned — and that is the biggest soft spot

**[MEASURED]** Dataset B contains **684 cases and 0 observed failures**. All 38
`browser_error` events carry an empty text field and sit at the three portal roots
(page load, not case failure); no error wording was ever rendered into the portal
inside a case; no case committed twice. The one ambiguity — 57 of 684 cases with no
observed commit — is explainable by step 1's boundary accuracy and cannot be separated
from genuine abandonment.

**[ASSUMPTION]** So the portal's real behaviour when a purchase order is rejected, when
the supplier is already registered, when the worklist moves, or when the session times
out is **unknown**, and no further analysis of these logs will produce it. The design
follows from that rather than from evidence:

- **commit once, never retry** — `policy.commit_attempts: 1`, and there is no code path
  that increments it;
- **verify by reading the state back**, never by trusting the click or a toast (the
  engine never parses the portal's messages, because it cannot know their wording);
- **queue on anything unrecognised**, including an unexpected browser error, which is
  caught and routed rather than swallowed.

**[ASSUMPTION] The honest cost statement.** This branch — prechecks, verify, the queue,
the stop conditions, and the seeded failures needed to test it — is roughly a third of
the step-3 build, against 0% of the observed logs. Step 2 §7.5 predicted exactly this,
and building it confirmed the prediction rather than testing it: the seeded failures are
failures *I* invented, so they prove the mechanism works, not that it covers what the
real portal does. **The first real-system run will find failure modes this queue has no
code for.** The mitigation is that they all land in the same place — the queue — because
the default is to stop, not to improvise.

---

## 5b. The bugs that only surfaced once it was running — the real "risks that appear at implementation"

Step 2 §7.5 predicted that the failure branch would be the expensive part and that the
first real run would find modes the design had no code for. It did — five times — and not
once in the automation logic. They are recorded here because the assignment asks what
surfaces when implementation begins, and this is the honest answer: **every one was in the
plumbing around the automation or in the host it runs on, not in the browser work itself.**
Two of them (§5b.5, §5b.6) were found only by running the prototype on a machine that was
not the one it was written on.

### 5b.1 The engine deadlocked against a full stderr pipe — [MEASURED]

**Symptom.** A run through the review UI wrote its job file and then produced **no audit
records at all**. The portal was left showing the case at 未処理 with `#rt-note` empty;
pressing 登録確定 by hand returned 「…: 処理内容が未入力です」, which is the portal behaving
correctly. The natural reading — "the note-writing code is broken" — was wrong.

**What was checked first, and cleared.** The same job file, run against the same portal
straight from the CLI, completed green (`automated=1`, 未処理 → 登録済み). Then the write
path itself was instrumented: `#rt-note` is a real `<textarea>`, not a contenteditable;
`page.fill()` sets the value **and** dispatches an `input` event; `input_value()` reads
the value straight back; the commit that follows flips the row. So the selector, the
element type, the reactive-event question, the composed value and the job-payload
serialization were all sound.

**The actual cause.** `src/app.py` launched the engine with
`Popen(stdout=PIPE, stderr=PIPE)`, iterated **stdout to completion**, and only then called
`proc.stderr.read()`. Nothing drained stderr in the meantime. The pipe buffer on this
kernel is **65536 bytes** (measured with `fcntl(F_GETPIPE_SZ)`). Once chromium wrote more
than that to stderr it blocked in `write()`; blocked, it produced no more stdout; with no
more stdout the parent stayed in its read loop; and so nobody ever drained stderr. Classic
deadlock, and it is *environment-dependent* in exactly the way that makes it nasty: it
never fired on a machine with fonts and browser libraries installed, because chromium
stayed quiet. On a machine that emits `Fontconfig error`, dbus and GPU warnings, 64 KB
arrives quickly.

Reproduced deterministically with a 20-line probe (a child that writes two stdout lines
and 3200 stderr lines): the reader blocked after **one** stdout line — `run_start` — which
is precisely the observed signature of a run that starts and then writes nothing.

**Fix.** stderr is drained on its own thread from the moment the process starts. The same
probe then completes with both stdout lines and all 3200 stderr lines read.

**[ASSUMPTION] What this means beyond the prototype.** A production deployment would run
the engine from a scheduler, not from Streamlit, so this specific plumbing would not
exist. The transferable lesson is narrower and worth keeping: **a UI that supervises a
browser automation is itself a place the automation can fail silently**, and the failure
looks exactly like a broken automation. The audit log is what distinguished the two —
"no records at all" is a different fault from "records that say the write failed".

### 5b.2 The dashboard and the portal could disagree about which demo was running — [MEASURED]

**Symptom.** The portal held 18 fresh 未処理 cases while the dashboard simultaneously
showed nothing pending and counters at 0/0/0.

**Cause.** The UI kept a third opinion. Besides the portal (which owns the cases) and the
audit log (which owns what happened to each case), `src/app.py` kept its own `handled`
set, and `dispatch()` added every dispatched case to it **unconditionally** — including
when the engine returned nothing, as in §5b.1. Those cases then vanished from the pending
list while never appearing in the counters. Restarting `server.py` in a terminal produced
the same class of disagreement from the other direction: a brand-new worklist with the
previous run's ids still marked handled.

**Fix, in three parts.**
1. The `handled` set is gone. A case counts as decided **only** if the audit log holds a
   record for it. Every counter — worklist total, awaiting review, automated, queued — is
   recomputed from the portal's state plus this run's audit records on every redraw, with
   an assertion that `total == pending + automated + queued`.
2. The portal now stamps a new **epoch** on every reset and every start, and returns it in
   `/api/state`. The UI binds to an epoch and rebinds automatically when it changes, so a
   reseed behind the dashboard's back reloads it instead of desyncing it.
3. When the engine returns no record for a dispatched case, the UI says so and leaves the
   case pending rather than silently consuming it.

**Verified from real state**, not from the numbers the code expects:

| | worklist | awaiting review | automated | exceptions |
|---|---:|---:|---:|---:|
| fresh reset | 18 | 18 | 0 | 0 |
| after 1 approve | 18 | 17 | 1 | 0 |
| after 1 flag | 18 | 16 | 1 | 1 |
| portal reseeded behind the dashboard | 18 | 18 | 0 | 0 (rebound, with a notice) |

### 5b.3 The engine could start before the worklist existed — [MEASURED]

Found while fixing the above, not reported by the user. `engine.py` waited on
`#rt-table`, which ships in the static HTML with an **empty `<tbody>`** and is filled by
the page's own fetch. With `/api/state` delayed, `wait_for_selector('#rt-table')` was
measured returning at **rows = 0** — after which every case would have failed `read_row`
with `ROW_NOT_FOUND` and been queued. It never fired on a warm local server, which is
exactly why it was worth finding before a slower machine found it.

**Fix.** The definition now carries a `selectors.ready` (`#rt-table > tbody > tr`) and the
engine waits for the worklist to be *populated*, not merely present. A timeout there is no
longer silent either: the engine writes one `ENGINE_STARTUP_FAILED` audit record per job
rather than exiting with nothing, so a startup failure can never lose a case.

### 5b.4 What changed in the automation itself

One thing, and it came out of §5b.1 rather than from a defect: writing the note and
confirming the note are now **separate, separately reported steps**, and the confirmation
happens immediately before the commit click. The engine re-reads `#rt-note`, requires it
to hold exactly the composed value, and **queues the case with `NOTE_NOT_CONFIRMED`
without touching the commit button** if it does not. Previously the check existed but sat
inside the write helper and was invisible in the trace. `note_confirmed` is now a field in
every audit record.

This closes the loop the report claimed all along — the engine now verifies **both** of
its writes, the note before committing and the row status after — and it means an empty
note can no longer reach the portal's validator at all.

---

### 5b.5 A space in the demo machine's own username stopped the engine launching — [MEASURED]

**Symptom.** On the evaluation machine, pressing APPROVE showed
*"The automation engine produced no run — nothing was written to the portal and no case
was marked handled"*, with this on stderr:

```
C:\Users\Aanchal: can't open file 'C:\...
```

All 18 cases stayed pending. The portal was untouched, so the case sat at 未処理 with an
empty `#rt-note` — and pressing 登録確定 by hand then returned 「…: 処理内容が未入力です」,
which is the portal being correct, not a second bug.

**Cause.** The Windows account folder is `C:\Users\Aanchal Shah` — **it contains a space**
— and `engine.py` called `os.execv(sys.executable, [sys.executable] + sys.argv)` to re-exec
itself with `LD_LIBRARY_PATH` set. On POSIX `execv` takes a real argument vector and a
space is harmless. **On Windows there is no exec:** the CRT joins the argument list into a
single command line *without quoting*, so the interpreter path splits at the space.
Reproduced verbatim:

```
$ python.exe probe.py --definition "C:\a b\def.json"
exe = 'C:\\Users\\Aanchal Shah\\AppData\\Local\\Programs\\Python\\Python313\\python.exe'
--- calling os.execv(sys.executable, [sys.executable] + sys.argv) ---
C:\Users\Aanchal: can't open file 'C:\...\automation_project\Shah\AppData\...\python.exe'
```

`argv[0]` became `C:\Users\Aanchal` and the "script" became the tail after the space. Two
things made it reachable at all: the shim was **not OS-gated**, and `build/pwdeps/` — a
Linux-only artefact — sits on a path Windows can also see, so `local.is_dir()` was true
there too.

**Note what was *not* the cause.** The `subprocess.Popen` in `src/app.py` was already a
list with `shell=False`. The audit asked for covered every spawn site in step 3; there are
exactly two, and the broken one was the `execv`, not the `Popen`.

**Fix.** The re-exec is gone entirely — it was never needed. Chromium is launched as a
child process and inherits `os.environ` at spawn time, so setting `LD_LIBRARY_PATH`
in-process is sufficient (verified: chromium launches with the variable set and no exec).
The shim is now `if os.name != "posix": return`, and **there is no exec anywhere in this
program**. `app.py`'s command is unchanged in shape but now passes every path
`.resolve()`d as its own list element with `shell=False` stated explicitly, and the
surfacing of the child's stderr in the UI — which is how this was caught — is kept.

**5b.6 And immediately behind it, the same class of bug: cp1252.** With the launch fixed,
the engine got as far as writing the note and then died with
`UnicodeEncodeError: 'charmap' codec can't encode characters` — a Windows console defaults
to cp1252, and every string this program prints is Japanese. The mock portal died the same
way on its own startup banner. Both now force UTF-8 on `stdout`/`stderr` before writing
anything.

**[ASSUMPTION] Why this belongs in a risk section and not a changelog.** Neither bug is
about the automation. Both are about the *host*: a username with a space, and a console
codepage. Step 2 §7.5 argued the failure branch would be the expensive part; what actually
cost the most was the environment the demo runs in. A rollout onto client laptops will hit
this class first and hardest — localised Windows installs, OneDrive-redirected home
folders with spaces, corporate paths several levels deep — and none of it is visible in
the operation logs the whole analysis is built on. **The mitigation is not cleverer code,
it is running the thing on a machine that is not the developer's before calling it done.**

---

---

## 5c. Two portals behind one URL — the state-architecture bug

The last and worst of the implementation-time findings, and the only one that was an
*architecture* problem rather than a plumbing one.

### 5c.1 The symptom — [ENCOUNTERED-AND-FIXED]

RESET, the engine and the reviewer's browser tab did not reliably agree about the state
of the portal. A run could report "0 automated, 18 queued, negative saving" while the
portal visibly held a fresh worklist, and a case approved in the UI could fail to change
in a separately opened `http://127.0.0.1:5233/` tab.

### 5c.2 The reproduction — [MEASURED]

`netstat` showed **two processes listening on `127.0.0.1:5233` simultaneously**. Stopping
one proved they held entirely different state behind the same URL:

| listener | epoch | statuses |
|---|---|---|
| WSL `python3 server.py` | `c54b40020cbf` | 14 登録済み · 1 完了 · 3 未処理 — **spent** |
| Windows `python.exe server.py` | `aa361abcbf8e` | 17 未処理 · 1 完了 — **fresh** |

Which one any given client reached was decided by the TCP stack, not by configuration. So
RESET could reseed one portal while the engine wrote to the other and the reviewer's tab
rendered a third view of the demo. Every "counter" symptom downstream followed from that.

### 5c.3 The cause — [MEASURED], and it was mine

`Server.allow_reuse_address = True` in `src/mock_portal/server.py`. On Linux `SO_REUSEADDR`
only relaxes TIME_WAIT. **On Windows it genuinely permits a second process to bind an
address that is already bound.** Measured directly:

```
SO_REUSEADDR=True  -> SECOND BIND SUCCEEDED   (this is the bug)
SO_REUSEADDR=False -> refused, errno 10048    (correct)
```

So a second `python src/mock_portal/server.py --port 5233` started **silently** instead of
failing, and from that moment the URL was ambiguous. Nothing in the system could detect it,
because nothing identified *which* portal process a client had reached.

### 5c.4 Where the authoritative state actually lives — [MEASURED]

In the memory of **one** portal process: the `_STATE` dict in `src/mock_portal/server.py`.
There is no state file and no second copy — deliberately, because a second copy is exactly
the thing that can drift. The row statuses, detail fields, note/comment, 種別 and ステータス
are owned there and nowhere else. The browser page renders that state; the Playwright
engine changes it by driving that page; Streamlit only reads it.

That design was already right. What was missing was any way to tell **which process** was
serving it.

### 5c.5 The fix — single source of truth, made verifiable

1. **A duplicate portal can no longer start.** `allow_reuse_address` is now POSIX-only, and
   on Windows the socket additionally sets `SO_EXCLUSIVEADDRUSE`. Before binding, the
   server probes the port and refuses to start if a portal already answers there, naming
   the incumbent's `server_id`, pid and epoch.
2. **The portal identifies itself.** `/api/state` returns `server_id` (`pid@start_time`),
   `pid`, `port` and `epoch`. The page stamps `server_id` and `epoch` onto `<body>`.
3. **The engine records which portal it actually drove** — read from the rendered DOM, so
   it is what the *browser* reached, not what anyone intended. Every audit record now
   carries `portal_server_id` and `portal_epoch`.
4. **The engine refuses to write to the wrong portal.** Streamlit passes `--expect-server`;
   on a mismatch the run is abandoned with one audit record per job, nothing written.
5. **The engine is pinned to the portal the UI is reading.** `--base-url` overrides the
   definition's `target.base_url`, closing the gap where the sidebar pointed at one portal
   and the definition at another.
6. **RESET resets the actual portal and reads the result back from it** — a POST to the
   portal's own `/api/reset` followed by a fresh GET, reporting the server_id, pid, case
   count and committable count it observed. Streamlit's own variables are dropped
   separately, only once the new epoch is observed.

### 5c.6 Why the counters diverged, and how they are derived now — [ENCOUNTERED-AND-FIXED]

Two causes, both removed:

* **The ambiguous portal** (§5c.2) meant Streamlit and the engine could legitimately be
  describing different worklists.
* **Streamlit's "what has been decided" was session-local.** It accumulated audit records
  in `st.session_state`, so a browser reload or a second tab forgot work already done to
  the same worklist — and then offered an already-committed case for approval, which the
  engine correctly refused with `STATUS_NOT_COMMITTABLE`. Observed during this pass: a
  clean run scored 13 automated / 5 queued instead of 14 / 4 for exactly this reason.

Counters are now derived on every redraw from **two** authoritative sources and nothing
else — the portal's live state, and the audit log filtered by the portal's current epoch:

```
automated = audit says automated  AND  the portal shows 登録済み
queued    = audit holds a final exception or FLAG result
awaiting  = cases with neither
disputed  = audit claims automated but the portal disagrees   (surfaced, never hidden)
```

No counter is incremented or decremented anywhere. The invariant
`in_worklist == awaiting + automated + queued + disputed` is checked every redraw and
rendered as a visible error if it ever fails, rather than asserted away. Reading the
decided set from the log by epoch also made the dashboard survive a reload: a brand-new
browser session against a worked portal reports the same 14 / 4 / ≈56% and does not
re-offer a committed case.

### 5c.7 The zero-committable guard — [ENCOUNTERED-AND-FIXED]

Before any run, Streamlit counts rows in 未処理 **in the live portal**. If that is zero the
engine is not launched at all and the UI says exactly *"Nothing committable — press RESET
DEMO first"*. A spent portal is not a result: without this, starting a demo against one
produced "0 automated, 18 queued, negative saving", which is a broken run dressed up as an
ROI figure. Verified against a deliberately exhausted portal: message shown, batch button
disabled, APPROVE not offered, engine never spawned.

### 5c.8 What was NOT changed

The engine's safety rules are untouched. Commit is still allowed only from 未処理, the
commit is still a single click with no retry, the note is still re-read before the commit
and the row re-read after it, and a case that cannot be verified still stops and goes to a
human. Streamlit still cannot mutate portal row status — it has no code path that does, by
design. The four seeded failures were not altered to improve the numbers.

### 5c.9 Evidence, before and after — [MEASURED]

Before: two listeners on `127.0.0.1:5233` with different epochs and different statuses.

After, one continuous session against a single portal (`server_id 8176@1789670585`):

```
STEP 3  RESET DEMO
STEP 4  portal read directly:  epoch 5ba4411ae5af   {未処理: 17, 完了: 1}
        UI: 18 worklist · 18 awaiting · 0 automated · 0 queued
STEP 5  portal BEFORE 001: ('未処理', '')
        portal AFTER  001: '登録済み' + the composed note
        audit: note_confirmed=True commit_attempts=1 verify_confirmed=True
               portal_server_id=8176@1789670585
STEP 6  three live approvals -> rows 1,2,3 all 登録済み in the portal
STEP 7  batch -> UI: 18 · 0 awaiting · 14 automated · 4 queued · ≈56%
STEP 8  queue shows REQUIRED_FIELD_MISSING, STATUS_NOT_COMMITTABLE,
        ENUM_UNRECOGNISED, VERIFY_FAILED; no invariant or disagreement error
        portal read directly: {登録済み: 14, 未処理: 3, 完了: 1}
STEP 9  invariant 18 == 0 + 14 + 4  -> True
VERIFY_FAILED P10-07054374-017: commit_attempts=1 verify_confirmed=False
              portal still '未処理' — not retried
```

**[ASSUMPTION] What this means for a rollout.** The client's real portal is a service
somebody else operates, so "two servers behind one URL" becomes "which environment am I
pointed at" — staging versus production, or a load balancer with two backends holding
different session state. The defence generalises unchanged: make the target identify
itself, record that identity in the audit trail, and refuse to write when it is not the
one the human reviewed. None of this is visible in the operation logs; it only appears
once something actually runs.

---

## 6. The time-saved figure, and why it is a ratio

Shown in the UI as **"≈X% of hands-on time removed (relative)"**. Never as hours.

```
before = median manual cycle × cases
after  = Σ automated cases (engine seconds + review seconds)
       + Σ queued    cases (review seconds + full manual cycle)
```

- **`median manual cycle` = 11.0 s. [MEASURED]** — `reports/step2_process_metrics.csv`,
  `median_s` for `fin_purchase_order_management`, over 77 observed executions.
- **engine seconds [MEASURED per run]** — wall clock inside `engine.py`, 0.43 s per
  automated case in the canonical run (0.83 s with screenshots on).
- **review seconds [MEASURED per run]** — wall clock from the case appearing in the UI
  to the reviewer's click. Batch cases are charged **0**, because nobody reviewed them.
- **A queued case is charged the full manual cycle on top of its review time**, because
  it saves nothing: a person still has to do the whole case. This is why the exception
  count actually costs something in the number, and why a session dominated by
  exceptions can show a *negative* saving. The UI says so when it happens.

**Three reasons not to quote this as a production figure**, all stated on screen:

1. **[MEASURED]** The 11.0 s baseline comes from a test-environment recording. The
   generator is visible in the data (`dwell_scale 1.4`), so waits are compressed by a
   known-ish but not exactly invertible factor. Real manual cycles are longer, which
   makes the baseline — and therefore the saving — **conservative**.
2. **[ASSUMPTION]** The mock's own seconds are not on that clock at all. A local
   stdlib HTTP server with no auth, no latency and no page weight is faster than the
   real portal, which makes the saving **optimistic**.
3. The two effects push in opposite directions and neither is invertible, so the number
   is a demo figure. Step 2 §1 already established that every duration in this project
   is meaningful only against the other processes in the same table. That did not stop
   being true in step 3.

What the figure *is* good for: it makes the exception count visible in the same units as
the benefit, which is the thing a client conversation actually turns on.

---

## 7. Why this implementation form, and why no LLM at runtime

**Deterministic Playwright script + JSON process definitions + a human review UI.**

**Why not an AI agent.** The task is data entry: click a row, write one templated
sentence, click commit. [MEASURED] `variant_rate` 0.17, `copy_paste_ratio` 0.96, 0.95 of
clipboard content copied from inside the portal, `template_conformance` 0.90, and a note
template that 68 of 68 recovered values conform to. There is no natural-language
understanding in that loop for a model to contribute. What a model *would* contribute is
non-determinism into a write path, and the client's need here is the opposite: the same
input must produce the same write on every run, and the audit trail must say why each
value was written. A model in this position would also make the failure story worse, not
better — it would be *capable* of guessing through an unrecognised case, which is exactly
the behaviour §7.5 argues must not exist when the portal's error semantics are unknown.
`llm_in_runtime: false` is recorded on every audit record so this is checkable and not
just claimed.

Where AI *was* used is in building this: reading Japanese screen text, drafting code and
these notes. That belongs in `WORKLOG.md`, not in the runtime.

**Why not n8n / Power Automate.** Both would work for the happy path. Neither gives a
review surface where a human corrects a field before it commits, and both put the
verify-and-queue logic into a GUI that is harder to review than ~460 lines of Python.
The governance questions in §7.5 are answered by reading code and a definition file,
not by reading a flowchart.

**Why not a single-purpose script.** [MEASURED] All twelve processes in dataset B share
one DOM contract with five selector prefixes. Hard-coding `#rt-note` throws away
eleven-twelfths of the work and saves nothing, because the first definition has to be
written either way. The stub is the evidence that the split is real rather than
decorative.

**Scope, stated plainly.** One process fully working; one stub to prove the shape
extends; the other ten deferred. Step 2 §7 says why: four are judgment-heavy with 31–38%
of their clipboard content copied out of Word, one needs a payroll/tax governance answer
nobody has, and one needs a client decision about approval authority over spend.

---

## 8. Risks carried forward

### 8.1 Positional row selectors — [MEASURED] + unmitigated

[MEASURED] Every process in this portal selects its case with `tr:nth-of-type(N)` and
**no case id appears anywhere in the row's DOM** (step 2 §8.2). The mock reproduces this
fragility on purpose rather than inventing semantic row ids that the real screen does
not have.

An automation built on row position is correct only while the worklist's sort order,
filter and pagination are identical to what the reviewer saw. **Partial mitigation, and
it is in the build:** the engine re-reads column 1 after locating the row and refuses the
case with `ROW_IDENTITY_MISMATCH` if the id is not the one the human approved. That turns
a silent wrong-row write into a queued case.

It is a detector, not a fix. It cannot help if two rows share an id, and it does nothing
about a worklist that re-sorts *between* the read and the commit. **The real mitigation
is a portal change — expose the case id in the row — and that is a client-side ask, not
something a cleverer selector solves.**

### 8.2 Unknown error behaviour — [ASSUMPTION], see §5

The single largest risk in this build. Everything the automation does on a bad case is
designed against an evidence base of zero failures.

### 8.3 Procedure recovered, values synthetic — [MEASURED] structure, [MOCKED] values

The loop shape, selectors, field names and note template are recovered from the logs and
are as solid as 684 segmented cases make them. The *content* is invented, and dataset B's
real content was never recorded. So this prototype demonstrates that **the procedure is
automatable**; it does not demonstrate that **the client's actual data is clean enough**
to run through it. Real values will contain things the field schema will reject —
half-width digits where the template expects full-width spacing, suppliers not in any
enum, amounts with unexpected formatting. Those cases go to the queue, which is correct,
but the queue rate on first contact with real data will be higher than 4-in-18, and
nobody should plan on 4-in-18.

### 8.4 One header shape was measured that the mock does not use — [MEASURED]

The 発注管理 worklist was captured with two different column sets: `ID / 社員ID / 氏名 /
項目 / 金額 / ステータス` (4 captures) and `ID / 社員ID / 氏名 / 区分 / 金額 / 種別 /
ステータス` (1 capture, the portal's uniform family). The mock and the definition use the
7-column family, because 種別 is the branch flag the automation gates on. If the real
発注管理 screen renders the 6-column form, `row_columns` and the `shubetsu` enum check
need re-mapping — again a definition edit, not a code change. Flagging it because it is
the kind of detail that looks like a bug in week two.

### 8.5 The three governance questions are still the client's — [ASSUMPTION]

Unchanged from step 2 §7.5 and unaddressed by this build, because they are not
engineering questions: who owns the exception queue, what the automation authenticates
as (an operator's session is a different governance object from a service account), and
what the audit trail must contain. The audit log in §2.6 is a proposal for the third,
not an answer to it.

---

## 9. Honest summary

| | |
|---|---|
| **Genuinely works on the mock** | the engine's full read → precheck → write note → confirm-note → commit-once → verify-by-read-back loop; approve / edit / flag, with EDIT changing what commits; the exception queue, including all four seeded failures landing in it; no double-commit, verified by replay; counters derived from real state, verified against the portal; the relative time-saved metric; the audit log |
| **Found and fixed while running it** | a stderr-pipe deadlock in the UI's subprocess handling that made the engine write nothing; a start-before-the-worklist-loads race; an `os.execv` re-exec that a space in the machine's own username broke on Windows; a cp1252 console that could not encode the Japanese the whole program prints (§5b); and — the architecture one — **two portal processes bound to `127.0.0.1:5233` at once with different state**, so RESET, the engine and the reviewer's browser tab could each be describing a different demo (§5c). |
| **Single source of truth** | the portal process owns the row state in memory, with no second copy anywhere; the audit log owns what the automation attempted. Counters are derived from those two on every redraw, `automated` requires the portal to corroborate the audit record, and the invariant `worklist == awaiting + automated + queued` is shown as an error if it ever fails rather than asserted away. |
| **Explicitly mocked** | the portal (no system access) and every case value (never logged) |
| **Explicitly manual after deployment** | the exception queue, flagged cases, the review itself, and the decision to force a queued case through |
| **Explicitly designed rather than observed** | the entire failure branch — 0 failures in 684 observed cases |
| **Explicitly deferred** | the other eleven processes, and the second definition beyond its stub |
