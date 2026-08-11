"""The `citations` command.

    citations init              make a library here
    citations verify            do my quotations resolve in the sources I pinned?
    citations resolve           backfill missing identifiers
    citations build             rebuild records from the papers' bibliographies
    citations lint              BibTeX correctness, via papis doctor
    citations link              point pdfs/ at wherever the papers keep the artifacts
    citations bib               emit a .bib for the works a paper cites
"""
from __future__ import annotations

import argparse
import collections
import pathlib
import sys

import yaml

from citations import paths, verify as V

RESULTS = ["found", "not found", "unchecked"]
WARNINGS = {"short": "the source may qualify this in the next clause",
            "normalized": "matched after ignoring punctuation and spacing",
            "page": "found, but not on the page recorded"}


def _records() -> list[dict]:
    d = paths.records()
    return [yaml.safe_load(p.read_text()) or {} for p in sorted(d.glob("*.yaml"))]


def _quotes_from_claims(root: pathlib.Path):
    """A paper's claims/ holds the extraction: source, sha256 and the quotations taken from it."""
    for p in sorted(root.glob("*.yaml")):
        r = yaml.safe_load(p.read_text()) or {}
        src = r.get("source") or {}
        art = src.get("local")
        # Papers name this block either way. Reading only one spelling makes the command find
        # nothing and report it, which is indistinguishable from a paper that has no quotes yet.
        for cid, ev in (r.get("evidence") or r.get("claims") or {}).items():
            for q in (ev.get("quotes") or []):
                yield p.stem, cid, (q.get("exact") or q.get("text") or ""), art, q.get("page")


def cmd_verify(a) -> int:
    rep = V.Report()
    counts: collections.Counter = collections.Counter()

    if a.claims:
        root = pathlib.Path(a.claims).expanduser().resolve()
        base = root.parent
        for claim, cid, text, art, page in _quotes_from_claims(root):
            if not text:
                continue
            rep.checked += 1
            r = V.check_one(text, (base / art) if art else None, page)
            counts[r.state] += 1
            if r.state != "found" or r.warnings:
                rep.problems.append((f"{claim}:{cid}", text[:58], r))
        rep.counts = dict(counts)
        return _report(rep, counts, a)

    for rec in _records():
        if a.only and a.only not in (rec.get("cited_by") or {}):
            continue
        art = rec.get("local")
        artifact = (paths.home() / art) if art else None
        for q in rec.get("quotes") or []:
            text = q.get("text") or q.get("exact") or ""
            if not text:
                continue
            rep.checked += 1
            r = V.check_one(text, artifact, q.get("page"))
            counts[r.state] += 1
            if r.state != "found" or r.warnings:
                rep.problems.append((rec["slug"], text[:58], r))
    rep.counts = dict(counts)
    return _report(rep, counts, a)


def _report(rep, counts, a) -> int:
    if rep.checked == 0:
        print("nothing to check.\n")
        print("quotes live in a paper's claims/ directory. point at one:")
        print("    citations verify --claims <path>")
        return 2

    sources = len({s for s, _, _ in rep.problems}) or "?"
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
    elif counts.get("unchecked"):
        print(f"nothing failed. {counts['unchecked']} unchecked — no measurement was made "
              f"for those.")
    else:
        print("all found.")
    return 0 if rep.ok or not a.strict else 1


def _delegate(module: str, name: str, argv: list[str]) -> int:
    import importlib
    m = importlib.import_module(f"citations.{module}")
    sys.argv = [f"citations {name}"] + argv
    return m.main()


def main() -> int:
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
                           ("resolve", "backfill missing identifiers"),
                           ("build", "rebuild records from the papers' bibliographies"),
                           ("lint", "BibTeX correctness, via papis doctor"),
                           ("link", "point pdfs/ at the papers' artifacts")]:
        p = sub.add_parser(name, help=helptext, add_help=False)
        p.set_defaults(fn=None, delegate={"link": "link_pdfs"}.get(name, name),
                       shown=name)

    args, rest = ap.parse_known_args()
    if not args.cmd:
        ap.print_help()
        return 0
    if getattr(args, "fn", None):
        return args.fn(args)
    return _delegate(args.delegate, args.shown, rest)


if __name__ == "__main__":
    sys.exit(main())
