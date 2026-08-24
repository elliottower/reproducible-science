"""The `citations` command.

    citations init              make a library here
    citations verify            do my quotations resolve in the sources I pinned?
    citations audit             does the metadata match the record the identifier resolves to?
    citations resolve           backfill missing identifiers
    citations build             rebuild records from the papers' bibliographies
    citations lint              BibTeX correctness, via papis doctor
    citations link              point pdfs/ at wherever the papers keep the artifacts
    citations bib               emit a .bib for the works a paper cites
"""
from __future__ import annotations

import argparse
import collections
import importlib
import pathlib

from citations import paths, verify as V
from citations.exceptions import CitationsError, ClaimFileError
from citations.models import ClaimFile, load_claim_file, load_record

RESULTS = ["found", "not found", "unchecked"]
WARNINGS = {"truncated": "stops mid-word or mid-number — the source continues it",
            "short": "the source may qualify this in the next clause",
            "normalized": "matched after ignoring punctuation and spacing",
            "page": "found, but not on the page recorded"}

DELEGATED = {"init": "init", "audit": "audit", "resolve": "resolve",
             "build": "build", "lint": "lint", "link": "link_pdfs"}


def _records() -> list:
    """Every record in the governing library, validated."""
    return [load_record(p) for p in sorted(paths.records().glob("*.yaml"))]


def _claim_files(root: pathlib.Path) -> list[ClaimFile]:
    """Every claims file under `root`, validated.

    A file that cannot be parsed is reported and skipped rather than ending the run: one
    malformed file should not hide the state of the other three hundred.
    """
    out: list[ClaimFile] = []
    for p in sorted(root.glob("*.yaml")):
        try:
            out.append(load_claim_file(p))
        except ClaimFileError as e:
            print(f"  skipped  {p.name}: {e.detail.splitlines()[0]}")
    return out


def cmd_verify(a) -> int:
    rep = V.Report()
    counts: collections.Counter = collections.Counter()

    if a.claims:
        root = pathlib.Path(a.claims).expanduser().resolve()
        for cf in _claim_files(root):
            artifact = cf.artifact()
            pin = V.check_pin(artifact, cf.source.sha256)
            if pin.state == "broken":
                rep.broken_pins.append((cf.name, pin))
            for cid, claim in cf.claims.items():
                for q in claim.quotes:
                    if not q.text:
                        continue
                    rep.checked += 1
                    r = V.check_one(q.text, artifact, q.page)
                    counts[r.state] += 1
                    if r.state != "found" or r.warnings:
                        rep.problems.append((f"{cf.name}:{cid}", q.text[:58], r))
        rep.counts = dict(counts)
        return _report(rep, counts, a, f"claims  {root}")

    lib, origin = paths.find_with_origin()
    source = f"library {lib}" + (
        "  (user-level: no .citations/ in this directory or above it)"
        if origin == "user" else "")
    for rec in _records():
        if a.only and a.only not in rec.cited_by:
            continue
        artifact = (paths.home() / rec.local) if rec.local else None
        if rec.quotes:
            pin = V.check_pin(artifact, rec.sha256)
            if pin.state == "broken":
                rep.broken_pins.append((rec.slug, pin))
        for q in rec.quotes:
            if not q.text:
                continue
            rep.checked += 1
            r = V.check_one(q.text, artifact, q.page)
            counts[r.state] += 1
            if r.state != "found" or r.warnings:
                rep.problems.append((rec.slug, q.text[:58], r))
    rep.counts = dict(counts)
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
            print(f"  {s:<12}{n:>7}")
            continue
        if not n:
            continue
        why = ""
        if s == "unchecked":
            reasons = collections.Counter(r.detail for _, _, r in rep.problems
                                          if r.state == "unchecked")
            why = ("   " + " · ".join(f"{c:,} {d}" for d, c in reasons.most_common())
                   if len(reasons) > 1 else f"   {reasons.most_common(1)[0][0]}")
        print(f"  {s:<12}{n:>7,}{why}")

    warns = collections.Counter(w for _, _, r in rep.problems for w in r.warnings)
    if warns:
        print("\nwarnings")
        for w, n in warns.most_common():
            print(f"  {n:>7,}  {w} — {WARNINGS.get(w, '')}")

    # A broken pin is reported before the quotation failures. Every result computed against
    # that source describes a document the record does not describe, so it changes how the
    # numbers above should be read.
    if rep.broken_pins:
        print(f"\n{len(rep.broken_pins)} source{'s' if len(rep.broken_pins) > 1 else ''} "
              f"changed since being pinned")
        for name, pin in rep.broken_pins[:10]:
            print(f"  {name[:38]:<40}pinned {pin.expected[:12]}  on disk {pin.actual[:12]}")
        if len(rep.broken_pins) > 10:
            print(f"  ... and {len(rep.broken_pins) - 10} more")

    bad = [(s, q, r) for s, q, r in rep.problems if r.state == "not found"]
    if bad and not a.quiet:
        print()
        for slug, text, r in bad[:20]:
            print(f"  not found  {slug[:30]:<32}{text[:44]}")
        if len(bad) > 20:
            print(f"             ... and {len(bad) - 20} more")

    print()
    if bad:
        print(f"{len(bad)} not found. read the source before concluding anything.")
    elif rep.broken_pins:
        print("every quote resolved, but against a source that is not the one pinned.")
    elif counts.get("unchecked"):
        print(f"nothing failed. {counts['unchecked']} unchecked — no measurement was made "
              f"for those.")
    else:
        print("all found.")
    return 0 if rep.ok or not a.strict else 1


def _delegate(module: str, argv: list[str]) -> int:
    """Hand the remaining arguments to a subcommand's own parser.

    `argv` is passed, never assigned to `sys.argv`: a function whose behavior depends on a
    global cannot be called twice, tested without monkeypatching, or run from anything that is
    not a terminal.
    """
    return importlib.import_module(f"citations.{module}").main(argv)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="citations", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd")

    v = sub.add_parser("verify", help="do my quotations resolve in their pinned sources?")
    v.add_argument("--claims", help="a paper's claims/ directory, where quotations live")
    v.add_argument("--only", help="restrict to records cited by this paper")
    v.add_argument("--strict", action="store_true", help="exit 1 on any failure, for CI")
    v.add_argument("--verbose", action="store_true", help="also list loose matches")
    v.add_argument("--quiet", action="store_true")
    v.set_defaults(fn=cmd_verify)

    for name, helptext in [("init", "make a library here"),
                           ("audit", "does the stored metadata match the registry record?"),
                           ("resolve", "backfill missing identifiers"),
                           ("build", "rebuild records from the papers' bibliographies"),
                           ("lint", "BibTeX correctness, via papis doctor"),
                           ("link", "point pdfs/ at the papers' artifacts")]:
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
