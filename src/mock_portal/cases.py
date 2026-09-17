"""Synthetic case seed for the 発注管理 (fin_purchase_order_management) mock screen.

WHAT IS MEASURED AND WHAT IS INVENTED
-------------------------------------
MEASURED (recovered from dataset B's own `context.extracted_text` and
`browser_form_input` payloads on `http://127.0.0.1:5133/#/resident-tax`):

  * the screen chrome            財務会計システム / 2026年度 · 経理部門 /
                                 佐藤 直樹 · 経理マネージャー / breadcrumb ダッシュボード / 発注管理
  * the worklist column family   ID · 社員ID · 氏名 · 区分 · 金額 · 種別 · ステータス
  * the case-id format           P10-07054374-0NN
  * the procedure format         発注管理 PO-2026-5NNN
  * the supplier vocabulary      8 names, below (counts in dataset B in the comment)
  * the detail-pane field names  name · emp_id · variant · procedure · target_month ·
                                 reason · コメント
  * the note-field placeholder   処理内容を入力…   (from browser_form_input on #rt-note)
  * the note template            発注管理処理。{reason}。発注書確認・登録完了。
                                 — 68 distinct note values recovered, all conform
  * the reason sub-grammar       {発注区分}：{品目}　数量 {n}　合計 {amount}円　{flag}
  * 発注区分 vocabulary           年間契約 21 · スポット発注 17 · 定期発注 14 · 緊急発注 9 · 発注変更 7
  * 品目 vocabulary               8 items, below
  * flag vocabulary              通常 52 · 緊急 9 · 要注意 7
  * the ⚠ row marker             observed on 福岡システム設計 in a 発注管理 worklist capture

SYNTHETIC (values were never logged — clipboard payloads carry `text_content: null`,
only `text_length`):

  * every individual case: the specific supplier/item/quantity/amount pairing,
    the 社員ID assignment, the target month, the row ordering.

The *structure* is reconstructed from the logs. The *values* are made up.
The UI says so on screen.
"""

from __future__ import annotations

import json
import random

# --- measured vocabularies -------------------------------------------------

SUPPLIERS = [
    ("V3003", "東京電子工業株式会社"),      # 40 observations in dataset B
    ("V3004", "関西物流サービス"),          # 36
    ("V3007", "福岡システム設計"),          # 31
    ("V3002", "大和商事株式会社"),          # 26
    ("V3008", "沖縄物流センター"),          # 25
    ("V3001", "株式会社山田製作所"),        # 20
    ("V3005", "グローバルテック合同会社"),  # 20
    ("V3006", "北陸部品工業株式会社"),      # 18
]

ORDER_KINDS = ["年間契約", "スポット発注", "定期発注", "緊急発注", "発注変更"]

ITEMS = [
    "サーバー保守部品", "梱包材料", "包装資材", "電子基板ユニット",
    "測定機器", "事務用品", "精密部品一式", "工場設備部品",
]

# The reason-line flag. MEASURED: 緊急発注 always carried 緊急 and 発注変更 always
# carried 要注意 in the 68 recovered notes; everything else carried 通常.
FLAG_BY_KIND = {
    "緊急発注": "緊急",
    "発注変更": "要注意",
}

# 種別 ∈ {定常, 調整}. MEASURED as the portal's uniform worklist flag.
# ENGINEERING ASSUMPTION: the mapping 種別 -> detail-pane `variant` below.
# Only one `variant` value was ever captured on this screen (`V1_routine_po`);
# `V2_adjust_po` is invented to give the 調整 branch a value.
VARIANT_BY_SHUBETSU = {
    "定常": "V1_routine_po",
    "調整": "V2_adjust_po",
}

BATCH_ID = "P10-07054374"       # MEASURED format, from a real worklist capture
PO_BASE = 5094                  # MEASURED: first PO number seen on that worklist
TARGET_MONTH = "2026-07"        # MEASURED from the detail pane capture


def _reason(kind: str, item: str, qty: int, amount_yen: int) -> str:
    flag = FLAG_BY_KIND.get(kind, "通常")
    return f"{kind}：{item}　数量 {qty}　合計 {amount_yen:,}円　{flag}"


def _case(idx: int, emp_id: str, name: str, kind: str, item: str,
          qty: int, amount_yen: int, shubetsu: str, status: str = "未処理",
          *, seeded_failure: str | None = None,
          supplier_unregistered: bool = False,
          blank_reason: bool = False) -> dict:
    case_id = f"{BATCH_ID}-{idx:03d}"
    procedure = f"発注管理 PO-2026-{PO_BASE + idx - 1}"
    reason = "" if blank_reason else _reason(kind, item, qty, amount_yen)
    return {
        "case_id": case_id,
        "row": idx,
        # --- worklist row (the 7 columns) ---
        "row_cells": {
            "id": case_id,
            "emp_id": emp_id,
            "name": name + (" ⚠" if supplier_unregistered else ""),
            "kubun": procedure,
            "amount": f"{amount_yen:,}円",
            "shubetsu": shubetsu,
            "status": status,
        },
        # --- detail pane ---
        "detail": {
            "name": name,
            "emp_id": emp_id,
            "variant": VARIANT_BY_SHUBETSU.get(shubetsu, ""),
            "procedure": procedure,
            "target_month": TARGET_MONTH,
            "reason": reason,
            "amount": f"{amount_yen:,}円",
            "comment": "",
        },
        # --- mock-only server-side behaviour, never read by the engine ---
        "_mock": {
            "supplier_unregistered": supplier_unregistered,
            "seeded_failure": seeded_failure,
        },
    }


def seed(n: int = 18, rng_seed: int = 510448) -> list[dict]:
    """Build the worklist.

    `rng_seed` 510448 is the seed the dataset-B generator itself ran with
    (visible in the PowerShell capture at the top of every session). Reusing it
    is cosmetic — it just makes this seed reproducible.

    Four cases are deliberately unautomatable. They are the point of the
    exception queue: dataset B contains 684 happy paths and zero failures
    (§7.5), so the failure branch cannot be learned from the logs and has to be
    exercised against seeded ones instead.
    """
    rng = random.Random(rng_seed)
    cases: list[dict] = []

    # Rows that must land in the exception queue, and the stage that must catch them.
    failures = {
        6:  ("REQUIRED_FIELD_MISSING",  "reason is blank — nothing to compose the note from"),
        11: ("STATUS_NOT_COMMITTABLE",  "row is already 完了 — committing again would double-commit"),
        14: ("ENUM_UNRECOGNISED",       "種別 is 保留, which is not in the definition's enum"),
        17: ("VERIFY_FAILED",           "supplier not registered — portal accepts the click, "
                                        "row never flips; only the read-back sees it"),
    }

    for idx in range(1, n + 1):
        emp_id, name = SUPPLIERS[rng.randrange(len(SUPPLIERS))]
        kind = ORDER_KINDS[rng.randrange(len(ORDER_KINDS))]
        item = ITEMS[rng.randrange(len(ITEMS))]
        qty = rng.randint(10, 500)
        amount = qty * rng.randint(900, 48000)
        shubetsu = "調整" if rng.random() < 0.17 else "定常"   # 0.17 = measured variant_rate

        code = failures.get(idx, (None, None))[0]

        if code == "REQUIRED_FIELD_MISSING":
            c = _case(idx, emp_id, name, kind, item, qty, amount, "定常",
                      seeded_failure=code, blank_reason=True)
        elif code == "STATUS_NOT_COMMITTABLE":
            c = _case(idx, emp_id, name, kind, item, qty, amount, "定常",
                      status="完了", seeded_failure=code)
        elif code == "ENUM_UNRECOGNISED":
            c = _case(idx, emp_id, name, kind, item, qty, amount, "定常",
                      seeded_failure=code)
            c["row_cells"]["shubetsu"] = "保留"       # not in {定常, 調整}
            c["detail"]["variant"] = "V9_unknown"
        elif code == "VERIFY_FAILED":
            c = _case(idx, "V3007", "福岡システム設計", kind, item, qty, amount,
                      "定常", seeded_failure=code, supplier_unregistered=True)
        else:
            c = _case(idx, emp_id, name, kind, item, qty, amount, shubetsu)

        cases.append(c)

    return cases


if __name__ == "__main__":
    print(json.dumps(seed(), ensure_ascii=False, indent=2))
