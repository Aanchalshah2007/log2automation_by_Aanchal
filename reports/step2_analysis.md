# Step 2 — What dataset B's back office actually does, and what to automate first

Input: `segments.jsonl` (the step-1 deliverable — 684 segments, 12 processes, 15 sessions)
joined back to the raw events inside each segment.
Code: `src/rank_b.py` (measurement + ranking), `src/roi.py` (the scoring model).
Output: `reports/step2_process_metrics.csv` (every factor, one row per process),
`reports/step2_metrics.json` (the same plus three robustness re-runs).

Evidence is tagged throughout, as in the step-1 report:
**[O]** measured from dataset B's own events · **[I]** an inference I drew from it ·
**[A]** an engineering or policy assumption, stated so it can be argued with.

---

## 0. The headline

**Automate `fin_purchase_order_management` (発注管理, supplier-registration purchase
orders) first.** It ranks first on Client_ROI in the base ranking and in all three
robustness re-runs, by a margin of 1.4×–2.2× over the runner-up, and it is also the
second most buildable process in the set. It is the Step-3 target; nothing had to be
deferred to make that work.

The process with the most volume — `hr_expense_and_pay_change`, 134 cases and 26.5 of
the 163 segmented minutes — is **not** the recommendation. It writes to payroll and tax
withholding, and step 1 established that it is two business objectives sharing one
worklist. Section 5 is the argument for why volume did not win.

---

## 1. Durations in this report are relative, never absolute

**[O]** The brief states the logs were recorded in a test environment and that waiting
time inside each operation is shorter than in production. **[O]** The generator is
visible in the data (`dwell_scale 1.4`, step-1 report limitation 7), so the compression
is real and roughly known but not exactly invertible per operation.

**[I]** Every duration below — median cycle, total minutes, per-case Word dwell — is
therefore only meaningful **against the other processes in the same table**. A median
cycle of 11 s does not mean a purchase order takes eleven seconds in the client's
office. It means a purchase order takes about half as long as a contract amendment.
No figure in this report should be multiplied by a headcount or an hourly rate.
The Impact factor is normalised against the busiest process for exactly this reason:
a ratio survives an unknown time scale, an absolute does not.

---

## 2. The four descriptive questions

### 2.1 What processes are performed?

**[O]** Twelve, each worked against one screen of one of three back-office web systems.
The names are the ones the portal itself renders, recovered from B's own screen text in
step 1 — no dataset-A label was transferred.

| Process label | Screen (B's own text) | System / route |
|---|---|---|
| `hr_expense_and_pay_change` | 経費精算・給与変更 | hr / payroll-items |
| `fin_purchase_order_management` | 発注管理 | fin / resident-tax |
| `fin_invoice_approval` | 請求書承認・経費精算 | fin / payroll-items |
| `ops_inventory_management` | 在庫管理 | ops / payroll-items |
| `hr_onboarding` | 入社手続き | hr / onboarding |
| `ops_contract_management` | 契約管理 | ops / leave-applications |
| `hr_attendance_leave_request` | 勤怠・休暇申請 | hr / leave-applications |
| `ops_it_access_request` | IT申請 | ops / social-insurance |
| `fin_payment_processing` | 支払処理 | fin / onboarding |
| `hr_benefits_application` | 福利厚生申請 | hr / social-insurance |
| `fin_manager_expense_approval` | 経費承認（管理職） | fin / leave-applications |
| `fin_budget_variance_analysis` | 予算差異分析 | fin / social-insurance |

**[O]** The route path and the business screen are decoupled in this portal: five route
paths (`payroll-items`, `leave-applications`, `social-insurance`, `onboarding`,
`resident-tax`) are reused across the three systems, so `fin/resident-tax` serves
発注管理 — purchase orders — and has nothing to do with resident tax. **[I]** This
matters for the ranking: had I scored governance sensitivity off the route path,
the top-ranked process would have been mislabelled a tax process and penalised.
Sensitivity is scored off the rendered screen name and the record types on the
worklist, not the URL.

### 2.2 How often, and how much time?

**[O]** 684 cases over 163 segmented minutes of the 176 minutes recorded (93%).

| Process | Cases | Sessions | Total (min) | Median cycle (s) | p90 (s) | CV |
|---|---:|---:|---:|---:|---:|---:|
| `hr_expense_and_pay_change` | 134 | 11 | 26.5 | 11.0 | 15.0 | 0.56 |
| `fin_invoice_approval` | 74 | 9 | 22.8 | 15.5 | 26.0 | 0.48 |
| `hr_onboarding` | 65 | 9 | 19.7 | 16.0 | 25.0 | 0.47 |
| `ops_contract_management` | 59 | 8 | 19.1 | 20.0 | 28.0 | 0.47 |
| `ops_inventory_management` | 67 | 9 | 14.1 | 10.0 | 17.0 | 0.62 |
| `fin_purchase_order_management` | 77 | 9 | 14.0 | 11.0 | 14.0 | 0.25 |
| `fin_payment_processing` | 37 | 5 | 10.8 | 20.0 | 24.0 | 0.35 |
| `hr_attendance_leave_request` | 56 | 6 | 9.6 | 9.0 | 12.0 | 0.27 |
| `fin_manager_expense_approval` | 32 | 4 | 9.0 | 17.5 | 24.0 | 0.37 |
| `ops_it_access_request` | 40 | 5 | 7.8 | 10.5 | 15.0 | 0.44 |
| `hr_benefits_application` | 35 | 4 | 7.5 | 12.0 | 16.0 | 0.48 |
| `fin_budget_variance_analysis` | 8 | 1 | 2.6 | 21.0 | 24.0 | 0.26 |

**[I]** Frequency and cycle time pull in different directions and neither alone is a
ranking. `hr_expense_and_pay_change` is frequent and short; `ops_contract_management`
is infrequent and slow; both consume roughly a fifth of an operator's logged day.
Impact multiplies the two.

**[A]** `fin_budget_variance_analysis` rests on 8 cases in one session. Its existence is
not in doubt; its frequency estimate is worthless, and it should not be ranked on
volume. Build_Fit (0.15) reflects this directly through its evidence-density term.

### 2.3 How many people?

**[O]** Four machines, four `username_hash` values, mapping 1:1 (verified across all
15 sessions). **[O]** Each machine touches 9, 10, 10 and 11 of the 12 processes.
**[O]** The portal, meanwhile, renders only three personas: 田中 麻里 · 人事マネージャー,
佐藤 直樹 · 経理マネージャー, 高橋 健司 · 物流マネージャー — one per business system.

**[I] Operator count is a recording artefact, not a staffing measurement, and it must
not enter any score.** If four recording machines each cover almost every process, the
count tells you how the capture was distributed, not how the work is divided. The real
staffing dimension visible in this data is the three departments, and it is constant
across the twelve processes, so it cannot discriminate between them either. Operator
count is reported in the metrics table and used nowhere in the ranking. Multiplying
Impact by it — the obvious move — would have inflated every process by an almost
identical factor while adding noise wherever coverage happened to be uneven.

### 2.4 Are there different handling patterns within the same process?

Yes, and three independent channels see them. `variant_rate` takes the **strongest** of
the three, on the reasoning **[I]** that a branch any one channel can see is a branch
the automation has to handle.

1. **[O] The worklist's own 種別 column.** Every worklist row is flagged 定常 (routine)
   or 調整 (adjustment — this case needs a hand). This is the most direct signal in the
   data, because it is the flag the operator reads before deciding how to work the row.
   Read from worklist OCR, so its coverage follows the OCR sampling: 8–9 sessions of
   evidence on the three `payroll-items` screens, **one session** on six others. The
   `worklist_variant_sessions` column reports that coverage per process, and §6 re-runs
   the ranking with the thin-evidence readings discarded.
2. **[O] Declared handling categories in the Word processing record.** Three processes
   write one: `ops_contract_management` 処理区分 ∈ {新規締結 55, 更新 30, 変更 16, 解除 14};
   `hr_onboarding` 採用区分 ∈ {新卒家族持 50, 中途 23, 新卒 18, 契約社員 5};
   `fin_manager_expense_approval` 費目 ∈ {消耗品費 71, 研修費 24, 接待交際費 16,
   出張旅費（複数人）7, 出張旅費 6}.
3. **[O] Step 1's optional-step split test** (`reports/discovery_B.json`), which finds
   bimodal execution shapes within a screen — the signature of a step some cases take
   and others skip.

**[O]** The spread: `ops_contract_management` 0.54 and `hr_onboarding` 0.47 at the top,
`fin_purchase_order_management` 0.17 at the bottom. **[I]** The processes with a written
handling category are the processes with real branching, and they are the same
processes that spend the most time in a regulation document — the operator reads the
rule *because* the case type is ambiguous. That coupling is the single clearest
structure in dataset B, and it is what the Automatability factor is built to capture.

---

## 3. The two scores

They are kept apart on purpose.

**`Client_ROI = Impact × Automatability × Client_Feasibility`** — what the client should
automate, independent of who builds it or how long they have. **This is the ranking.**

**`Build_Fit`** (0–1) — whether *I* can put a convincing end-to-end prototype of it on a
mock portal in the four days that remain. That is a fact about my week, not about the
client's business. It is reported in its own column and **never** folded into the
ranking.

Everything is multiplicative, and that is the point: a high-volume process that needs a
per-case policy judgment, or whose targets cannot be hit reliably, should be crushed
rather than rewarded for its volume.

### Impact
`norm(cases × median_cycle)`, normalised against the busiest process. **Not** multiplied
by operator count, for the reason in §2.3.

### Automatability = `repeatability × copy_paste_ratio × (1 − variant_rate) × (1 − judgment_step)`

- **`repeatability`** **[O]** — the mean of (a) how often the full
  row-click → note → commit template is actually observed and (b) `1 − CV` of the cycle
  time. Two independent views: a process can be uniform in shape but ragged in time, or
  the reverse.
- **`copy_paste_ratio`** **[O]** — `pasted_chars / (pasted_chars + typed_chars)` per case.
  `clipboard_change.text_length` is populated on all 872 of B's clipboard events (median
  42 chars), so this is a real character count, not a proxy. **[I]** Content that was
  pasted came from somewhere a program can also read. Content that was typed came out of
  a person's head. Range 0.56–0.96. **[O] *Where* it was read from is measurable too, and
  it decides how much integration a build needs — §3.1.**
- **`variant_rate`** **[O]** — §2.4.
- **`judgment_step`** **[O]** — the share of the case cycle spent inside a **regulation**
  document. **[O]** B's Word documents split cleanly in two: 規定 / 手続き / checklist
  (`settai_keihi_kitei`, `keiyaku_kaijo_tetsuzuki`, `nyusha_checklist_shinsotsu_batch` …)
  versus 一覧 (`getsujitsu_teigaku_torihikisaki_ichiran`, a monthly fixed-amount vendor
  list). **[I] Only the first counts as judgment. A 一覧 is a reference table — data an
  automation can join against. A 規定 is a policy a human reads and then decides, and a
  per-case policy read is not clean automation.** This distinction is what separates
  `fin_invoice_approval` (0.54 s of regulation, 2.35 s of table lookup per case → judgment
  0.03) from `fin_payment_processing` (7.62 s of regulation → judgment 0.38), and the two
  would be indistinguishable if Word dwell were counted as one number.

### 3.1 Where the pasted content comes from

`copy_paste_ratio` says how much of a case arrives through the clipboard. It does not say
where the clipboard was filled from, and those are different feasibility questions: content
copied from the portal is in the DOM, content copied from a Word document is in a file
somebody has to parse.

**[O] Method.** `clipboard_change` fires at the *copy*, so the application in the
foreground at that instant is the surface the content was copied **out of**. 865 of B's
872 clipboard events fall inside a segmented case. Two channels read the source app: the
foreground timeline (primary) and `context.active_app` (cross-check). They agree on 87.6%
of the 865, and the disagreement is **one-directional** — `context.active_app` reads Edge
where the timeline has already moved to Notepad, which is exactly the one-step lag step 1
documented in `common.py`. **[A] The table below therefore uses the timeline, the
conservative channel**; the `paste_source_in_portal_ctx` column in the metrics table
carries the more generous ctx reading beside it — never lower than this one, and higher
for the seven processes where the operator moves between the portal and the note pad.

| # | Process | Clipboard events | From the portal | From the note pad | **From a document** |
|---:|---|---:|---:|---:|---:|
| 1 | `fin_purchase_order_management` | 76 | 0.95 | 0.05 | **0.00** |
| 2 | `hr_expense_and_pay_change` | 172 | 0.65 | 0.35 | **0.00** |
| 3 | `hr_attendance_leave_request` | 55 | 0.93 | 0.07 | **0.00** |
| 4 | `ops_inventory_management` | 103 | 0.51 | 0.48 | **0.00** |
| 5 | `fin_invoice_approval` | 76 | 0.93 | 0.01 | **0.04** |
| 6 | `ops_contract_management` | 86 | 0.67 | 0.01 | **0.31** |
| 7 | `ops_it_access_request` | 55 | 0.55 | 0.38 | **0.00** |
| 8 | `hr_benefits_application` | 38 | 0.92 | 0.00 | **0.05** |
| 9 | `hr_onboarding` | 91 | 0.69 | 0.00 | **0.31** |
| 10 | `fin_budget_variance_analysis` | 8 | 1.00 | 0.00 | **0.00** |
| 11 | `fin_payment_processing` | 58 | 0.62 | 0.00 | **0.38** |
| 12 | `fin_manager_expense_approval` | 47 | 0.68 | 0.00 | **0.32** |

**[O] The finding.** Document-sourced clipboard content is **0.00 for the top-ranked
process** — all 76 of its copies come from the portal (72) or the note pad (4), none from
Word or Excel — and **0.31–0.38 for `fin_payment_processing`, `fin_manager_expense_approval`,
`ops_contract_management` and `hr_onboarding`**, which are precisely the four processes §7
defers as judgment-heavy. **[I]** The two properties are the same structure seen from two
sides: a case whose handling depends on a 規定 is a case whose text is copied out of that
規定. Nothing was fitted to produce that agreement — `judgment_step` is a dwell measurement
and this is a clipboard count, and they land on the same four processes.

**[I]** Note what the note-pad column is not. A high scratch share
(`ops_inventory_management` 0.48, `hr_expense_and_pay_change` 0.35) is not an integration
cost: the note pad holds no business data of its own, it is a staging area for text that
came from the portal a moment earlier, and it is already counted as a mockable surface in
`mock_fidelity`. The column that costs a build is the last one.

### Client_Feasibility = `structured_target × stable_selectors × low_branching × (1 − sensitivity)`

Buildable and governable **for the client, in principle** — not by me, not this week.

- **`structured_target`** **[O]** — the share of cases where the whole
  row → note → commit target is actually observable in the DOM. 0.84–1.00.
- **`stable_selectors`** **[O]+[A]** — route purity (0.98–0.99 everywhere) × the share of
  the three required targets that are id-anchored. **[O]** All twelve processes share one
  DOM contract: `#<prefix>-table > tbody > tr:nth-of-type(N) > td:nth-of-type(N)` →
  `#<prefix>-note` → `#btn-<prefix>-ok`, with only five prefixes (`pi`, `rt`, `la`, `ob`,
  `si`) across all twelve. Two of the three targets are id-anchored; **the worklist row
  is positional in every single process**, with no case id in the selector.
  **[I] This factor is therefore near-constant at ≈0.65 and carries no ranking
  information.** I kept it because removing it would overstate the absolute feasibility
  of all twelve: positional row targeting is a real and universal risk in this portal,
  and §7 says what it costs.
- **`low_branching`** **[O]+[A]** — the *integration* surface: how many companion
  applications and reference documents the automation must keep in sync, counting only
  those recurring in ≥10% of the process's cases. **[A]** The 10% floor stops one
  operator opening Teams once during 56 leave requests from being charged to the process
  definition as a permanent integration; without it, every process looked like a 10-way
  integration. **[I]** This is deliberately a different thing from `variant_rate`: a
  process can have one handling pattern spread over four documents, or four handling
  patterns inside one screen. The first is a build cost, the second a logic cost.
- **`sensitivity`** **[A]** — **the only factor in the model not measured from the logs.**
  How hard it would be to get sign-off for an unattended agent that *writes* to this
  process. The rule: changes pay or tax withholding .55–.60; releases money or carries
  approval authority .45–.55; grants system access .45; touches personal HR data .30–.40;
  operational with legal weight .35; operational and routine .15–.20. The logs cannot
  tell us a company's risk appetite. What they *can* tell us is which process touches
  which record type, and that is what the rule is keyed on. The full table is one block
  in `src/roi.py` so a reviewer who disagrees can change a number and re-rank.

### Build_Fit = `loop_completeness × evidence_density × mock_fidelity × selector_determinism`

**[O]** all four. `loop_completeness` = observed template conformance;
`evidence_density` = `min(1, cases / 30)` — enough observed executions to write and test
a process definition against; `mock_fidelity` = the share of the cycle spent in surfaces
a mock can reproduce honestly (the portal and the note pad — **not** a Word regulation a
human is reading); `selector_determinism` = route purity.

---

## 4. The ranking

Ranked by **Client_ROI**. All three Client_ROI factors are shown so the ordering is
auditable. **Build_Fit is a separate column and does not affect the order.**
Full precision and every intermediate quantity: `reports/step2_process_metrics.csv`.

| # | Process | **Client_ROI** | Impact | Autom. | Client_Feas. | *Build_Fit* | Cases | Med (s) | Variant | Judgment | Sens. |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **1** | **`fin_purchase_order_management`** | **0.166** | 0.57 | **0.62** | **0.47** | *0.80* | 77 | 11.0 | 0.17 | 0.07 | 0.20 |
| 2 | `hr_expense_and_pay_change` | 0.090 | **1.00** | 0.40 | 0.22 | *0.74* | 134 | 11.0 | 0.31 | 0.02 | 0.60 |
| 3 | `hr_attendance_leave_request` | 0.075 | 0.34 | 0.48 | 0.46 | *0.97* | 56 | 9.0 | 0.42 | 0.00 | 0.30 |
| 4 | `ops_inventory_management` | 0.070 | 0.45 | 0.32 | 0.48 | *0.75* | 67 | 10.0 | 0.42 | 0.01 | 0.15 |
| 5 | `fin_invoice_approval` | 0.050 | 0.78 | 0.34 | 0.19 | *0.52* | 74 | 15.5 | 0.42 | 0.03 | 0.50 |
| 6 | `ops_contract_management` | 0.038 | 0.80 | 0.20 | 0.24 | *0.46* | 59 | 20.0 | 0.54 | 0.40 | 0.35 |
| 7 | `ops_it_access_request` | 0.037 | 0.28 | 0.53 | 0.24 | *0.85* | 40 | 10.5 | 0.24 | 0.04 | 0.45 |
| 8 | `hr_benefits_application` | 0.032 | 0.28 | 0.38 | 0.30 | *0.75* | 35 | 12.0 | 0.33 | 0.20 | 0.40 |
| 9 | `hr_onboarding` | 0.031 | 0.71 | 0.23 | 0.19 | *0.49* | 65 | 16.0 | 0.47 | 0.31 | 0.40 |
| 10 | `fin_budget_variance_analysis` | 0.029 | 0.11 | 0.49 | 0.53 | *0.15* | 8 | 21.0 | 0.00 | 0.00 | 0.20 |
| 11 | `fin_payment_processing` | 0.024 | 0.50 | 0.24 | 0.20 | *0.53* | 37 | 20.0 | 0.50 | 0.38 | 0.55 |
| 12 | `fin_manager_expense_approval` | 0.021 | 0.38 | 0.26 | 0.22 | *0.53* | 32 | 17.5 | 0.43 | 0.42 | 0.50 |

**[O]** Impact and Client_ROI are close to uncorrelated: the four highest-Impact
processes finish 2nd, 5th, 6th and 9th. **[I]** That is the model working as designed,
not a defect. The processes the client spends the most time on are the ones where the
time goes into reading a rule and deciding — which is precisely the part that should not
be automated.

### The top four, and why

**1. `fin_purchase_order_management` — 発注管理 (0.166).**
The only process that is simultaneously frequent (77 cases, 9 of 15 sessions), tightly
repeatable (CV 0.25, the lowest of any process with real volume; p90 14 s against a
median of 11 s), almost entirely clipboard-driven (52.6 pasted characters against 2.0
typed per case — 96% paste), essentially free of per-case judgment (0.78 s of regulation
dwell in an 11 s cycle), and operationally low-stakes (a purchase order against an
already-registered supplier is reversible and carries no payroll, tax or approval
authority). **[I]** Nothing else in the table has all five at once.

**2. `hr_expense_and_pay_change` — 経費精算・給与変更 (0.090).**
The volume leader by a distance — 134 cases, 26.5 minutes, Impact 1.00 by construction —
and the cleanest paste loop after the winner (93% paste, judgment 0.02). It ranks second
because the two non-volume factors both cut hard: it is the one label step 1 flagged as
two business objectives sharing a worklist (variant 0.31), and it writes to payroll and
tax withholding, which is where governance friction is highest (sensitivity 0.60, so
`1 − sensitivity` alone removes 60% of its feasibility). §5 is the full argument.

**3. `hr_attendance_leave_request` — 勤怠・休暇申請 (0.075).**
The most mechanical process in dataset B and by far the most buildable (Build_Fit 0.97):
100% template conformance, 98% of the cycle inside the portal and the note pad, 0.02 s of
regulation dwell per case — a human barely thinks during one of these. It ranks third
only because it is small (56 cases, 9.6 min, Impact 0.34) and because its single session
of worklist OCR shows 5 of 12 rows flagged 調整, the highest adjustment share observed
anywhere. **[I]** That reading is thin evidence; §6 re-runs the ranking without it, and
this process moves to 2nd but not to 1st.

**4. `ops_inventory_management` — 在庫管理 (0.070).**
Essentially zero judgment (0.06 s regulation dwell) and the lowest governance
sensitivity in the set (0.15 — stock adjustments are operational and reversible), but
the raggedest execution of any process here (CV 0.62, template conformance 0.87, 7.3
typed characters per case against 60.3 pasted). **[I]** Something inside this process
varies case to case in a way the log does not name — consistent with its 0.42 worklist
adjustment rate over 8 sessions, which is well-evidenced. It is a good second-wave
candidate once the shared foundation exists, not a first build.

---

## 5. Why the volume leader did not win, and why that conclusion is robust

`hr_expense_and_pay_change` has 1.7× the case count and 1.9× the total time of the
recommended target. It lost on the other two factors, and the honest question is whether
that survives the known defect in it.

**[O] The defect.** Step 1 established that this single label covers two business
objectives on one positional worklist: `P1-…` rows (expense settlement — 消耗品費, 研修費,
出張旅費, 接待交際費) interleaved with `P4-…` rows (pay changes — 昇給, 役職手当廃止,
扶養控除変更). The P-code is visible in the detail pane of only 5 of 684 segments and the
row selector is positional, so a code cannot be attributed to an individual clicked row.
Step 1 declined to guess and kept them together.

**[O] New evidence measured here.** The P-code *does* prefix the case id of every
worklist row rendered into `context.extracted_text`, even though it cannot be tied to the
clicked row. Counting the highest row index reached per code per session:
**in all 8 sessions where both codes appear, the screen carries exactly 12 P1 rows and
12 P4 rows — 96 and 96 in total, a ratio of 1.000.** (`conflation_evidence` in
`step2_metrics.json`.) **[I]** The worst case for the ranking is therefore a clean 50/50
split, and I can bound it rather than speculate about it.

**[O] The robustness re-run** (`split_conflated` in `src/rank_b.py`) halves the case count
into `hr_expense_claim_P1` and `hr_pay_change_P4`, inherits every per-case measurement
unchanged — both halves are worked on the same screen with the same selectors, the same
paste behaviour and the same documents, so only frequency changes, which is exactly what
the test is meant to isolate — and scores the pay-change half at sensitivity 0.60 and the
expense half at 0.45 **[A]**, since only one of them touches payroll.

| Ranking view | 1st | 2nd | Margin |
|---|---|---|---:|
| Base (as one process) | `fin_purchase_order_management` 0.166 | `hr_expense_and_pay_change` 0.090 | 1.8× |
| Conflated label split 50/50 | `fin_purchase_order_management` 0.207 | `hr_attendance_leave_request` 0.094 | 2.2× |
| Extension-less session removed | `fin_purchase_order_management` 0.207 | `hr_expense_and_pay_change` 0.122 | 1.7× |
| Thin worklist 種別 evidence dropped | `fin_purchase_order_management` 0.184 | `hr_attendance_leave_request` 0.129 | 1.4× |

**[I] The recommendation is the same process in all four views, and the conflated label
never reaches first place in any of them.** Splitting it only lowers it further (the two
halves land 4th and below), so the answer does not depend on resolving a question step 1
could not resolve. **[I]** Where the split *would* matter is in a Phase-2 build: the two
halves need different approval routing, and an automation that treated the worklist as
one queue would silently apply expense-claim handling to a pay change. The client should
resolve the split before anyone automates that screen — and the cheapest way is not more
log analysis, it is asking the portal team to put the P-code in the row's DOM.

---

## 6. How the degraded sessions and the thin OCR were handled in the counts

**[O]** 7 of dataset A's 63 sessions and **1 of dataset B's 15** never connected the
browser extension. B's is `ses_20260701-192455-NEELA9BAF`, contributing **49 of the 684
segments (7.2%)**. Step 1 measured what that costs on the A analogue of this population:
system identity ≈85% correct, route ≈64% correct, temporal IoU 0.635 against 0.891 for
extension-present sessions.

**[O] Where those 49 land:** `hr_expense_and_pay_change` 19 (14.2% of its cases),
`hr_onboarding` 10 (15.4%), `fin_purchase_order_management` 8 (10.4%),
`ops_inventory_management` 8 (11.9%), `fin_invoice_approval` 4 (5.4%). The other seven
processes have none.

**[I] Decision: keep them in the headline counts, and re-run the ranking without them.**
Dropping them would silently understate five processes by a tenth; keeping them silently
without saying so would launder a 64%-accurate route label into a frequency. So both
numbers are published — `degraded_share` is a column in the metrics table, and
`robustness_without_degraded_session` in `step2_metrics.json` is the full re-measurement
with that session excluded. **[O]** The top-ranked process is unchanged and its margin
widens slightly (§5 table). **[I]** It widens because the degraded session is
disproportionately `hr_expense_and_pay_change`, so removing it costs the runner-up more
than the winner — the recommendation is not being propped up by the low-confidence 7%.

**[O] A second, independent coverage gap: the worklist 種別 channel.** It reads the
adjustment flag out of worklist OCR, so it inherits the OCR sampling. Coverage is 8–9
sessions on the three `payroll-items` screens and **a single session** on six others,
including the top-ranked process (4 of 24 rows flagged 調整) and
`hr_attendance_leave_request` (5 of 12 — the highest in the set). **[I]** One session is
enough to prove a variant exists but not to estimate its rate, so the third re-run
discards every reading resting on fewer than three sessions and falls back to the other
two channels. `hr_attendance_leave_request` rises from 3rd to 2nd; the top-ranked process
is unchanged. **[I]** Noting which way this cuts: dropping the thin evidence *helps* the
runner-up and the winner still holds.

**[O] Multi-tab OCR bleed** (6 of B's 15 sessions work with 2–3 tabs open) can put a
second screen's worklist into one blob. Mitigated by taking the median across sessions
rather than a pooled sum, so one bled blob moves the estimate rather than setting it.
Not eliminated, and it is the reason `worklist_variant_rows` is published alongside the
rate.

---

## 7. Recommendation for Step 3

**Build `fin_purchase_order_management` (発注管理).** It is the highest Client_ROI process
*and* has high Build_Fit (0.80, second only to `hr_attendance_leave_request`'s 0.97).
**Nothing was deferred to reach that answer, and no easy process is being relabelled as
#1** — the two rankings simply agree here, which is the fortunate case rather than the
usual one.

**[I] Why it is also honestly demonstrable this week.** 90.6% of its cycle happens in
surfaces a mock can reproduce faithfully — the portal worklist and the note pad. 77
observed executions is comfortably enough to write a process definition and test against
it. Its one recurring companion document (`shinkuitorihikisaki_touroku_tetsuzuki`, the
supplier-registration procedure) accounts for 0.78 s of an 11 s cycle, so a prototype
that skips it is not hiding the hard part — there is no hard part hidden there. And it
exercises the complete row → note → paste → commit loop end to end, which is the loop all
twelve processes share.

**[O] Its whole input surface is inside the DOM.** Every one of its 76 clipboard events
was copied from the portal (72) or from the note pad (4); **none from Word, Excel or any
file** (§3.1). **[I]** That is a build-cost statement, not a restatement of the ranking:
the tool needs no document parser, no file-open dialog, no Excel reader and no OCR
fallback — it reads the row out of the DOM and writes the note back into the DOM. Every
integration this project does *not* have to build is one that cannot break in front of
the client, and it is why 発注管理 is cheaper to build than its Build_Fit of 0.80 alone
suggests.

**[I] Scope: a shared foundation plus one process definition, not a single-purpose
script.** **[O]** All twelve processes are worked through one DOM contract with five
selector prefixes. **[I]** A tool that hard-codes `#rt-note` and `#btn-rt-ok` throws away
eleven-twelfths of the work for no saving; a tool that takes the prefix, the note
template and the commit target as a per-process definition covers 発注管理 now and is a
configuration change away from the next candidate. The ceiling is higher and the floor is
the same, because the first definition has to be written either way.

**[I] What the runner-up would have cost.** `hr_attendance_leave_request` is the more
buildable process (Build_Fit 0.97 against 0.80) and I am deliberately not choosing it.
It is a third of the winner's Client_ROI, its 0.42 variant rate rests on one session of
OCR, and building the most prototypable process rather than the most valuable one is the
exact failure the two-score split exists to prevent. If the foundation lands early, it is
the cheapest second definition to add — same `la` prefix family, zero new integrations.

**[I] What is explicitly Phase 2, and why.**
- **`hr_expense_and_pay_change`** (Impact 1.00) — needs the P1/P4 split resolved first
  (§5), and writing to payroll and tax withholding is the highest governance bar in the
  set. Both are real blockers, not scheduling ones: no amount of prototype time makes an
  unattended payroll write approvable, and the split needs a change in the portal's DOM,
  not a better model.
- **`ops_contract_management`, `fin_payment_processing`, `fin_manager_expense_approval`,
  `hr_onboarding`** — 30–42% of each case is a human reading a 規定 and then deciding.
  **[I]** A prototype that automated these would have to either fake the decision or skip
  it, and either would misrepresent what the tool does. The honest form for these is
  assistive — surface the right clause and pre-fill the note, leave the decision and the
  commit to the operator — which is a different product and a different conversation with
  the client. **[O] An independent second reason, measured rather than argued:** 31–38% of
  the clipboard content in these four is copied **out of Word** (§3.1), against 0% for the
  recommended target. So even setting the judgment question aside, each of them needs a
  document reader the recommended build does not — a second integration on top of a
  decision the tool should not be making.
- **`fin_invoice_approval`** (Impact 0.78, 3rd highest) — the interesting one. Its Word
  time is a *table* lookup (2.35 s in 月次定額取引先一覧) rather than a policy read (0.54 s),
  so unlike the four above it is not blocked on judgment. It is held back by approval
  authority over spend (sensitivity 0.50) and by a three-way integration surface
  (the vendor list, `expense_calc` in Excel, and a file-open dialog). **[I]** Best candidate for the second wave once the foundation exists and the
  approval question has been answered by the client rather than by me.

---

## 7.5 What it would take to build this, and what would bite

**[O] Every one of the 684 observed cases is a happy path.** Four places a failed case
would have to leave a trace were checked, and all four are empty. The fifth row is in the
table because it is the one that is *not* empty:

| Where a failed case would have to show up | Observed in dataset B |
|---|---:|
| `browser_error` events, total | 38 |
| …of those, inside a segmented case | **0** |
| …of those, carrying any text | **0** |
| Error wording rendered into the portal, inside a case | **0** |
| Cases that committed more than once (a retry or a duplicate) | **0** of 684 |
| Cases with no observed commit at all | 57 of 684 |

All 38 `browser_error` events carry an empty text field and sit at the three portal roots (`http://127.0.0.1:5134/` 14 · `http://127.0.0.1:5132/` 13 · `http://127.0.0.1:5133/` 11) — page load, not case failure.

**[O] The one place an abandoned case could be hiding** is the last row: 57 of the 684
cases show no commit click. **[I]** That is not evidence of failure — step 1's boundary
accuracy (F1 0.858 on A) is enough to put a commit on the wrong side of a segment edge,
and `commit_rate` tracks `template_conformance` almost exactly, which is what a boundary
artefact looks like and not what an error would look like. But the logs cannot separate
"the commit fell outside the segment" from "the operator gave up on this case", and that
is the honest statement of the gap.

**[I] What that forces.** The portal's failure behaviour cannot be specified from this
data, because it was never recorded. What the portal does when a purchase order is
rejected, when the supplier is already registered, when the worklist has moved under the
automation, when the session has timed out — none of it is in the logs, and no amount of
further analysis of these logs will produce it. This is the risk that only surfaces once
implementation begins, and it is the one thing in this report that a client conversation
resolves faster than a measurement does.

**[A] The design that follows.** Because the error branch cannot be learned, it has to be
made safe by construction rather than by coverage: **commit once — never retry blind;
verify the write actually landed by re-reading the row before moving on; and stop the run
and queue the case for a human on anything the definition does not recognise.** An
automation that cannot recognise a failure must not be allowed to guess through one, and
with **no case in the data committing twice**, there is no evidence anywhere in these logs
that a second commit on the same case is even idempotent.

**[A] The honest asymmetry.** That error branch is plausibly a third of the build effort —
verify-after-write, the exception queue, the stop conditions, and the tests that fake
failures the logs never showed — while being **0% of the observed logs**. It is invisible
in every column of §4: the recommended target's `structured_target` 0.90, `variant_rate`
0.17 and `mock_fidelity` 0.91 are all measurements of a world in which nothing goes wrong.
The ranking is a comparison between processes and is not disturbed by this — the blind spot is identical
for all twelve — but any estimate of how long the Step-3 build takes should be read with
it in mind.

**[A] Three governance questions the logs also cannot answer**, and they are the client's
to settle before an unattended run, not mine: who owns the exception queue when the
automation stops (an automation with no named human behind it silently becomes a backlog);
what the agent authenticates as, since the logs show an operator's own session and a
service account with its own permissions is a different governance object from a person's
login; and what the audit trail must contain, given that `sensitivity` 0.20 assumes a
purchase order is reversible — which is only true if there is a record of what was
written and by which run.

---

## 8. What this analysis cannot tell you

1. **[A] The sensitivity table is a judgement, and it moves the answer.** It is the only
   unmeasured input. `fin_purchase_order_management` is scored 0.20 because 発注管理
   against a registered supplier is operational and reversible; if the client's finance
   function treats any purchase order as a committed spend, that number should rise and
   the ranking should be re-run. The table is one block in `src/roi.py` for exactly this
   reason.
2. **[O]+[I] Positional row targeting is a universal, unmitigated risk.** Every process
   selects its case with `tr:nth-of-type(N)` and no case id appears in the row's DOM. An
   automation built on row position is correct only as long as the worklist sort order,
   filter and pagination are identical to the operator's. This does not discriminate
   between processes — it applies to all twelve equally — but it is the single most
   likely thing to break a Step-3 build on real screens, and the mitigation is a portal
   change (expose the case id in the row), not a cleverer selector.
3. **[O] There is no ground truth for dataset B.** Every case count here inherits step
   1's boundary accuracy, which was measured on a *different* theme (A: boundary F1
   0.858, mean IoU 0.865, 91.0% of executions matched at IoU ≥ 0.5). Those are the best
   available estimates of B's accuracy and they are not measurements of it.
4. **[O] One process rests on one session.** `fin_budget_variance_analysis` — 8 cases.
   Its Impact of 0.11 should be read as "unknown, probably small", not as a measurement.
5. **[A] `variant_rate` takes the maximum of three channels** rather than combining them.
   This deliberately errs toward finding branching, because an unhandled branch in
   production is more expensive than a process passed over. A client who disagrees should
   re-run with the median.
6. **[O] Dead time is attributed to the preceding case** (step-1 limitation 6, right 94.8%
   of the time on A). This inflates median cycle where an operator genuinely idled
   between cases, and it inflates it more for the slow processes than the fast ones —
   which means Impact is, if anything, slightly generous to the judgment-heavy processes
   that already rank low.
7. **[O] The generator is visible in the data.** Both datasets are scripted runs
   (`dwell_scale 1.4`, seeded). The regularities this analysis leans on — one row-click
   per case, a consistent commit button, a clean 種別 flag — may be crisper here than in
   organic behaviour.
