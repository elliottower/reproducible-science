"""Seal a run, record what it produced, and verify the chain.

results init              start tracking results here
results seal <file>...    hash inputs before a run (prereg, script, data)
results access <note>     record a data-access event (what you looked at, when)
results run <file>...     record outputs after a run completes
results claim <text>      bind a manuscript claim to a run's output
results coverage <paper>  how many of a manuscript's numbers are bound to a run
results verify            check the ledger chain and every hash it names

This module parses arguments. Each handler unpacks the namespace argparse built and calls into
`results.record` or `results.audit`, where the command's logic and its refusals live.
"""

from __future__ import annotations

import argparse
import sys

from provenance_core import hint

from results import audit, ledger, record

# Nothing below uses these. Each was reachable as `results.cli.<name>` while the logic lived in
# this module, so they are re-exported and an import written against that path still resolves.
# The redundant alias is the form ruff and a type checker read as a deliberate re-export.
from results.paths import RESULTS_DIR as RESULTS_DIR
from results.paths import find_root as find_root
from results.paths import ledger_path as ledger_path
from results.paths import record_path as record_path
from results.paths import require_root as require_root
from results.record import ACCESS_LEVELS
from results.timeline import first_outcomes_seen as first_outcomes_seen
from results.timeline import first_run_timestamp as first_run_timestamp
from results.timeline import freeze_timestamp as freeze_timestamp
from results.timeline import precedes as precedes


def cmd_init(a) -> int:
    return record.init()


def cmd_seal(a) -> int:
    return record.seal(a.files, a.role)


def cmd_access(a) -> int:
    return record.access(a.note, a.level)


def cmd_run(a) -> int:
    return record.run(a.files, a.run_id, a.note, getattr(a, "anyway", False))


def cmd_claim(a) -> int:
    return record.claim(
        a.text,
        a.run_id,
        a.confirmatory,
        a.anyway,
        getattr(a, "frozen_at", None),
        a.location,
    )


def cmd_coverage(a) -> int:
    return audit.coverage(a.manuscript, a.limit, a.strict)


def cmd_reanchor(a) -> int:
    return audit.reanchor()


def cmd_verify(a) -> int:
    return audit.verify(a.files)


def main(argv: list[str] | None = None) -> int:
    code = _main(argv)
    # After the work, never before it, and never instead of it: the note is about how this
    # project could be run, and a command that has not yet said what it found should not be
    # interrupted to say that.
    hint.note("results")
    return code


def _main(argv: list[str] | None = None) -> int:
    """The command. `argv` defaults to the process arguments.

    Taking it explicitly is what lets a caller in the same process run this without touching
    `sys.argv`: `repro results` forwards its remaining arguments here, and a test can
    drive the command the way a user does. `citations` and `repro` already had this shape.
    """
    ap = argparse.ArgumentParser(prog="results", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("init", help="start tracking results here")

    s = sub.add_parser("seal", help="hash inputs before a run")
    s.add_argument("files", nargs="+")
    s.add_argument(
        "--role", default="input", help="what these files are: input, prereg, script, data"
    )
    s.set_defaults(fn=cmd_seal)

    ac = sub.add_parser("access", help="record a data-access event")
    ac.add_argument("note", help="what was accessed and why")
    ac.add_argument("--level", default="metadata only", help=f"one of: {', '.join(ACCESS_LEVELS)}")
    ac.set_defaults(fn=cmd_access)

    r = sub.add_parser("run", help="record outputs after a run")
    r.add_argument("files", nargs="+")
    r.add_argument("--run-id", required=True, help="a name for this run")
    r.add_argument("--note", help="what this run computed")
    r.add_argument(
        "--anyway",
        action="store_true",
        help="record a second run under an id that already exists; a claim naming that id "
        "is then ordered by the later run",
    )
    r.set_defaults(fn=cmd_run)

    cl = sub.add_parser("claim", help="bind a manuscript claim to a run")
    cl.add_argument("text", help="the claim, as it appears in the manuscript")
    cl.add_argument("--run-id", required=True, help="which run backs this claim")
    cl.add_argument(
        "--confirmatory", action="store_true", help="mark as confirmatory (default: exploratory)"
    )
    cl.add_argument(
        "--anyway",
        action="store_true",
        help="record a confirmatory claim whose run postdates seeing the "
        "outcomes; the ledger and verify both report the ordering",
    )
    cl.add_argument(
        "--frozen-at",
        help="a commit containing the frozen plan this claim rests on; if it "
        "predates the exposure, the claim is confirmatory with the "
        "exposure logged rather than retrospective",
    )
    cl.add_argument("--location", help="where in the manuscript: Table 2, Section 4.1, etc.")
    cl.set_defaults(fn=cmd_claim)

    v = sub.add_parser("verify", help="check the ledger and every hash it names")
    v.add_argument(
        "--files",
        action="store_true",
        help="also check that sealed/output files still match their hashes",
    )
    v.set_defaults(fn=cmd_verify)

    cv = sub.add_parser("coverage", help="how many of a manuscript's numbers are bound to a run")
    cv.add_argument("manuscript", help="the manuscript source: .tex, .md, .qmd, .rst")
    cv.add_argument(
        "--limit", type=int, default=25, help="how many unbound numbers to list (default: 25)"
    )
    cv.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero when anything is unbound, for a pre-submission check",
    )
    cv.set_defaults(fn=cmd_coverage)

    ra = sub.add_parser("reanchor", help="record the ledger's current length as authoritative")
    ra.set_defaults(fn=cmd_reanchor)

    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 0
    try:
        if a.cmd == "init":
            return cmd_init(a)
        return a.fn(a)
    except ledger.ResultsError as e:
        # The process boundary. Library code raises; only here does a failure become a code.
        print(str(e))
        return 2


if __name__ == "__main__":
    sys.exit(main())
