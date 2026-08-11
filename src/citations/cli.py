"""The `citations` command.

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

STATE_ORDER = ["missing", "page-off", "too-short", "no-source", "loose", "ok"]
SYMBOL = {"ok": "ok", "loose": "loose", "no-source": "NO SOURCE",
          "page-off": "PAGE OFF", "missing": "MISSING", "too-short": "TOO SHORT"}


def _records() -> list[dict]:
    d = paths.records()
    if not d.is_dir():
        print(f"no library here. Looked in {paths.home()}\n"
              f"Set CITATIONS_HOME, or run from a directory containing records/.",
              file=sys.stderr)
        raise SystemExit(2)
    return [yaml.safe_load(p.read_text()) or {} for p in sorted(d.glob("*.yaml"))]


def _quotes_from_claims(root: pathlib.Path):
    """A paper's claims/ holds the extraction: source, sha256 and the quotations taken from it."""
    for p in sorted(root.glob("*.yaml")):
        r = yaml.safe_load(p.read_text()) or {}
        src = r.get("source") or {}
        art = src.get("local")
        for cid, ev in (r.get("evidence") or {}).items():
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
            if r.state != "ok":
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
            if r.state != "ok":
                rep.problems.append((rec["slug"], text[:58], r))
    rep.counts = dict(counts)
    return _report(rep, counts, a)


def _report(rep, counts, a) -> int:
    if rep.checked == 0:
        print("  0 quotations checked.\n")
        print("  Refusing to report success: a check that examines nothing passes trivially.")
        print("  Quotations live in a paper's claims/ directory, not in records/.")
        print("  Point at one with:  citations verify --claims <path/to/claims>")
        return 2

    print(f"  {rep.checked} quotations checked\n")
    for s in STATE_ORDER:
        if counts.get(s):
            print(f"    {SYMBOL[s]:<10}{counts[s]:>5}")
    if rep.problems and not a.quiet:
        print()
        for slug, text, r in rep.problems[:40]:
            if r.state in ("ok", "loose") and not a.verbose:
                continue
            print(f"  {SYMBOL[r.state]:<10}{slug[:34]:<36}{text[:44]}")
            print(f"             {r.detail}")
    print()
    if rep.ok:
        print("  no quotation failed. Unreachable sources are reported, not failed.")
    else:
        n = sum(counts.get(s, 0) for s in ("missing", "page-off"))
        print(f"  {n} need looking at. A broken extraction produces the same signal as an "
              f"invented quotation, so read before concluding.")
    return 0 if rep.ok or not a.strict else 1


def _delegate(module: str, argv: list[str]) -> int:
    import importlib
    m = importlib.import_module(f"citations.{module}")
    sys.argv = [f"citations {module}"] + argv
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

    for name, helptext in [("resolve", "backfill missing identifiers"),
                           ("build", "rebuild records from the papers' bibliographies"),
                           ("lint", "BibTeX correctness, via papis doctor"),
                           ("link", "point pdfs/ at the papers' artifacts")]:
        p = sub.add_parser(name, help=helptext, add_help=False)
        p.set_defaults(fn=None, delegate={"link": "link_pdfs"}.get(name, name))

    args, rest = ap.parse_known_args()
    if not args.cmd:
        ap.print_help()
        return 0
    if getattr(args, "fn", None):
        return args.fn(args)
    return _delegate(args.delegate, rest)


if __name__ == "__main__":
    sys.exit(main())
