"""Render the report tables that are generated rather than written by hand.

Every number in reports/step2_analysis.md that can come from the generated
artefacts does come from them: this module reads step2_process_metrics.csv and
step2_metrics.json and prints the markdown, and verify_step2.py checks the
report still matches.  Nothing here recomputes anything.

Run:  cd src && python3 report_tables.py [paste_sources|failure_path]
"""
from __future__ import annotations

import csv
import json
import os
import sys

from common import REPORTS

CSV_PATH = os.path.join(REPORTS, "step2_process_metrics.csv")
JSON_PATH = os.path.join(REPORTS, "step2_metrics.json")


def rows() -> list[dict]:
    with open(CSV_PATH, encoding="utf-8", newline="") as fh:
        return sorted(csv.DictReader(fh), key=lambda r: int(r["rank"]))


def metrics() -> dict:
    return json.load(open(JSON_PATH, encoding="utf-8"))


def clip_total(r: dict) -> int:
    return sum(int(p.rsplit(":", 1)[1]) for p in r["paste_sources"].split(";") if p)


def paste_sources() -> str:
    out = ["| # | Process | Clipboard events | From the portal | From the note pad "
           "| **From a document** |",
           "|---:|---|---:|---:|---:|---:|"]
    for r in rows():
        out.append(
            f"| {r['rank']} | `{r['label']}` | {clip_total(r)} "
            f"| {float(r['paste_source_in_portal']):.2f} "
            f"| {float(r['paste_source_scratch']):.2f} "
            f"| **{float(r['paste_source_document']):.2f}** |")
    return "\n".join(out)


def failure_path() -> str:
    f = metrics()["failure_path_evidence"]
    urls = " · ".join(f"`{u}` {n}" for u, n in f["browser_error_urls"].items())
    return "\n".join([
        "| Where a failed case would have to show up | Observed in dataset B |",
        "|---|---:|",
        f"| `browser_error` events, total | {f['browser_error_events']} |",
        f"| …of those, inside a segmented case | **{f['browser_error_inside_a_segment']}** |",
        f"| …of those, carrying any text | **{f['browser_error_with_text']}** |",
        f"| Error wording rendered into the portal, inside a case | "
        f"**{f['portal_text_error_tokens_in_segments']}** |",
        f"| Cases that committed more than once (a retry or a duplicate) | "
        f"**{f['cases_committing_more_than_once']}** of {f['cases']} |",
        f"| Cases with no observed commit at all | "
        f"{f['cases_with_no_observed_commit']} of {f['cases']} |",
        "",
        f"All {f['browser_error_events']} `browser_error` events carry an empty text field "
        f"and sit at the three portal roots ({urls}) — page load, not case failure.",
    ])


TABLES = {"paste_sources": paste_sources, "failure_path": failure_path}

if __name__ == "__main__":
    want = sys.argv[1:] or sorted(TABLES)
    for i, name in enumerate(want):
        if i:
            print()
        print(TABLES[name]())
