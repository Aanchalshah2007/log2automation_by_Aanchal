"""Scoring model for the step-2 automation ranking.

Two scores are produced for every process, and they are deliberately **not**
blended:

  Client_ROI = Impact x Automatability x Client_Feasibility
      What the client should automate, independent of who builds it and how
      long they have.  This is the ranking.

  Build_Fit
      Whether *I* can put a convincing prototype of it on a mock portal in the
      four days left.  This is a property of my week, not of the client's
      business, so it is reported beside the ranking and never folded into it.

Every factor is in [0, 1] and every product is multiplicative on purpose: a
high-volume process that needs a per-case policy judgment, or whose targets are
unreliable, should be crushed rather than rewarded for its volume.

Each factor below is marked with where its value comes from:
  [O] measured from dataset B's own events
  [A] an engineering assumption, stated so it can be argued with and changed

The two assumption tables (SENSITIVITY, BRANCHING_COST) are the only places in
this module where a number is not derived from the logs.  They are kept here,
in one block, so a reviewer can change a policy judgement and re-rank.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any

# ---------------------------------------------------------------------------
# [A] Governance sensitivity: how hard it is to get sign-off for letting an
#     unattended agent WRITE to this process, on a 0 (routine) to 1 (forbidden)
#     scale.  This is a policy judgement, not a measurement.  The rule applied:
#
#       changes someone's pay or tax withholding      .55 - .60
#       releases money / carries approval authority    .45 - .55
#       grants system access                           .45
#       touches personal HR data                       .30 - .40
#       operational records, legal weight              .35
#       operational records, routine                   .15 - .20
#
#     The logs cannot tell us a company's appetite for this.  What the logs DO
#     tell us is which process touches which record type, and that is what the
#     rule is keyed on.
SENSITIVITY: dict[str, float] = {
    "hr_expense_and_pay_change":     0.60,  # 昇給 / 扶養控除変更 -> payroll + tax
    "fin_payment_processing":        0.55,  # releases money to a supplier
    "fin_invoice_approval":          0.50,  # approval authority over spend
    "fin_manager_expense_approval":  0.50,  # approval authority over spend
    "ops_it_access_request":         0.45,  # grants system access
    "hr_onboarding":                 0.40,  # personal data, new employee record
    "hr_benefits_application":       0.40,  # personal data, 育児/介護/家族手当
    "ops_contract_management":       0.35,  # legally binding documents
    "hr_attendance_leave_request":   0.30,  # personal data, low monetary value
    "fin_purchase_order_management": 0.20,  # operational, reversible
    "fin_budget_variance_analysis":  0.20,  # analysis, read-mostly
    "ops_inventory_management":      0.15,  # operational, reversible
}
DEFAULT_SENSITIVITY = 0.40

# [A] Each additional system or reference document the automation has to read,
#     beyond the portal itself, costs this much of the low_branching factor.
#     0.25 means a process touching four extra surfaces scores ~0.5.
BRANCHING_COST = 0.25
BRANCHING_FREE = 1          # [A] one companion surface (the note pad) is free

# [A] Of the three DOM targets an automation needs per case -- the worklist row,
#     the note field and the commit button -- two are id-anchored (`#pi-note`,
#     `#btn-pi-ok`) and one is positional (`#pi-table > tbody > tr:nth-of-type(N)`).
#     Measured across all 12 processes in section "selectors" of the metrics
#     table: the split is identical everywhere, so this constant carries no
#     ranking information.  It is kept because dropping it would overstate the
#     absolute feasibility of every process.
ID_ANCHOR_SHARE = 2 / 3

# [A] Below this many observed executions there is not enough evidence to write
#     and test a process definition.
EVIDENCE_FLOOR_CASES = 30


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


@dataclass
class Factors:
    """Every intermediate quantity, so the final ordering can be audited."""
    # --- Impact ---
    impact: float = 0.0
    case_seconds: float = 0.0            # [O] cases x median cycle

    # --- Automatability ---
    automatability: float = 0.0
    repeatability: float = 0.0           # [O] template conformance + tempo spread
    copy_paste_ratio: float = 0.0        # [O] pasted chars / (pasted + typed)
    variant_rate: float = 0.0            # [O] declared case-type branching
    judgment_step: float = 0.0           # [O] regulation dwell / cycle

    # --- Client_Feasibility ---
    client_feasibility: float = 0.0
    structured_target: float = 0.0       # [O] row -> note -> commit observable
    stable_selectors: float = 0.0        # [O] route purity x [A] id-anchor share
    low_branching: float = 0.0           # [O] surface count x [A] cost per surface
    sensitivity: float = 0.0             # [A] governance table above

    # --- the two scores ---
    client_roi: float = 0.0
    build_fit: float = 0.0
    # Build_Fit parts
    loop_completeness: float = 0.0       # [O]
    evidence_density: float = 0.0        # [O]
    mock_fidelity: float = 0.0           # [O] share of cycle in Edge + Notepad
    selector_determinism: float = 0.0    # [O] route purity

    notes: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def impact(case_seconds: float, max_case_seconds: float) -> float:
    """[O] frequency x median cycle, normalised against the busiest process.

    Deliberately NOT multiplied by the operator count.  Dataset B's four
    machines each touch 9-11 of the 12 processes, which is a property of how the
    sessions were recorded, not of how the work is staffed.  Operator count is
    reported in the metrics table and never enters a score.
    """
    return clamp(case_seconds / max_case_seconds) if max_case_seconds else 0.0


def repeatability(template_conformance: float, cv: float) -> float:
    """[O] Does the process run the same way every time?

    Two independent views, averaged: how often the full row -> note -> commit
    template is actually observed, and how tight the cycle time is around its
    own mean.  A process can be uniform in shape but ragged in time (a variable
    lookup inside it) or the reverse, and both matter.
    """
    return clamp(0.5 * (clamp(template_conformance) + clamp(1.0 - cv)))


def copy_paste_ratio(clip_chars: float, typed_chars: float) -> float:
    """[O] What share of the content entered per case arrived via the clipboard?

    `clipboard_change.text_length` is populated on all 872 of B's clipboard
    events (median 42 chars), so this is a real character count and not a proxy
    for one.  Content that is pasted came from somewhere a program can also
    read; content that is typed came from a person's head.
    """
    total = clip_chars + typed_chars
    return clamp(clip_chars / total) if total else 0.0


def judgment_step(regulation_dwell_s: float, median_cycle_s: float) -> float:
    """[O] Share of the case spent reading a regulation document.

    Word documents split cleanly into two kinds in dataset B:
      * 規定 / 手続き / checklist -- a policy a human reads and then decides
        (`settai_keihi_kitei`, `keiyaku_kaijo_tetsuzuki`, ...)
      * 一覧 -- a reference *table* that is looked up
        (`getsujitsu_teigaku_torihikisaki_ichiran`)
    Only the first counts as judgment.  A table lookup is data an automation can
    join against; a policy read is a decision it cannot honestly make.
    """
    return clamp(regulation_dwell_s / median_cycle_s) if median_cycle_s else 0.0


def automatability(repeat: float, cp: float, variant: float, judgment: float) -> float:
    return clamp(repeat) * clamp(cp) * clamp(1.0 - variant) * clamp(1.0 - judgment)


def low_branching(integration_surface: int) -> float:
    """[O]+[A] How many systems and documents must the automation keep in sync?

    `integration_surface` counts the distinct non-browser applications plus the
    distinct reference documents opened inside the process's cases.  This is the
    *build* surface, and it is a different thing from `variant_rate`, which is
    the *case* branching -- a process can have one handling pattern spread over
    four documents, or four handling patterns inside one screen.
    """
    extra = max(0, integration_surface - BRANCHING_FREE)
    return clamp(1.0 / (1.0 + BRANCHING_COST * extra))


def stable_selectors(route_purity: float) -> float:
    return clamp(ID_ANCHOR_SHARE * clamp(route_purity))


def client_feasibility(structured: float, selectors: float,
                       branching: float, sensitivity: float) -> float:
    return clamp(structured) * clamp(selectors) * clamp(branching) * clamp(1.0 - sensitivity)


def build_fit(loop_completeness: float, cases: int,
              mock_fidelity: float, route_purity: float) -> float:
    """Can a convincing end-to-end prototype of this exist in ~4 days on a mock?

    Not a client-value question and not part of the ranking.  Four things have
    to hold: the full row -> note -> paste -> commit loop is actually present in
    the data; there are enough observed executions to write a definition
    against; the cycle happens in surfaces a mock can reproduce honestly (the
    portal and the note pad, not a Word regulation a human is reading); and the
    process's own route is unambiguous in the logs.
    """
    evidence = clamp(cases / EVIDENCE_FLOOR_CASES)
    return clamp(loop_completeness) * evidence * clamp(mock_fidelity) * clamp(route_purity)


def score(m: dict[str, Any], max_case_seconds: float) -> Factors:
    """Turn one process's measured metrics into both scores."""
    f = Factors()

    f.case_seconds = m["cases"] * m["median_s"]
    f.impact = impact(f.case_seconds, max_case_seconds)

    f.repeatability = repeatability(m["template_conformance"], m["cv"])
    f.copy_paste_ratio = copy_paste_ratio(m["clip_chars_per_case"], m["typed_chars_per_case"])
    f.variant_rate = clamp(m["variant_rate"])
    f.judgment_step = judgment_step(m["regulation_dwell_s_per_case"], m["median_s"])
    f.automatability = automatability(f.repeatability, f.copy_paste_ratio,
                                      f.variant_rate, f.judgment_step)

    f.structured_target = clamp(m["template_conformance"])
    f.stable_selectors = stable_selectors(m["route_purity"])
    f.low_branching = low_branching(m["integration_surface"])
    f.sensitivity = SENSITIVITY.get(m["label"], DEFAULT_SENSITIVITY)
    f.client_feasibility = client_feasibility(f.structured_target, f.stable_selectors,
                                              f.low_branching, f.sensitivity)

    f.client_roi = f.impact * f.automatability * f.client_feasibility

    f.loop_completeness = clamp(m["template_conformance"])
    f.evidence_density = clamp(m["cases"] / EVIDENCE_FLOOR_CASES)
    f.mock_fidelity = clamp(m["mockable_dwell_share"])
    f.selector_determinism = clamp(m["route_purity"])
    f.build_fit = build_fit(f.loop_completeness, m["cases"],
                            f.mock_fidelity, f.selector_determinism)
    return f
