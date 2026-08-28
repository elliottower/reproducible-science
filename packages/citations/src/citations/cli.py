"""The `citations` command.

citations init              make a library here
citations verify            do my quotations resolve in the sources I pinned?
citations coverage          is every quotation in my manuscript pinned at all?
citations audit             does the metadata match the record the identifier resolves to?
citations resolve           backfill missing identifiers
citations build             rebuild records from the papers' bibliographies
citations lint              BibTeX correctness, and repeated keys in a .bib
citations add               add one entry to a .bib, refusing a key it already has
citations link              point pdfs/ at wherever the papers keep the artifacts
citations bib               emit a .bib for the works a paper cites
citations import-paperclip  turn a Paperclip paper repo into pinned claim files
"""

from __future__ import annotations

import argparse
import collections
import importlib
import pathlib

from provenance_core import hint

from citations import coverage as C
from citations import paths, projects
from citations import verify as V
from citations.exceptions import CitationsError, ClaimFileError
from citations.models import ClaimFile, load_claim_file, load_record

RESULTS = ["found", "not found", "indeterminate", "unchecked"]

#: Width of the outcome column, computed so adding an outcome does not silently ragged the
#: table. `indeterminate` is the longest, and naming an outcome for what it means rather than
#: for what fits is why this is derived instead of written down.
OUTCOME_WIDTH = max(len(r) for r in RESULTS) + 1
WARNINGS = {
    "truncated": "stops mid-word or mid-number — the source continues it",
    "short": "the source may qualify this in the next clause",
    "normalized": "matched after ignoring punctuation and spacing",
    "page": "found, but not on the page recorded",
    "page unchecked": "a page is recorded and the declared extractor cannot be asked for one",
}

DELEGATED = {
    "init": "init",
    "audit": "audit",
    "resolve": "resolve",
    "build": "build",
    "lint": "lint",
    "add": "add",
    "pin": "pin",
    "projects": "projects",
    "link": "link_pdfs",
    "import-paperclip": "import_paperclip",
}


def _records() -> list:
    """Every record in the governing library, validated."""
    return [load_record(p) for p in sorted(paths.records().glob("*.yaml"))]


def _claim_files(root: pathlib.Path, skipped=None) -> list[ClaimFile]:
    """Every claims file under `root`, validated.

    A file that cannot be parsed is reported and skipped rather than ending the run: one
    malformed file should not hide the state of the other three hundred.
    """
    out: list[ClaimFile] = []
    skipped = [] if skipped is None else skipped
    for p in sorted(root.glob("*.yaml")):
        try:
            out.append(load_claim_file(p))
        except ClaimFileError as e:
            reason = e.detail.splitlines()[0]
            print(f"  skipped  {p.name}: {reason}")
            skipped.append((p.name, reason))
    return out


def _record_extractor(rep: V.Report, extractors, r: V.Result) -> None:
    """Note what read this source, why it was not the preferred extractor, and whether more
    than one was asked.

    Kept on the report rather than printed as it happens: a substitution that only ever
    appeared in a log line is one no later run can compare itself against.
    """
    if not r.extractor:
        return
    extractors[r.extractor] += 1
    if len(r.agreement) > 1:
        rep.triangulated += 1
    if r.fallback and r.extractor not in rep.fallback_reasons:
        rep.fallback_reasons[r.extractor] = r.fallback_reason or "pdftotext did not answer"


COVERAGE = ["covered", "uncovered", "unresolvable"]
COVERAGE_WIDTH = max(len(s) for s in COVERAGE) + 1


def cmd_coverage(a) -> int:
    """Every quotation in the manuscript, against what is pinned."""
    manuscript = pathlib.Path(a.manuscript)
    if not manuscript.is_file():
        print(f"no manuscript at {manuscript}")
        return 2
    claims_dir = pathlib.Path(a.claims)
    if not claims_dir.is_dir():
        print(f"no claims directory at {claims_dir}")
        return 2

    quotes = C.quotations(manuscript.read_text(errors="replace"))
    print(f"manuscript  {manuscript}")
    print(f"claims      {claims_dir}")
    print()
    if not quotes:
        # Not a pass. A manuscript with no ``...'' may quote nothing, or may quote with a
        # convention this does not read, and the two are worth telling apart by eye.
        print("no ``...'' quotations found. nothing was checked.")
        return 1 if a.strict else 0

    skipped: list = []
    files = _claim_files(claims_dir, skipped)
    allowed = V.DEFAULT_EXTRACTORS | frozenset(a.allow_extractor or ())

    if a.attribute:
        by_key, missing = C.artifacts_by_key(files, claims_dir, allowed)
        findings = [C.attribute(q, by_key, missing) for q in quotes]
    else:
        pool = C.pinned_spans(files)
        findings = [C.cover(q, pool) for q in quotes]

    counts: collections.Counter = collections.Counter(f.status for f in findings)
    for status in COVERAGE:
        n = counts.get(status, 0)
        if n or status != "unresolvable":
            print(f"  {status:<{COVERAGE_WIDTH}}{n:>7,}")

    problems = [f for f in findings if f.status != "covered"]
    if problems:
        print()
        for f in problems:
            head = "UNCOVERED" if f.status == "uncovered" else "unresolvable"
            print(f"  {head}  {manuscript.name}:{f.quotation.line}")
            print(f"    ``{f.quotation.raw.strip()[:96]}''")
            print(f"    {f.detail}")

    print()
    uncovered = counts.get("uncovered", 0)
    unresolvable = counts.get("unresolvable", 0)
    if uncovered:
        print(f"{uncovered} quotation(s) the manuscript makes and nothing pins.")
        print("pin them, or stop quoting them. an unpinned quotation is not checked by anything.")
    elif unresolvable:
        print(f"nothing uncovered. {unresolvable} could not be decided; see the reasons above.")
    else:
        print(f"every quotation is {'attributed' if a.attribute else 'covered'}.")

    if a.strict:
        return 1 if (uncovered or unresolvable) else 0
    return 1 if uncovered else 0


def cmd_verify(a) -> int:
    rep = V.Report()
    counts: collections.Counter = collections.Counter()
    extractors: collections.Counter = collections.Counter()
    # Consent to run a program comes from whoever invokes the command, never from the file
    # being checked. See the trust model in `verify.py`.
    allowed = V.DEFAULT_EXTRACTORS | frozenset(a.allow_extractor or ())

    if a.claims:
        root = pathlib.Path(a.claims).expanduser().resolve()
        for cf in _claim_files(root, skipped=rep.skipped):
            artifact = cf.artifact()
            pin = V.check_pin(artifact, cf.source.sha256)
            if pin.state == "broken":
                rep.broken_pins.append((cf.name, pin))
            elif pin.state == "unpinned":
                rep.unpinned.append(cf.name)
            for cid, claim in cf.claims.items():
                if claim.interpretation is not None:
                    rep.interpretations += 1
                    whose = claim.interpretation.whose
                    if whose not in {"ours", cf.source.citation}:
                        rep.foreign_readings += 1
                    if claim.interpretation.status == "contested":
                        rep.contested_readings += 1
                for q in claim.quotes:
                    if not q.text:
                        continue
                    rep.checked += 1
                    r = V.check_one(
                        q.text,
                        artifact,
                        q.page,
                        cf.source.extract_cmd,
                        allowed,
                        a.triangulate,
                        q.prefix,
                        q.suffix,
                    )
                    counts[r.state] += 1
                    _record_extractor(rep, extractors, r)
                    if r.state != "found" or r.warnings:
                        rep.problems.append((f"{cf.name}:{cid}", q.text[:58], r))
        rep.counts = dict(counts)
        rep.extractors = dict(extractors)
        return _report(rep, counts, a, f"claims  {root}")

    lib, origin = paths.find_with_origin()
    source = f"library {lib}" + (
        "  (user-level: no .citations/ in this directory or above it)" if origin == "user" else ""
    )
    for rec in _records():
        if a.only and a.only not in rec.cited_by:
            continue
        artifact = (paths.home() / rec.local) if rec.local else None
        if rec.quotes:
            pin = V.check_pin(artifact, rec.sha256)
            if pin.state == "broken":
                rep.broken_pins.append((rec.slug, pin))
            elif pin.state == "unpinned":
                rep.unpinned.append(rec.slug)
        for q in rec.quotes:
            if not q.text:
                continue
            rep.checked += 1
            r = V.check_one(
                q.text, artifact, q.page, None, allowed, a.triangulate, q.prefix, q.suffix
            )
            counts[r.state] += 1
            _record_extractor(rep, extractors, r)
            if r.state != "found" or r.warnings:
                rep.problems.append((rec.slug, q.text[:58], r))
    rep.counts = dict(counts)
    rep.extractors = dict(extractors)
    return _report(rep, counts, a, source)


def _report(rep: V.Report, counts, a, source: str = "") -> int:
    # What was checked, before how it went. A clean run against the wrong library reads exactly
    # like a clean run against the right one, and the path is the only thing that separates them.
    if source:
        print(f"{source}\n")
    if rep.checked == 0:
        print("nothing to check.\n")
        print("quotes live in a paper's claims/ directory. point at one:")
        print("    citations verify --claims <path>")
        return 2

    print(f"{rep.checked:,} quotes\n")
    for s in RESULTS:
        n = counts.get(s, 0)
        if not n and s == "not found":
            print(f"  {s:<{OUTCOME_WIDTH}}{n:>7}")
            continue
        if not n:
            continue
        why = ""
        if s in ("unchecked", "indeterminate"):
            # Untruncated: the reason is the only thing that says what to fix, and the one
            # that matters most -- "which this run does not allow" -- is at the end of it.
            reasons = collections.Counter(r.detail for _, _, r in rep.problems if r.state == s)
            why = (
                "   " + " · ".join(f"{c:,} {d}" for d, c in reasons.most_common())
                if len(reasons) > 1
                else f"   {reasons.most_common(1)[0][0]}"
            )
        print(f"  {s:<{OUTCOME_WIDTH}}{n:>7,}{why}")

    # Which extractor a verdict rests on, before the verdicts. A `found` taken through a
    # declared renderer and one taken through `pdftotext` are different records, and a report
    # that does not separate them cannot be compared with a later run.
    if rep.extractors:
        print("\nread by")
        for name, n in sorted(rep.extractors.items(), key=lambda kv: (-kv[1], kv[0])):
            why = rep.fallback_reasons.get(name, "")
            print(f"  {n:>7,}  {name}" + (f"   fallback: {why[:50]}" if why else ""))
    if a.triangulate:
        # What was triangulated, not what was asked for. A source that declares a command has
        # one extractor and a machine may have one reader, and reporting the request as the
        # result would claim an agreement nothing measured.
        consulted = V.available_extractors()
        print(
            f"\ntriangulated  {rep.triangulated:,} of {rep.checked:,} over {', '.join(consulted)}"
            if rep.triangulated
            else "\ntriangulation established nothing: every source was read by one extractor."
        )

    # The second axis. Quotations are measured; characterizations are not, and a report that
    # printed only the first would let "all found" read as an endorsement of statements
    # nothing examined.
    if rep.interpretations:
        print(
            f"\nreadings  {rep.interpretations:,} — unchecked; this package does not measure them"
        )
        if rep.foreign_readings:
            print(f"  {rep.foreign_readings:>7,}  attributed to a party other than the source")
        if rep.contested_readings:
            print(f"  {rep.contested_readings:>7,}  contested")

    # A record that is not committed exists on one machine, and a verdict resting on it cannot
    # be appealed to later. Counted and reported, never blocking: a library mid-edit is the
    # ordinary state of working in one.
    try:
        pending = projects.uncommitted(paths.home())
    except CitationsError:
        pending = 0
    if pending:
        print(
            f"\n{pending} record(s) in the library are not committed. A pin is evidence once it "
            f"is in history."
        )

    warns = collections.Counter(w for _, _, r in rep.problems for w in r.warnings)
    if warns:
        print("\nwarnings")
        for w, n in warns.most_common():
            print(f"  {n:>7,}  {w} — {WARNINGS.get(w, '')}")

    # A broken pin is reported before the quotation failures. Every result computed against
    # that source describes a document the record does not describe, so it changes how the
    # numbers above should be read.
    if rep.broken_pins:
        print(
            f"\n{len(rep.broken_pins)} source{'s' if len(rep.broken_pins) > 1 else ''} "
            f"changed since being pinned"
        )
        for name, pin in rep.broken_pins[:10]:
            print(f"  {name[:38]:<40}pinned {pin.expected[:12]}  on disk {pin.actual[:12]}")
        if len(rep.broken_pins) > 10:
            print(f"  ... and {len(rep.broken_pins) - 10} more")

    bad = [(s, q, r) for s, q, r in rep.problems if r.state == "not found"]
    if bad and not a.quiet:
        print()
        for slug, text, r in bad[:20]:
            print(f"  not found  {slug[:30]:<32}{text[:44]}")
            # The detail carries where the passage stopped matching and what the source reads
            # there, which is the only part that says what to do. Printing the row without it
            # leaves a reader with an accusation and no way to act on it.
            if r.detail:
                for line in r.detail.splitlines():
                    print(f"             {line.strip()}" if line.strip() else "")
        if len(bad) > 20:
            print(f"             ... and {len(bad) - 20} more")

    print()
    if bad:
        print(f"{len(bad)} not found. read the source before concluding anything.")
    elif rep.broken_pins:
        print("every quote resolved, but against a source that is not the one pinned.")
    elif counts.get("indeterminate"):
        print(
            f"nothing failed. {counts['indeterminate']} indeterminate — the extractors here "
            "disagree about those passages, which is not the same as their being absent."
        )
    elif counts.get("unchecked"):
        print(
            f"nothing failed. {counts['unchecked']} unchecked — no measurement was made for those."
        )
    else:
        print("all found.")
    if a.strict and not rep.strict_ok:
        if rep.unresolved:
            print(f"\n{rep.unresolved} quotation(s) could not be checked at all.")
        if rep.unpinned:
            print(f"{len(rep.unpinned)} source(s) carry no digest: {', '.join(rep.unpinned[:3])}")
        if rep.skipped:
            print(f"{len(rep.skipped)} claims file(s) did not parse and were never examined.")
        print("--strict fails on these: nothing was established about them either way.")
    return 0 if (rep.strict_ok if a.strict else rep.ok) else 1


def _delegate(module: str, argv: list[str]) -> int:
    """Hand the remaining arguments to a subcommand's own parser.

    `argv` is passed, never assigned to `sys.argv`: a function whose behavior depends on a
    global cannot be called twice, tested without monkeypatching, or run from anything that is
    not a terminal.
    """
    return importlib.import_module(f"citations.{module}").main(argv)


def main(argv: list[str] | None = None) -> int:
    code = _main(argv)
    # After the work, never before it, and never instead of it: the note is about how this
    # project could be run, and a command that has not yet said what it found should not be
    # interrupted to say that.
    hint.note("citations")
    return code


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="citations", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd")

    v = sub.add_parser("verify", help="do my quotations resolve in their pinned sources?")
    v.add_argument("--claims", help="a paper's claims/ directory, where quotations live")
    v.add_argument("--only", help="restrict to records cited by this paper")
    v.add_argument("--strict", action="store_true", help="exit 1 on any failure, for CI")
    v.add_argument(
        "--allow-extractor",
        action="append",
        metavar="NAME",
        help="let a claims file's extract_cmd run this program, named exactly as it writes it "
        f"(allowed unasked: {', '.join(sorted(V.DEFAULT_EXTRACTORS))})",
    )
    v.add_argument(
        "--triangulate",
        action="store_true",
        help="ask every installed reader; report disagreement as indeterminate",
    )
    c = sub.add_parser("coverage", help="is every quotation in my manuscript pinned at all?")
    c.add_argument("manuscript", help="the .tex the paper is written in")
    c.add_argument("--claims", default="claims", help="where the claim files live")
    c.add_argument(
        "--attribute",
        action="store_true",
        help="also check each quotation against the artifact of a source cited near it",
    )
    c.add_argument(
        "--allow-extractor",
        action="append",
        metavar="PROGRAM",
        help="let a claims file's extract_cmd run this program, for --attribute",
    )
    c.add_argument(
        "--strict", action="store_true", help="also fail on a quotation that could not be decided"
    )
    c.set_defaults(fn=cmd_coverage)

    v.add_argument("--verbose", action="store_true", help="also list loose matches")
    v.add_argument("--quiet", action="store_true")
    v.set_defaults(fn=cmd_verify)

    for name, helptext in [
        ("init", "make a library here"),
        ("audit", "does the stored metadata match the registry record?"),
        ("resolve", "backfill missing identifiers"),
        ("build", "rebuild records from the papers' bibliographies"),
        ("lint", "BibTeX correctness, and repeated keys in a .bib"),
        ("add", "add one entry to a .bib, refusing a key it already has"),
        ("pin", "write a quotation into a claims file, refusing one that does not resolve"),
        ("projects", "which projects this library refers to, and which names are dead"),
        ("link", "point pdfs/ at the papers' artifacts"),
        ("import-paperclip", "turn a Paperclip paper repo into pinned claim files"),
    ]:
        p = sub.add_parser(name, help=helptext, add_help=False)
        p.set_defaults(fn=None, delegate=DELEGATED[name])

    args, rest = ap.parse_known_args(argv)
    if not args.cmd:
        ap.print_help()
        return 0
    try:
        if getattr(args, "fn", None):
            return args.fn(args)
        return _delegate(args.delegate, rest)
    except CitationsError as e:
        print(str(e))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
