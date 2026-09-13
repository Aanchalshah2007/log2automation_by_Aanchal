"""Human-readable label for each process discovered in a dataset.

The label is derived from the screen name the portal itself renders, which
`screenmap.learn` recovers from `context.extracted_text`.  The table below is a
transliteration of those Japanese names -- nothing here decides *what* the
processes are, it only gives the discovered ones a readable handle.  Any screen
not in the table still gets a stable label (`<system>_<route>`), so a process can
never go unnamed just because it was not anticipated.
"""
from __future__ import annotations

# Screen names as rendered by dataset B's portal -> label.
# (Dataset A's names are included so the same code labels both datasets.)
FROM_SCREEN_NAME = {
    # ---- dataset B (theme M2) ----
    "経費精算・給与変更":   "hr_expense_and_pay_change",
    "勤怠・休暇申請":       "hr_attendance_leave_request",
    "入社手続き":           "hr_onboarding",
    "福利厚生申請":         "hr_benefits_application",
    "住民税・その他":       "hr_resident_tax_misc",
    "請求書承認・経費精算": "fin_invoice_approval",
    "経費承認（管理職）":   "fin_manager_expense_approval",
    "支払処理":             "fin_payment_processing",
    "予算差異分析":         "fin_budget_variance_analysis",
    "発注管理":             "fin_purchase_order_management",
    "在庫管理":             "ops_inventory_management",
    "契約管理":             "ops_contract_management",
    "IT申請":               "ops_it_access_request",
    # ---- dataset A (theme M1) ----
    "住民税通知確認":       "hr_resident_tax_notice_check",
    "住民税通知":           "hr_resident_tax_notice_check",
    "給与備考・控除整備":   "hr_payroll_note_deduction",
    "給与備考・控除":       "hr_payroll_note_deduction",
    "育児・産休申請確認":   "hr_parental_leave_check",
    "育児・産休申請":       "hr_parental_leave_check",
    "社保・年金補正対応":   "hr_social_insurance_correction",
    "社保・年金補正":       "hr_social_insurance_correction",
    "入社照合・手当確認":   "hr_onboarding_allowance_check",
    "入社照合":             "hr_onboarding_allowance_check",
    "請求書承認":           "fin_invoice_approval",
    "経費精算承認":         "fin_expense_approval",
    "銀行勘定照合":         "fin_bank_reconciliation",
    "支払処理 ":            "fin_payment_processing",
    "受注処理":             "ops_order_processing",
    "在庫調整":             "ops_stock_adjustment",
    "仕入先連絡":           "ops_supplier_contact",
    "出荷追跡":             "ops_shipment_tracking",
    "返品処理":             "ops_returns_processing",
}


def build(screen_map: dict[tuple[str, str], str]) -> dict[tuple[str, str], str]:
    """(system, route) -> label, using the screen names learned from the data."""
    out: dict[tuple[str, str], str] = {}
    for (sysn, jp), route in screen_map.items():
        key = (sysn, route)
        lab = FROM_SCREEN_NAME.get(jp)
        if lab and key not in out:
            out[key] = lab
    return out


def label_for(ctx: tuple[str, str], table: dict[tuple[str, str], str]) -> str:
    return table.get(ctx, f"{ctx[0]}_{ctx[1].replace('-', '_')}")
