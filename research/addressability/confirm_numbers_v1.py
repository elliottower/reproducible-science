"""Stage three: look for each traceable number in the article's pinned artifact.

Stage one enumerates what a paper states (`scan_numbers.py`); this asks whether the artifact
says the same thing. The output is three verdicts, and the third is the one the tool exists
to report honestly:

    confirmed   the printed value appears in a readable artifact
    absent      readable artifacts exist that could hold it, and none does
    unchecked   no readable artifact could hold it, so the question was never asked

`unchecked` is never `absent`. A repository holding results only in pickles, model
checkpoints or plot images is not a repository that disagrees with its paper -- it is one
that cannot be asked. Collapsing the two would report a property of the tool as a property
of the work, and would let a scanner take credit for coverage it never had.

Matching is on the printed string at printed precision, which is deliberately strict: `0.62`
does not match a stored `0.6234`. Rounding is a judgment about how the number was produced,
and a scanner that guesses at it silently converts a mismatch into an agreement.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import xml.etree.ElementTree as ElementTree
import zipfile

#: Files holding results the work produced. A printed value confirmed against one of these
#: is confirmed against the record of a run.
DATA = {
    ".csv",
    ".tsv",
    ".json",
    ".txt",
    ".dat",
    ".out",
    ".log",
    ".yaml",
    ".yml",
    ".xml",
    ".ipynb",
    ".html",
    ".md",
}

#: Source that produces results rather than recording them. Searched, because a
#: hyperparameter's counterpart is a call site, but its absence does not make a value
#: absent: the number may sit in an output this stage cannot read.
CODE = {".py", ".r", ".jl", ".m", ".sh", ".toml", ".cfg", ".ini", ".rmd", ".qmd"}

READABLE = DATA | CODE

#: The manuscript, when the repository carries it. Matching a paper against its own source
#: confirms that the paper equals itself: on two of three development articles the LaTeX
#: body and the table files ship in the repository, and including them put confirmation at
#: 96 and 98 per cent. Excluded outright rather than down-weighted.
MANUSCRIPT = {".tex", ".bib", ".bbl", ".cls", ".sty", ".rtf", ".docx", ".odt"}

#: A spreadsheet is a zip of XML, so its cells are readable without a dependency. Treating
#: it as opaque cost one development article 356 of 362 table cells: every result it
#: reports sits in `results/rep_values.xlsx`, and the scan reported them not found.
SPREADSHEET = {".xlsx", ".xlsm"}

#: Files that hold results in a form this stage cannot read. Their presence is what makes a
#: verdict `unchecked` rather than `absent`: the artifact may well contain the value.
OPAQUE = {
    ".pkl",
    ".pickle",
    ".npy",
    ".npz",
    ".pt",
    ".pth",
    ".h5",
    ".hdf5",
    ".mat",
    ".rds",
    ".rdata",
    ".parquet",
    ".feather",
    ".xls",
    ".db",
    ".sqlite",
    ".png",
    ".jpg",
    ".jpeg",
    ".pdf",
    ".eps",
    ".ps",
    ".svg",
    ".gz",
    ".zip",
}

#: Directories that hold the tool's own inputs rather than the work's outputs.
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".ipynb_checkpoints", "venv", ".venv"}

#: A file larger than this is read in full anyway -- results files are small, and truncating
#: would turn a present value into an absent one.
MAX_BYTES = 40_000_000

TRACEABLE = {"measurement", "table_cell", "parameter", "equation_content"}


#: Tiers of match strength, weakest first. A coincidental match becomes about ten times less
#: likely per constraining digit, so the tiers track digits rather than magnitude: finding
#: `3` in a repository says nothing, and finding `94.872` says a great deal. Rates are
#: reported per tier and never pooled -- a single percentage mixing the two measures mostly
#: how many small integers the paper happened to print.
TIERS = ("trivial", "weak", "moderate", "strong")


def constraining_digits(printed: str) -> int:
    """Digits that constrain a match.

    Leading zeros constrain nothing, so `0.9489` counts four. A trailing zero on an integer
    is usually a round figure a repository holds for unrelated reasons, so `100` and `20`
    count what is left after the zeros come off.
    """
    body = printed.lstrip("-+").replace(",", "")
    if "." in body:
        return max(1, len(body.replace(".", "").lstrip("0")))
    return max(1, len(body.rstrip("0").lstrip("0") or body.lstrip("0") or "0"))


def strength(printed: str) -> str:
    """Which tier a value's match falls in."""
    digits = constraining_digits(printed)
    if digits <= 2:
        return "trivial"
    if digits == 3:
        return "weak"
    if digits == 4:
        return "moderate"
    return "strong"


def collect(root: pathlib.Path) -> dict[str, list[pathlib.Path]]:
    """Files under `root` grouped by what they can settle, ignoring the manuscript."""
    groups: dict[str, list[pathlib.Path]] = {
        "data": [],
        "code": [],
        "opaque": [],
        "manuscript": [],
        "spreadsheet": [],
    }
    for path in root.rglob("*"):
        if not path.is_file() or SKIP_DIRS & set(path.parts):
            continue
        suffix = path.suffix.lower()
        if suffix in MANUSCRIPT:
            groups["manuscript"].append(path)
        elif suffix in SPREADSHEET:
            groups["spreadsheet"].append(path)
        elif suffix in DATA:
            groups["data"].append(path)
        elif suffix in CODE:
            groups["code"].append(path)
        elif suffix in OPAQUE:
            groups["opaque"].append(path)
    return groups


def read_spreadsheet(path: pathlib.Path) -> str:
    """Cell values from an xlsx, as text.

    The format is a zip holding one XML part per worksheet plus a shared string table.
    Numeric cells carry their value inline in `<v>`, which is what a printed value is
    compared against, so the shared strings are read for labels and the sheets for values.
    """
    parts = []
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            for name in names:
                if not (name.startswith("xl/worksheets/") and name.endswith(".xml")):
                    if name != "xl/sharedStrings.xml":
                        continue
                try:
                    root = ElementTree.fromstring(archive.read(name))
                except ElementTree.ParseError:
                    continue
                for node in root.iter():
                    tag = node.tag.rsplit("}", 1)[-1]
                    if tag in ("v", "t") and node.text:
                        parts.append(node.text)
    except (zipfile.BadZipFile, OSError):
        return ""
    return " ".join(parts)


def corpus(paths: list[pathlib.Path]) -> str:
    """Every readable artifact concatenated, for one pass per value rather than per file."""
    chunks = []
    for path in paths:
        try:
            if path.stat().st_size > MAX_BYTES:
                continue
            if path.suffix.lower() in SPREADSHEET:
                chunks.append(read_spreadsheet(path))
            else:
                chunks.append(path.read_text(errors="replace"))
        except OSError:
            continue
    return "\n".join(chunks)


def verdict(printed: str, text: str, searchable: bool) -> str:
    """One value against the artifact corpus.

    The boundary check keeps `0.62` from matching inside `0.6234` or `10.62`, so a
    confirmation means the artifact prints the same value rather than a value containing
    the same digits.

    A miss is `absent` only where a readable record of a run existed to search. Where the
    results live entirely in pickles, checkpoints or plot images, the artifact was never
    asked and the verdict says so.
    """
    if re.search(rf"(?<![\d.]){re.escape(printed)}(?![\d.])", text):
        return "confirmed"
    return "absent" if searchable else "unchecked"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scan", help="the .numbers.json written by scan_numbers.py")
    parser.add_argument("repo", help="checkout of the article's pinned artifact")
    args = parser.parse_args()

    records = json.loads(pathlib.Path(args.scan).read_text())["records"]
    traceable = [r for r in records if r["kind"] in TRACEABLE]

    groups = collect(pathlib.Path(args.repo))
    text = corpus(groups["data"] + groups["spreadsheet"] + groups["code"])
    searchable = bool(groups["data"] or groups["spreadsheet"])

    for record in traceable:
        record["verdict"] = verdict(record["printed"], text, searchable)
        record["strength"] = strength(record["printed"])

    counts = {
        name: sum(1 for r in traceable if r["verdict"] == name)
        for name in ("confirmed", "absent", "unchecked")
    }

    print(f"  {args.scan}")
    print(
        f"  artifact: {len(groups['data'])} data, {len(groups['spreadsheet'])} spreadsheet, "
        f"{len(groups['code'])} code, {len(groups['opaque'])} opaque, "
        f"{len(groups['manuscript'])} manuscript (excluded); "
        f"{len(text):,} characters searched\n"
    )
    print(f"  traceable values: {len(traceable)}\n")
    print(
        f"    {'tier':10}{'values':>8}{'confirmed':>11}{'absent':>8}{'unchecked':>11}"
        f"{'rate':>8}   example"
    )
    for tier in TIERS:
        row = [r for r in traceable if r["strength"] == tier]
        if not row:
            continue
        hit = sum(1 for r in row if r["verdict"] == "confirmed")
        sample = next((r["printed"] for r in row if r["verdict"] == "confirmed"), "-")
        print(
            f"    {tier:10}{len(row):>8}{hit:>11}"
            f"{sum(1 for r in row if r['verdict'] == 'absent'):>8}"
            f"{sum(1 for r in row if r['verdict'] == 'unchecked'):>11}"
            f"{hit / len(row):>8.0%}   {sample}"
        )

    load = [r for r in traceable if r["strength"] in ("moderate", "strong")]
    hit = sum(1 for r in load if r["verdict"] == "confirmed")
    print(
        f"\n    load-bearing (4+ digits): {hit} of {len(load)} confirmed"
        f"{f' ({hit / len(load):.0%})' if load else ''}\n"
    )

    for kind in sorted({r["kind"] for r in load}):
        row = [r for r in load if r["kind"] == kind]
        print(
            f"    {kind:18} {len(row):5}   "
            + "  ".join(
                f"{name} {sum(1 for r in row if r['verdict'] == name)}"
                for name in ("confirmed", "absent", "unchecked")
            )
        )

    out = pathlib.Path(args.scan).with_suffix(".confirmed.json")
    out.write_text(
        json.dumps(
            {
                "scan": args.scan,
                "repo": args.repo,
                "files": {k: len(v) for k, v in groups.items()},
                "counts": counts,
                "by_tier": {
                    tier: {
                        name: sum(
                            1 for r in traceable if r["strength"] == tier and r["verdict"] == name
                        )
                        for name in ("confirmed", "absent", "unchecked")
                    }
                    for tier in TIERS
                },
                "records": traceable,
            },
            indent=2,
        )
        + "\n"
    )
    print(f"\n  wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
