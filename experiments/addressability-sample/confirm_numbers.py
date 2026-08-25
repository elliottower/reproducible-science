"""Stage three: look for each traceable number in the article's pinned artifact.

Stage one enumerates what a paper states (`scan_numbers.py`); this asks whether the artifact
says the same thing, and where. Every confirmation carries the file and line it was found
in, because a verdict without a location is an assertion rather than a check.

Three verdicts, and the third is the one the tool exists to report honestly:

    confirmed   the printed value appears in a readable artifact, at a recorded location
    absent      readable records of a run exist, and none of them holds it
    unchecked   results live only in formats this stage cannot read, so nothing was asked

`unchecked` is never `absent`. A repository holding its results in pickles or plot images is
not one that disagrees with its paper -- it is one that cannot be asked, and collapsing the
two lets a scanner take credit for coverage it never had.

Matching is on the printed string at printed precision. `0.62` does not match a stored
`0.6234`: rounding is a judgment about how a number was produced, and a scanner that guesses
at it converts a mismatch into an agreement.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import tempfile
import xml.etree.ElementTree as ElementTree
import zipfile

from artifact_readers import COMPRESSORS, read_pickle, read_rdata, unwrap

#: Files holding results the work produced. A value confirmed against one of these is
#: confirmed against the record of a run.
DATA = {".csv", ".tsv", ".json", ".txt", ".dat", ".out", ".log", ".yaml", ".yml", ".xml",
        ".ipynb", ".html", ".md"}

#: Source that produces results rather than recording them. Searched, because a
#: hyperparameter's counterpart is a call site, but a value's absence from source does not
#: make it absent: it may sit in an output this stage cannot read.
CODE = {".py", ".r", ".jl", ".m", ".sh", ".toml", ".cfg", ".ini", ".rmd", ".qmd"}

#: A spreadsheet is a zip of XML, so its cells are readable without a dependency. Treating
#: it as opaque cost one development article 356 of 362 table cells: every result it reports
#: sits in `results/rep_values.xlsx`, and the scan called them not found.
SPREADSHEET = {".xlsx", ".xlsm"}

#: The manuscript, where the repository carries it. Matching a paper against its own source
#: confirms that the paper equals itself. On two of three development articles the LaTeX
#: body and table files ship in the repository, and including them put confirmation at 96
#: and 98 per cent. Excluded outright rather than down-weighted.
MANUSCRIPT = {".tex", ".bib", ".bbl", ".cls", ".sty", ".rtf", ".docx", ".odt"}

#: Binary records with a reader in `artifact_readers`. Both formats here execute code when
#: opened the ordinary way, and neither is opened the ordinary way: see that module.
BINARY = {".pkl": read_pickle, ".pickle": read_pickle,
          ".rds": read_rdata, ".rdata": read_rdata, ".rda": read_rdata}

#: Machine-readable records with no reader here. A value missing from the corpus while one
#: of these sits unread is `unchecked`: the artifact may hold it, and nothing asked.
UNREAD = {".npy", ".npz", ".pt", ".pth", ".h5", ".hdf5", ".mat", ".parquet", ".feather",
          ".xls", ".db", ".sqlite", ".zip", ".7z", ".tar"}

#: Renderings of results rather than records of them. A value legible only inside a plot
#: image is not machine-addressable, which is a true statement about the artifact rather
#: than a limit of this tool, so these do not make a miss `unchecked`. Their count is
#: reported alongside every verdict so the reader can weigh it.
RENDERED = {".png", ".jpg", ".jpeg", ".pdf", ".eps", ".ps", ".svg", ".gif", ".tif", ".tiff"}

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".ipynb_checkpoints", "venv", ".venv"}

MAX_BYTES = 40_000_000

NUMBER = re.compile(r"(?<![\w.])[-+]?\d[\d,]*(?:\.\d+)?(?:[eE][-+]?\d+)?(?![\w])")

TRACEABLE = {"measurement", "table_cell", "parameter", "equation_content", "quoted_value"}

#: A value printed under a column headed as another study's result. Confirming one checks
#: that the authors transcribed the work they are comparing against, which is a real
#: relation and not the one a reader assumes: it says nothing about whether their own run
#: produced anything. Reported apart from the paper's own claims for that reason, and not
#: discarded, because on one development article all 118 such values are in the artifact at
#: 98 per cent precision while the authors' own results confirm at 3 per cent -- a
#: difference invisible in any figure that pools them.
QUOTED_KIND = "quoted_value"

#: Tiers of match strength, weakest first. A coincidental match becomes about ten times less
#: likely per constraining digit, so the tiers track digits rather than magnitude: finding
#: `3` in a repository says nothing and finding `94.872` says a great deal. Rates are
#: reported per tier and never pooled, since one percentage over both measures mostly how
#: many small integers the paper happened to print.
TIERS = ("trivial", "weak", "moderate", "strong")

#: Named subsets a reader asks for. Each is a question about the work rather than a slice of
#: the data: what did the paper report, and what was it configured with.
VIEWS = {
    "results": ("the paper's own reported values, carrying a decimal point",
                lambda r: "." in r["printed"] and r["kind"] in ("measurement", "table_cell")),
    "transcribed": ("values quoted from the study being reproduced; confirming one checks "
                    "transcription, not the authors' run",
                    lambda r: r["kind"] == QUOTED_KIND),
    "hyperparameters": ("values bound to a named symbol, and equation constants",
                        lambda r: r["kind"] in ("parameter", "equation_content")),
    "counts": ("integer quantities stated about the work",
               lambda r: "." not in r["printed"] and r["kind"] in ("measurement", "table_cell")),
    "own": ("every value the paper claims as its own",
            lambda r: r["kind"] != QUOTED_KIND),
    "all": ("every traceable value, including quoted ones", lambda r: True),
}


def constraining_digits(printed: str) -> int:
    """Digits that constrain a match.

    Leading zeros constrain nothing, so `0.9489` counts four. A trailing zero on an integer
    usually marks a round figure a repository holds for unrelated reasons, so `100` and `20`
    count what is left once the zeros come off.
    """
    body = printed.lstrip("-+").replace(",", "")
    if "." in body:
        return max(1, len(body.replace(".", "").lstrip("0")))
    return max(1, len(body.strip("0") or "0"))


def strength(printed: str) -> str:
    digits = constraining_digits(printed)
    return TIERS[min(3, max(0, digits - 2))] if digits >= 2 else "trivial"


def collect(root: pathlib.Path) -> dict[str, list[pathlib.Path]]:
    """Files under `root` grouped by what they can settle, ignoring the manuscript."""
    groups: dict[str, list[pathlib.Path]] = {
        "data": [], "spreadsheet": [], "binary": [], "code": [], "compressed": [],
        "unread": [], "rendered": [], "manuscript": []}
    for path in root.rglob("*"):
        if not path.is_file() or SKIP_DIRS & set(path.parts):
            continue
        suffix = path.suffix.lower()
        for name, group in (("manuscript", MANUSCRIPT), ("spreadsheet", SPREADSHEET),
                            ("binary", BINARY), ("data", DATA), ("code", CODE),
                            ("compressed", COMPRESSORS), ("unread", UNREAD),
                            ("rendered", RENDERED)):
            if suffix in group:
                groups[name].append(path)
                break
    return groups


def read_spreadsheet(path: pathlib.Path) -> str:
    """Cell values from an xlsx as newline-separated text.

    The format is a zip holding one XML part per worksheet plus a shared string table.
    Numeric cells carry their value inline in `<v>`, which is what a printed value is
    compared against.
    """
    parts: list[str] = []
    try:
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if not (name.startswith("xl/worksheets/") and name.endswith(".xml")) \
                        and name != "xl/sharedStrings.xml":
                    continue
                try:
                    root = ElementTree.fromstring(archive.read(name))
                except ElementTree.ParseError:
                    continue
                for node in root.iter():
                    if node.tag.rsplit("}", 1)[-1] in ("v", "t") and node.text:
                        parts.append(node.text)
    except (zipfile.BadZipFile, OSError):
        return ""
    return "\n".join(parts)


def build_index(paths: list[pathlib.Path],
                root: pathlib.Path) -> tuple[dict[str, tuple[str, int]], list[str]]:
    """Numeric strings in the artifact mapped to where each first occurs, and what went
    unread.

    One pass over the files rather than one pass per value; the location is what turns a
    verdict into a receipt. The second return value names every file that was skipped or
    only partly parsed, which is what separates `absent` from `unchecked` downstream.
    """
    index: dict[str, tuple[str, int]] = {}
    unread: list[str] = []
    scratch = tempfile.mkdtemp(prefix="artifact-unwrap-")
    for path in paths:
        relative = str(path.relative_to(root))
        if path.suffix.lower() in COMPRESSORS:
            member = unwrap(path, pathlib.Path(scratch))
            if member is None:
                unread.append(f"{relative} (compressed, no inner extension to dispatch on)")
                continue
            path = member
        suffix = path.suffix.lower()
        try:
            if path.stat().st_size > MAX_BYTES:
                unread.append(f"{relative} (over {MAX_BYTES // 1_000_000} MB)")
                continue
            if suffix in BINARY:
                values, complete = BINARY[suffix](path)
                if not complete:
                    unread.append(f"{relative} (parsed as far as it was understood)")
                for value in values:
                    index.setdefault(value, (relative, 0))
                    if "." in value:
                        # A double round-trips through repr with full precision; the printed
                        # form in a paper is shorter, so index the trimmed forms too.
                        for places in range(1, 7):
                            index.setdefault(f"{float(value):.{places}f}", (relative, 0))
                continue
            text = (read_spreadsheet(path) if suffix in SPREADSHEET
                    else path.read_text(errors="replace"))
        except OSError:
            unread.append(f"{relative} (unreadable)")
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for match in NUMBER.finditer(line):
                index.setdefault(match.group(0), (relative, lineno))
    shutil.rmtree(scratch, ignore_errors=True)
    return index, unread


def report(records: list[dict], title: str, note: str, show: int) -> None:
    if not records:
        print(f"  {title}: no values\n")
        return
    print(f"  {title} — {note}")
    print(f"  {len(records)} values\n")
    print(f"    {'tier':10}{'values':>8}{'confirmed':>11}{'absent':>8}{'unchecked':>11}{'rate':>8}")
    for tier in TIERS:
        row = [r for r in records if r["strength"] == tier]
        if not row:
            continue
        hit = sum(1 for r in row if r["verdict"] == "confirmed")
        print(f"    {tier:10}{len(row):>8}{hit:>11}"
              f"{sum(1 for r in row if r['verdict'] == 'absent'):>8}"
              f"{sum(1 for r in row if r['verdict'] == 'unchecked'):>11}{hit / len(row):>8.0%}")

    load = [r for r in records if r["strength"] in ("moderate", "strong")]
    if load:
        hit = sum(1 for r in load if r["verdict"] == "confirmed")
        print(f"\n    load-bearing (4+ constraining digits): {hit} of {len(load)} "
              f"confirmed ({hit / len(load):.0%})")

    confirmed = [r for r in load if r["verdict"] == "confirmed"]
    if confirmed:
        print(f"\n    confirmed, with the location that settles each:")
        for r in confirmed[:show]:
            print(f"      {r['printed']:>10}  paper line {r['line']:<6} -> "
                  f"{r['found_in']}:{r['found_line']}")
        if len(confirmed) > show:
            print(f"      ... {len(confirmed) - show} more in the written record")

    missing = [r for r in load if r["verdict"] != "confirmed"]
    if missing:
        print(f"\n    not settled:")
        for r in missing[:show]:
            print(f"      {r['printed']:>10}  paper line {r['line']:<6} {r['verdict']:<10} "
                  f"{r['context'][:52]}")
        if len(missing) > show:
            print(f"      ... {len(missing) - show} more")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scan", help="the .numbers.json written by scan_numbers.py")
    parser.add_argument("repo", help="checkout of the article's pinned artifact")
    parser.add_argument("--view", default="results", choices=sorted(VIEWS) + ["every"],
                        help="which filtered view to print (default: results)")
    parser.add_argument("--show", type=int, default=12, help="rows to list per section")
    args = parser.parse_args()

    root = pathlib.Path(args.repo)
    groups = collect(root)
    index, partial = build_index(
        groups["data"] + groups["spreadsheet"] + groups["binary"] + groups["compressed"]
        + groups["code"], root)

    # A miss is `absent` only where every machine-readable record was read to the end. One
    # unread record is enough to make every miss `unchecked`: the value may sit in it, and
    # reporting "not found" would state a limit of this tool as a disagreement between a
    # paper and its data. Renderings are excluded from the test deliberately -- a number
    # legible only inside a plot image is not machine-addressable, which is a fact about
    # the artifact.
    unread = partial + [str(p.relative_to(root)) for p in groups["unread"]]

    records = [r for r in json.loads(pathlib.Path(args.scan).read_text())["records"]
               if r["kind"] in TRACEABLE]
    for record in records:
        location = index.get(record["printed"])
        record["strength"] = strength(record["printed"])
        record["verdict"] = ("confirmed" if location
                             else "unchecked" if unread else "absent")
        record["found_in"], record["found_line"] = location or ("", 0)

    print(f"\n  {args.scan}  against  {args.repo}")
    print(f"  artifact: {len(groups['data'])} data, {len(groups['spreadsheet'])} spreadsheet, "
          f"{len(groups['binary'])} binary (read inertly), {len(groups['code'])} code, "
          f"{len(groups['rendered'])} rendered, {len(groups['manuscript'])} manuscript "
          f"(excluded)")
    print(f"  {len(index):,} distinct numeric values indexed from the artifact")
    if unread:
        print(f"  {len(unread)} record(s) NOT read, so every miss below is `unchecked`:")
        for name in unread[:6]:
            print(f"      {name}")
        if len(unread) > 6:
            print(f"      ... and {len(unread) - 6} more")
    else:
        print("  every machine-readable record was read to the end")
    print()

    for name in (sorted(VIEWS) if args.view == "every" else [args.view]):
        note, keep = VIEWS[name]
        report([r for r in records if keep(r)], name, note, args.show)

    out = pathlib.Path(args.scan).with_suffix(".confirmed.json")
    out.write_text(json.dumps(
        {"scan": args.scan, "repo": args.repo,
         "files": {k: len(v) for k, v in groups.items()},
         "unread": unread,
         "views": {name: {tier: {v: sum(1 for r in records if keep(r)
                                        and r["strength"] == tier and r["verdict"] == v)
                                 for v in ("confirmed", "absent", "unchecked")}
                          for tier in TIERS}
                   for name, (_, keep) in VIEWS.items()},
         "records": records}, indent=2) + "\n")
    print(f"  wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
