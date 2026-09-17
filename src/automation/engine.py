"""Deterministic, config-driven automation engine for the step-3 prototype.

    python3 src/automation/engine.py \
        --definition src/automation/definitions/fin_purchase_order_management.json \
        --jobs build/jobs.json \
        --audit build/audit_log.jsonl

Reads a per-process JSON definition and a list of human-approved jobs, drives the
portal through the motif dataset B actually shows — open row → focus note → write →
commit → **re-read the row and confirm the write landed** — and writes one audit
record per case. Progress is streamed to stdout as JSON lines so the review UI can
show each step as it happens.

THERE IS NO LLM ANYWHERE IN THIS FILE, AND THAT IS A DESIGN DECISION.
Every value written to the portal is either read out of the DOM or composed by the
definition's `write.template`, and the same input produces the same output on every
run. A model in this loop would buy nothing the definition does not already give —
the motif is one row-click, one templated note and one commit, with 0.17 branching —
and would cost the two things the client actually needs from a data-entry robot:
repeatability, and an audit trail that says exactly why a value was written. Where
judgment is genuinely required, this engine does not guess: it stops and hands the
case to a human (see `_precheck`). That is also why the four judgment-heavy processes
in step 2 §7 were deferred rather than agent-ified.

THE FAILURE BRANCH IS DESIGNED, NOT LEARNED.
Dataset B contains 684 cases and zero observed failures (§7.5), so the portal's real
error behaviour is unknown. The rules below follow from that, not from evidence:
commit at most once, never retry, verify by reading the state back, and route
anything unrecognised to a human. `policy.commit_attempts` is 1 and this engine has
no code path that increments it.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import time
import uuid

REPO = pathlib.Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------
# Environment shim — Linux only.
#
# Playwright's chromium needs a handful of system libraries. On a Linux box where
# they cannot be apt-installed, `setup_browser.sh` unpacks them under build/pwdeps/
# and this puts them on the loader path. Chromium is launched as a CHILD process and
# inherits os.environ at spawn time, so setting the variable here is enough.
#
# An earlier version also called os.execv() to re-exec the interpreter with the new
# environment. That was never necessary (verified: the child picks the variable up
# without it) and it was actively harmful on Windows, where os.execv does not exec —
# the CRT joins the argument list into one unquoted command line, so an interpreter
# path containing a space is split at the space. On a machine whose user folder is
# "Aanchal Shah" that produced, verbatim:
#
#     C:\Users\Aanchal: can't open file 'C:\...\Shah\AppData\...\python.exe'
#
# and the engine never started. `build/pwdeps/` is a Linux artefact but lives on a
# path Windows can also see, so the shim fired there too. It is now POSIX-gated and
# there is no exec anywhere in this program.
# --------------------------------------------------------------------------
def _ensure_browser_libs() -> None:
    if os.name != "posix":
        return
    local = REPO / "build" / "pwdeps" / "root" / "usr" / "lib" / "x86_64-linux-gnu"
    if not local.is_dir():
        return
    current = os.environ.get("LD_LIBRARY_PATH", "")
    if str(local) in current.split(":"):
        return
    os.environ["LD_LIBRARY_PATH"] = f"{local}:{current}".rstrip(":")


_ensure_browser_libs()

from playwright.sync_api import Error as PWError  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402


# --------------------------------------------------------------------------
# progress stream
# --------------------------------------------------------------------------
def rel(path: pathlib.Path) -> str:
    """Repo-relative if it can be, absolute otherwise. `--audit build/x.jsonl` and
    `--audit /tmp/x.jsonl` both have to work."""
    try:
        return str(path.resolve().relative_to(REPO))
    except ValueError:
        return str(path.resolve())


# Everything this engine prints is Japanese: screen names, statuses, the note itself.
# A Windows console defaults to cp1252, which cannot encode any of it — the progress
# stream died with UnicodeEncodeError the first time it tried to report a note. Force
# UTF-8 on both streams before anything is written.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):   # already wrapped, or not a real stream
        pass


def emit(ev: str, **fields) -> None:
    rec = {"ev": ev, "t": round(time.time(), 3)}
    rec.update(fields)
    sys.stdout.write(json.dumps(rec, ensure_ascii=False) + "\n")
    sys.stdout.flush()


# --------------------------------------------------------------------------
# outcomes
# --------------------------------------------------------------------------
AUTOMATED = "automated"
QUEUED = "queued"


class Queue(Exception):
    """Stop working this case and hand it to a human. Never raised after a commit
    has been attempted without the verify result also being recorded."""

    def __init__(self, code: str, detail: str, *, stage: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.stage = stage


# --------------------------------------------------------------------------
# definition
# --------------------------------------------------------------------------
def load_definition(path: pathlib.Path) -> dict:
    d = json.loads(path.read_text(encoding="utf-8"))
    if d.get("state") != "active":
        raise SystemExit(
            f"definition '{d.get('definition_id')}' is state={d.get('state')!r}, not 'active'.\n"
            f"Stub definitions describe a screen that has no mock behind it in this "
            f"prototype. The engine refuses to run one rather than pretend it did."
        )
    for key in ("selectors", "field_schema", "row_schema", "write", "policy", "row_columns"):
        if key not in d:
            raise SystemExit(f"definition is missing required block '{key}'")
    return d


def sel(defn: dict, name: str, **fmt) -> str:
    return defn["selectors"][name].format(**fmt)


# --------------------------------------------------------------------------
# the per-case work
# --------------------------------------------------------------------------
class Runner:
    def __init__(self, page, defn: dict, shots: pathlib.Path | None):
        self.page = page
        self.d = defn
        self.shots = shots

    # -- reads ------------------------------------------------------------
    def read_row(self, row: int) -> dict:
        cells = {}
        for name, col in self.d["row_columns"].items():
            loc = self.page.locator(sel(self.d, "row_cell", n=row, col=col))
            if loc.count() == 0:
                raise Queue("ROW_NOT_FOUND",
                            f"row {row} column {col} ({name}) is not on the page",
                            stage="read_row")
            cells[name] = (loc.inner_text() or "").strip()
        return cells

    def open_row(self, row: int) -> None:
        self.page.click(sel(self.d, "row_open", n=row))

    def read_detail(self) -> dict:
        out = {}
        for field in self.d["field_schema"]:
            loc = self.page.locator(sel(self.d, "detail_field", field=field))
            if loc.count() == 0:
                raise Queue("DETAIL_FIELD_ABSENT",
                            f"detail pane has no element for '{field}'",
                            stage="read_detail")
            out[field] = (loc.inner_text() or "").strip()
        return out

    def read_status(self, row: int) -> str:
        col = self.d["row_columns"]["status"]
        return (self.page.locator(sel(self.d, "row_cell", n=row, col=col))
                .inner_text() or "").strip()

    # -- checks -----------------------------------------------------------
    def precheck(self, case_id: str, row_cells: dict, fields: dict) -> None:
        """Everything that can be refused BEFORE touching the commit button.

        This is the half of the safety story that costs nothing: a case that
        fails here is queued without a single write. The other half is verify,
        which is the only thing that catches a failure the portal does not
        announce.
        """
        # 1. Positional-selector guard. §8.2: the row carries no case id in its
        #    selector, so the automation is correct only while the worklist has
        #    not moved under it. It can at least notice when it has.
        seen_id = row_cells.get("id", "")
        if seen_id != case_id:
            raise Queue(
                "ROW_IDENTITY_MISMATCH",
                f"row holds {seen_id!r}, the approved case was {case_id!r} — "
                f"the worklist moved between review and run",
                stage="precheck")

        # 2. Row-level enums (種別 and friends).
        for name, rule in self.d["row_schema"].items():
            if "enum" in rule:
                value = row_cells.get(name, "")
                if value not in rule["enum"]:
                    raise Queue(
                        "ENUM_UNRECOGNISED",
                        f"row column '{name}' is {value!r}, which the definition does "
                        f"not recognise (expected one of {rule['enum']})",
                        stage="precheck")

        # 3. Status gate. A row that is not in a committable state must never be
        #    committed again — 0 of 684 observed cases committed twice, so there
        #    is no evidence a second commit is idempotent.
        allowed = self.d["row_schema"]["status"]["commit_allowed_from"]
        status = row_cells.get("status", "")
        if status not in allowed:
            raise Queue(
                "STATUS_NOT_COMMITTABLE",
                f"row status is {status!r}; commit is only allowed from {allowed}",
                stage="precheck")

        # 4. Field schema.
        for field, rule in self.d["field_schema"].items():
            value = fields.get(field, "")
            if rule.get("required") and not value:
                raise Queue("REQUIRED_FIELD_MISSING",
                            f"required field '{field}' is empty", stage="precheck")
            if "enum" in rule and value not in rule["enum"]:
                raise Queue("ENUM_UNRECOGNISED",
                            f"field '{field}' is {value!r}, not one of {rule['enum']}",
                            stage="precheck")
            if "pattern" in rule and value and not re.match(rule["pattern"], value):
                raise Queue("PATTERN_MISMATCH",
                            f"field '{field}' is {value!r}, which does not match "
                            f"{rule['pattern']}", stage="precheck")

    # -- writes -----------------------------------------------------------
    def compose(self, fields: dict) -> str:
        try:
            return self.d["write"]["template"].format(**fields)
        except KeyError as exc:
            raise Queue("TEMPLATE_FIELD_MISSING",
                        f"note template references {exc}, which the detail pane "
                        f"does not provide", stage="compose") from None

    def write_note(self, note: str) -> None:
        target = sel(self.d, "note")
        self.page.focus(target)
        # .fill() sets the value AND dispatches an `input` event, so a portal whose
        # model is reactive sees the change. Verified against this mock: the field is
        # a real <textarea> (not contenteditable) and `input` does fire.
        self.page.fill(target, note)

    def confirm_note(self, note: str) -> str:
        """Re-read the note field and confirm the intended value actually landed.

        Separate from write_note and called immediately before the commit click, so
        the gap between 'we wrote it' and 'we committed it' is as small as it can be.
        If this does not hold, the case is queued and **the commit button is never
        touched** — an empty note would otherwise be rejected by the portal, and a
        rejection is the one thing this automation must not walk into blind.
        """
        target = sel(self.d, "note")
        seen = self.page.input_value(target)
        if seen != note:
            raise Queue("NOTE_NOT_CONFIRMED",
                        f"the note field holds {seen[:40]!r} after the write, "
                        f"expected {note[:40]!r} — not committing",
                        stage="confirm_note")
        return seen

    def commit_once(self) -> None:
        self.page.click(sel(self.d, "commit"))

    def verify(self, row: int) -> tuple[bool, str]:
        """Re-read the row's status and confirm it flipped.

        This is a first-class step, not a formality. It is the ONLY check that
        catches a portal which accepts the click and does nothing — and since
        dataset B never recorded a failure, that is exactly the case nobody can
        rule out.
        """
        expected = self.d["row_schema"]["status"]["expect_after_commit"]
        deadline = time.time() + self.d["policy"]["verify_timeout_ms"] / 1000
        seen = ""
        while time.time() < deadline:
            seen = self.read_status(row)
            if seen == expected:
                return True, seen
            time.sleep(0.12)
        return False, seen

    def shot(self, case_id: str, tag: str) -> str | None:
        if not self.shots:
            return None
        self.shots.mkdir(parents=True, exist_ok=True)
        path = self.shots / f"{case_id}_{tag}.png"
        try:
            self.page.screenshot(path=str(path))
        except PWError:
            return None
        return rel(path)


# --------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------
def run_case(runner: Runner, job: dict) -> dict:
    """Returns the audit record for one case. Never raises."""
    case_id = job["case_id"]
    row = int(job["row"])
    rec: dict = {
        "case_id": case_id,
        "row": row,
        "human_action": job.get("action", "approve"),
        "reviewed_by": job.get("reviewed_by", "operator"),
        "review_seconds": round(float(job.get("review_seconds") or 0.0), 2),
        "edits": job.get("overrides") or {},
        "read": {},
        "written": None,
        "note_confirmed": None,
        "commit_attempted": False,
        "commit_attempts": 0,
        "verify_confirmed": None,
        "status_before": None,
        "status_after": None,
        "outcome": None,
        "code": None,
        "detail": None,
        "stage": None,
        "screens": {},
        "started_at": time.time(),
    }

    emit("case_start", case_id=case_id, row=row, action=rec["human_action"])

    # A flagged case never reaches the browser at all.
    if rec["human_action"] == "flag":
        rec.update(outcome=QUEUED, code="HUMAN_FLAGGED", stage="review",
                   detail=job.get("flag_reason") or "flagged by the reviewer")
        rec["automation_seconds"] = 0.0
        rec["ended_at"] = time.time()
        emit("case_done", case_id=case_id, outcome=QUEUED, code="HUMAN_FLAGGED",
             detail=rec["detail"])
        return rec

    t0 = time.time()
    try:
        emit("step", case_id=case_id, step="read_row")
        row_cells = runner.read_row(row)
        rec["read"]["row_cells"] = row_cells
        rec["status_before"] = row_cells.get("status")

        emit("step", case_id=case_id, step="open_row",
             detail=f"tr:nth-of-type({row})")
        runner.open_row(row)

        emit("step", case_id=case_id, step="read_detail")
        fields = runner.read_detail()
        rec["read"]["detail"] = dict(fields)

        # The human's corrections replace what the DOM said. This is the point
        # where "the human is in the loop" becomes a fact about the data rather
        # than a claim about the UI: what commits below is the corrected value.
        for k, v in (job.get("overrides") or {}).items():
            if k in fields:
                fields[k] = v
        if job.get("overrides"):
            emit("step", case_id=case_id, step="apply_edits",
                 detail=", ".join(f"{k}→{v!r}" for k, v in job["overrides"].items()))
        rec["read"]["effective"] = dict(fields)

        emit("step", case_id=case_id, step="precheck")
        runner.precheck(case_id, row_cells, fields)

        note = runner.compose(fields)
        rec["written"] = note
        emit("step", case_id=case_id, step="write_note", detail=note)
        runner.write_note(note)

        # Re-read the field before going anywhere near the commit button.
        emit("step", case_id=case_id, step="confirming_note",
             detail="re-reading the note field")
        rec["note_confirmed"] = bool(runner.confirm_note(note))
        rec["screens"]["wrote"] = runner.shot(case_id, "wrote")
        emit("step", case_id=case_id, step="note_confirmed", detail=note,
             screenshot=rec["screens"]["wrote"])

        emit("step", case_id=case_id, step="commit",
             detail=f"single click on {sel(runner.d, 'commit')}, no retry")
        rec["commit_attempted"] = True
        rec["commit_attempts"] = 1
        runner.commit_once()

        emit("step", case_id=case_id, step="verifying",
             detail="re-reading the row's ステータス")
        ok, seen = runner.verify(row)
        rec["status_after"] = seen
        rec["verify_confirmed"] = ok
        rec["screens"]["verified"] = runner.shot(case_id, "verified")

        if not ok:
            expected = runner.d["row_schema"]["status"]["expect_after_commit"]
            rec.update(outcome=QUEUED, code="VERIFY_FAILED", stage="verify",
                       detail=(f"commit was clicked once; the row is still {seen!r}, "
                               f"expected {expected!r}. Not retried."))
            emit("case_done", case_id=case_id, outcome=QUEUED, code="VERIFY_FAILED",
                 detail=rec["detail"], status_before=rec["status_before"],
                 status_after=seen, screenshot=rec["screens"]["verified"])
        else:
            rec.update(outcome=AUTOMATED, code="VERIFIED", stage="verify",
                       detail=f"{rec['status_before']} → {seen} confirmed by read-back")
            emit("case_done", case_id=case_id, outcome=AUTOMATED, code="VERIFIED",
                 detail=rec["detail"], status_before=rec["status_before"],
                 status_after=seen, screenshot=rec["screens"]["verified"])

    except Queue as q:
        rec.update(outcome=QUEUED, code=q.code, detail=q.detail, stage=q.stage)
        rec["screens"]["queued"] = runner.shot(case_id, "queued")
        emit("case_done", case_id=case_id, outcome=QUEUED, code=q.code,
             detail=q.detail, stage=q.stage, screenshot=rec["screens"]["queued"])

    except PWError as exc:
        # Anything the definition did not anticipate is, by construction, a
        # human's problem and not the automation's to improvise around.
        rec.update(outcome=QUEUED, code="UNEXPECTED_BROWSER_ERROR",
                   detail=str(exc).splitlines()[0][:300], stage="unknown")
        emit("case_done", case_id=case_id, outcome=QUEUED,
             code="UNEXPECTED_BROWSER_ERROR", detail=rec["detail"])

    rec["automation_seconds"] = round(time.time() - t0, 3)
    rec["ended_at"] = time.time()
    return rec


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--definition", required=True)
    ap.add_argument("--jobs", required=True,
                    help="JSON list of {case_id, row, action, overrides, review_seconds}")
    ap.add_argument("--audit", default=str(REPO / "build" / "audit_log.jsonl"))
    ap.add_argument("--screenshots", default=str(REPO / "build" / "screens"))
    ap.add_argument("--no-screenshots", action="store_true")
    ap.add_argument("--headed", action="store_true",
                    help="show the browser (needs a display; headless otherwise)")
    ap.add_argument("--slow-mo", type=int, default=0,
                    help="ms between actions — use ~400 with --headed for a live demo")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--base-url", default=None,
                    help="portal to drive, overriding the definition's target.base_url; "
                         "the caller passes the portal it is itself reading")
    ap.add_argument("--expect-server", default=None,
                    help="server_id of the portal the caller believes it is driving; "
                         "the run is abandoned if the browser lands on a different one")
    args = ap.parse_args()

    defn = load_definition(pathlib.Path(args.definition))
    jobs = json.loads(pathlib.Path(args.jobs).read_text(encoding="utf-8"))
    run_id = args.run_id or f"run_{time.strftime('%Y%m%d-%H%M%S')}_{uuid.uuid4().hex[:6]}"
    shots = None if args.no_screenshots else pathlib.Path(args.screenshots)

    audit_path = pathlib.Path(args.audit)
    audit_path.parent.mkdir(parents=True, exist_ok=True)

    # The caller may pin the portal explicitly. Without this the engine drove
    # whatever target.base_url said while the review UI could be reading a different
    # portal entirely — the same "two portals, one demo" class of bug as §5c.
    base = (args.base_url or defn["target"]["base_url"]).rstrip("/")
    url = base + defn["target"]["route"]
    emit("run_start", run_id=run_id, definition=defn["definition_id"],
         definition_version=defn["definition_version"], url=url, n=len(jobs),
         llm_in_runtime=False)

    def abandon(reason: str) -> None:
        """The run could not start. Write one audit record per job rather than
        none, so the caller can never lose a case to a silent startup failure —
        which is exactly how an earlier build lost 18 of them (see build notes §5.1).
        """
        with audit_path.open("a", encoding="utf-8") as fh:
            for job in jobs:
                rec = {
                    "case_id": job["case_id"], "row": job.get("row"),
                    "human_action": job.get("action", "approve"),
                    "reviewed_by": job.get("reviewed_by", "operator"),
                    "review_seconds": round(float(job.get("review_seconds") or 0.0), 2),
                    "edits": job.get("overrides") or {}, "read": {}, "written": None,
                    "note_confirmed": None, "commit_attempted": False,
                    "commit_attempts": 0, "verify_confirmed": None,
                    "status_before": None, "status_after": None,
                    "outcome": QUEUED, "code": "ENGINE_STARTUP_FAILED",
                    "detail": reason, "stage": "startup", "screens": {},
                    "automation_seconds": 0.0,
                    "started_at": time.time(), "ended_at": time.time(),
                    "run_id": run_id, "definition_id": defn["definition_id"],
                    "definition_version": defn["definition_version"],
                    "llm_in_runtime": False,
                    "portal_epoch": None, "portal_server_id": None,
                }
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        emit("run_end", run_id=run_id, processed=len(jobs), automated=0,
             queued=len(jobs), automation_seconds=0.0,
             review_seconds=0.0, audit=rel(audit_path), startup_failed=reason)

    records: list[dict] = []
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=not args.headed, slow_mo=args.slow_mo)
        except PWError as exc:
            abandon(f"the browser would not launch: {str(exc).splitlines()[0][:200]}")
            return
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        try:
            page.goto(url)
        # Wait for the worklist to be POPULATED, not merely present. `#rt-table`
        # ships in the static HTML with an empty <tbody> and is filled by the
        # page's own fetch, so waiting on the table alone returns with zero rows
        # and every case then fails read_row with ROW_NOT_FOUND. Measured: with
        # /api/state delayed, `wait_for_selector('#rt-table')` returns at rows=0.
            ready = defn["selectors"].get("ready") or sel(defn, "row", n=1)
            page.wait_for_selector(
                ready, timeout=defn["policy"].get("ready_timeout_ms", 15000))
        except PWError as exc:
            browser.close()
            abandon(f"the worklist at {url} never became ready: "
                    f"{str(exc).splitlines()[0][:200]}")
            return

        # Which portal process did the BROWSER actually reach? The page stamps its
        # server's identity onto <body>, so this is read from the rendered DOM rather
        # than from a separate API call the browser might not have shared. Two portals
        # were once bound to one address with different state (build notes §5c); this
        # is how a run proves which one it drove.
        portal_epoch = page.evaluate("() => document.body.dataset.portalEpoch || ''")
        portal_server_id = page.evaluate("() => document.body.dataset.portalServer || ''")
        emit("portal_identity", url=url, portal_epoch=portal_epoch,
             portal_server_id=portal_server_id, expected=args.expect_server)

        if args.expect_server and portal_server_id != args.expect_server:
            browser.close()
            abandon(f"the browser reached portal {portal_server_id!r} at {url}, but the "
                    f"caller is reviewing {args.expect_server!r}. Refusing to write to a "
                    f"portal the reviewer is not looking at.")
            return

        runner = Runner(page, defn, shots)

        with audit_path.open("a", encoding="utf-8") as fh:
            for job in jobs:
                rec = run_case(runner, job)
                rec["run_id"] = run_id
                rec["definition_id"] = defn["definition_id"]
                rec["definition_version"] = defn["definition_version"]
                rec["llm_in_runtime"] = False
                rec["portal_epoch"] = portal_epoch
                rec["portal_server_id"] = portal_server_id
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fh.flush()
                records.append(rec)

        browser.close()

    automated = sum(1 for r in records if r["outcome"] == AUTOMATED)
    queued = sum(1 for r in records if r["outcome"] == QUEUED)
    auto_s = sum(r["automation_seconds"] for r in records)
    review_s = sum(r["review_seconds"] for r in records)

    emit("run_end", run_id=run_id, processed=len(records), automated=automated,
         queued=queued, automation_seconds=round(auto_s, 2),
         review_seconds=round(review_s, 2), audit=rel(audit_path))


if __name__ == "__main__":
    main()
