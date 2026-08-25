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

#: Distinctive lines lifted from the article and looked for in each candidate file. A
#: repository that carries its own manuscript is matching the paper against itself, and an
#: extension list loses to the next format that does it -- one development article ships its
#: paper as `article/draft.md`, which no list of document extensions would catch. Content
#: settles it in any format.
MANUSCRIPT_PROBES = 14

#: Probes a file must contain verbatim before it counts as a copy of the manuscript. Three
#: long sentences shared with the paper is not a coincidence, and is not what a results file
#: looks like.
MANUSCRIPT_HITS = 3


def manuscript_probes(article: str) -> list[str]:
    """Long, distinctive lines from across the article, for detecting a copy of it.

    Drawn at even intervals so a repository holding only one section is still caught, and
    restricted to lines long enough that sharing one verbatim means something.
    """
    lines = [line.strip() for line in article.splitlines() if 60 <= len(line.strip()) <= 200]
    if not lines:
        return []
    step = max(1, len(lines) // MANUSCRIPT_PROBES)
    return lines[::step][:MANUSCRIPT_PROBES]


def is_manuscript(text: str, probes: list[str]) -> bool:
    if not probes:
        return False
    return sum(1 for probe in probes if probe in text) >= MANUSCRIPT_HITS


#: Binary records with a reader in `artifact_readers`. Both formats here execute code when
#: opened the ordinary way, and neither is opened the ordinary way: see that module.
BINARY = {
    ".pkl": read_pickle,
    ".pickle": read_pickle,
    ".rds": read_rdata,
    ".rdata": read_rdata,
    ".rda": read_rdata,
}

#: Machine-readable records with no reader here. A value missing from the corpus while one
#: of these sits unread is `unchecked`: the artifact may hold it, and nothing asked.
UNREAD = {
    ".npy",
    ".npz",
    ".pt",
    ".pth",
    ".h5",
    ".hdf5",
    ".mat",
    ".parquet",
    ".feather",
    ".xls",
    ".db",
    ".sqlite",
    ".zip",
    ".7z",
    ".tar",
}

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

#: How much evidence a confirmation must carry before it is reported as one. The tiers are a
#: property of the value; a profile is a decision about which tiers this reader will act on,
#: and the right answer differs by use. A reader auditing their own draft wants everything
#: worth a second look; a reader making a claim about someone else's paper wants only what
#: survives a null.
#:
#:   strict    only values with five or more constraining digits, and only from an artifact
#:             where shape-matched decoys never land. Nothing here should need a second
#:             opinion.
#:   balanced  the weakest tier whose decoy rate on this artifact stays under five per cent,
#:             and every stronger tier with it.
#:   lenient   every tier, each labelled with its own decoy rate, so a reader can discount
#:             rather than be told what to ignore.
PROFILES = {
    "strict": {"floor": "strong", "max_decoy": 0.01},
    "balanced": {"floor": "weak", "max_decoy": 0.05},
    "lenient": {"floor": "trivial", "max_decoy": 1.0},
}


def trusted_tiers(
    records: list[dict], index: dict, printed: set[str], profile: dict
) -> tuple[list[str], dict[str, float]]:
    """Tiers this profile will report on, and the decoy rate measured for each.

    A tier qualifies when its own decoy rate clears the profile's ceiling and every stronger
    tier does too. Evidence has to be monotonic: reporting four-digit matches while
    withholding five-digit ones would be incoherent.
    """
    from precision_check import decoys

    rates: dict[str, float] = {}
    for tier in TIERS:
        row = [r for r in records if r["strength"] == tier]
        if not row:
            continue
        trials = [d for r in row for d in decoys(r["printed"]) if d not in printed]
        rates[tier] = (sum(1 for d in trials if d in index) / len(trials)) if trials else 0.0

    floor = TIERS.index(profile["floor"])
    ok = [t for t in TIERS if t in rates and rates[t] <= profile["max_decoy"]]
    keep = [
        t
        for i, t in enumerate(TIERS)
        if t in ok and i >= floor and all(x in ok for x in TIERS[i:] if x in rates)
    ]
    return keep, rates


#: Named subsets a reader asks for. Each is a question about the work rather than a slice of
#: the data: what did the paper report, and what was it configured with.
VIEWS = {
    "results": (
        "the paper's own reported values, carrying a decimal point",
        lambda r: "." in r["printed"] and r["kind"] in ("measurement", "table_cell"),
    ),
    "transcribed": (
        "values quoted from the study being reproduced; confirming one checks "
        "transcription, not the authors' run",
        lambda r: r["kind"] == QUOTED_KIND,
    ),
    "hyperparameters": (
        "values bound to a named symbol, and equation constants",
        lambda r: r["kind"] in ("parameter", "equation_content"),
    ),
    "counts": (
        "integer quantities stated about the work",
        lambda r: "." not in r["printed"] and r["kind"] in ("measurement", "table_cell"),
    ),
    "own": ("every value the paper claims as its own", lambda r: r["kind"] != QUOTED_KIND),
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
        "data": [],
        "spreadsheet": [],
        "binary": [],
        "code": [],
        "compressed": [],
        "unread": [],
        "rendered": [],
        "manuscript": [],
    }
    for path in root.rglob("*"):
        if not path.is_file() or SKIP_DIRS & set(path.parts):
            continue
        suffix = path.suffix.lower()
        for name, group in (
            ("manuscript", MANUSCRIPT),
            ("spreadsheet", SPREADSHEET),
            ("binary", BINARY),
            ("data", DATA),
            ("code", CODE),
            ("compressed", COMPRESSORS),
            ("unread", UNREAD),
            ("rendered", RENDERED),
        ):
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
                if (
                    not (name.startswith("xl/worksheets/") and name.endswith(".xml"))
                    and name != "xl/sharedStrings.xml"
                ):
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


#: Transforms tried between a printed value and a stored one, each named so a confirmation
#: says which relation settled it. A paper prints `14.38` and its artifact stores
#: `0.1438333`: the same measurement in a different unit at a different precision. Matching
#: strings alone reported 3 per cent of one article's own results as present when 49 per
#: cent are there.
#:
#: Off by default, because measurement says it manufactures agreement rather than finding
#: it. On `Obadage:2025`, whose spreadsheet stores reproduced accuracies as fractions, the
#: unit transform takes the moderate tier from 5 per cent confirmed to 95 per cent -- and
#: takes shape-matched decoys from 1.8 per cent to 90.9 per cent. At the strong tier it
#: confirms decoys more often than real values. Restricting the search to the results file
#: alone leaves precision at 7 per cent.
#:
#: The values really are there; the transform is not wrong about that. It cannot demonstrate
#: it. That spreadsheet holds 1,702 floating-point values in the same range, so rounding
#: them to the two decimals a paper prints covers nearly every two-decimal value, and a
#: fabricated number matches as readily as a real one. Four constraining digits against a
#: dense artifact carry no information, whatever transform is applied.
#:
#: Kept, and enabled only by `--allow-transforms`, so the option is available with its cost
#: stated rather than discovered.
TRANSFORMS = (
    ("printed exactly", lambda v: v),
    ("stored as a fraction of one", lambda v: v / 100),
    ("stored as a percentage", lambda v: v * 100),
)


def transformed_hit(
    printed: str, numeric_index: dict[float, tuple[str, int, str]]
) -> tuple[tuple[str, int, str], str] | None:
    """The first transform under which the printed value matches a stored one, if any.

    Comparison is at the printed precision, so `14.38` matches a stored `0.1438333` and does
    not match a stored `0.1439`. Rounding an artifact down to the paper's precision is what
    the paper itself did; inventing precision the paper never printed is not.
    """
    try:
        value = float(printed.replace(",", ""))
    except ValueError:
        return None
    places = len(printed.split(".")[1]) if "." in printed else 0
    for name, apply in TRANSFORMS:
        target = f"{apply(value):.{places}f}"
        for stored, location in numeric_index.items():
            if f"{stored:.{places}f}" == target:
                return location, name
    return None


def build_index(
    paths: list[pathlib.Path], root: pathlib.Path, probes: list[str] | None = None
) -> tuple[dict[str, tuple[str, int, str]], list[str]]:
    """Numeric strings in the artifact mapped to where each first occurs, and what went
    unread.

    One pass over the files rather than one pass per value; the location is what turns a
    verdict into a receipt. The second return value names every file that was skipped or
    only partly parsed, which is what separates `absent` from `unchecked` downstream.
    """
    index: dict[str, tuple[str, int, str]] = {}
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
                    index.setdefault(value, (relative, 0, ""))
                    if "." in value:
                        # A double round-trips through repr with full precision; the printed
                        # form in a paper is shorter, so index the trimmed forms too.
                        for places in range(1, 7):
                            index.setdefault(f"{float(value):.{places}f}", (relative, 0, ""))
                continue
            text = (
                read_spreadsheet(path)
                if suffix in SPREADSHEET
                else path.read_text(errors="replace")
            )
        except OSError:
            unread.append(f"{relative} (unreadable)")
            continue
        if probes and is_manuscript(text, probes):
            # The paper itself, under whatever name the repository gave it. Indexing it
            # would confirm that the paper equals itself.
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for match in NUMBER.finditer(line):
                # The surrounding text is what a reader needs to judge whether the artifact
                # means the same thing by this number as the paper does. A file and a line
                # number establish that a string occurs; they do not establish a match.
                index.setdefault(match.group(0), (relative, lineno, line.strip()[:110]))
    shutil.rmtree(scratch, ignore_errors=True)
    return index, unread


def report(records: list[dict], title: str, note: str, show: int, tiers: list[str]) -> None:
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
        print(
            f"    {tier:10}{len(row):>8}{hit:>11}"
            f"{sum(1 for r in row if r['verdict'] == 'absent'):>8}"
            f"{sum(1 for r in row if r['verdict'] == 'unchecked'):>11}{hit / len(row):>8.0%}"
        )

    load = [r for r in records if r["strength"] in tiers]
    if load:
        hit = sum(1 for r in load if r["verdict"] == "confirmed")
        print(
            f"\n    reported under this profile: {hit} of {len(load)} confirmed "
            f"({hit / len(load):.0%})"
        )
    else:
        print("\n    nothing in this view clears the profile")

    confirmed = [r for r in load if r["verdict"] == "confirmed"]
    if confirmed:
        print("\n    confirmed, with the location that settles each:")
        for r in confirmed[:show]:
            print(
                f"      {r['printed']:>10}  paper line {r['line']:<6} -> "
                f"{r['found_in']}:{r['found_line']}"
                + (f"   [{r['relation']}]" if r["relation"] != "printed exactly" else "")
            )
        if len(confirmed) > show:
            print(f"      ... {len(confirmed) - show} more in the written record")

    missing = [r for r in load if r["verdict"] != "confirmed"]
    if missing:
        print("\n    not settled:")
        for r in missing[:show]:
            print(
                f"      {r['printed']:>10}  paper line {r['line']:<6} {r['verdict']:<10} "
                f"{r['context'][:52]}"
            )
        if len(missing) > show:
            print(f"      ... {len(missing) - show} more")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scan", help="the .numbers.json written by scan_numbers.py")
    parser.add_argument("repo", help="checkout of the article's pinned artifact")
    parser.add_argument(
        "--view",
        default="results",
        choices=[*sorted(VIEWS), "every"],
        help="which filtered view to print (default: results)",
    )
    parser.add_argument("--show", type=int, default=12, help="rows to list per section")
    parser.add_argument(
        "--allow-transforms",
        action="store_true",
        help="also match under a unit change; measured to destroy precision "
        "on the development corpus, see TRANSFORMS",
    )
    parser.add_argument(
        "--profile",
        default="balanced",
        choices=sorted(PROFILES),
        help="how much evidence a confirmation must carry (default: balanced)",
    )
    args = parser.parse_args()

    root = pathlib.Path(args.repo)
    groups = collect(root)
    article = pathlib.Path(args.scan.replace(".numbers.json", ".txt"))
    probes = manuscript_probes(article.read_text(errors="replace")) if article.exists() else []
    index, partial = build_index(
        groups["data"]
        + groups["spreadsheet"]
        + groups["binary"]
        + groups["compressed"]
        + groups["code"],
        root,
        probes,
    )

    # A miss is `absent` only where every machine-readable record was read to the end. One
    # unread record is enough to make every miss `unchecked`: the value may sit in it, and
    # reporting "not found" would state a limit of this tool as a disagreement between a
    # paper and its data. Renderings are excluded from the test deliberately -- a number
    # legible only inside a plot image is not machine-addressable, which is a fact about
    # the artifact.
    unread = partial + [str(p.relative_to(root)) for p in groups["unread"]]

    records = [
        r
        for r in json.loads(pathlib.Path(args.scan).read_text())["records"]
        if r["kind"] in TRACEABLE
    ]
    # Values keyed numerically as well as by string, so a transform can be tried against
    # what the artifact stores rather than against how it happens to be written.
    numeric_index: dict[float, tuple[str, int, str]] = {}
    for key, location in index.items():
        try:
            numeric_index.setdefault(float(key.replace(",", "")), location)
        except ValueError:
            continue

    for record in records:
        location = index.get(record["printed"])
        record["relation"] = "printed exactly" if location else ""
        if location is None and args.allow_transforms:
            found = transformed_hit(record["printed"], numeric_index)
            if found:
                location, record["relation"] = found
        record["strength"] = strength(record["printed"])
        record["verdict"] = "confirmed" if location else "unchecked" if unread else "absent"
        record["found_in"], record["found_line"], record["found_context"] = location or ("", 0, "")

    print(f"\n  {args.scan}  against  {args.repo}")
    print(
        f"  artifact: {len(groups['data'])} data, {len(groups['spreadsheet'])} spreadsheet, "
        f"{len(groups['binary'])} binary (read inertly), {len(groups['code'])} code, "
        f"{len(groups['rendered'])} rendered, {len(groups['manuscript'])} manuscript "
        f"(excluded)"
    )
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

    profile = PROFILES[args.profile]
    tiers, rates = trusted_tiers(records, index, {r["printed"] for r in records}, profile)
    print(
        f"  profile `{args.profile}`: reporting {', '.join(tiers) or 'no tier'}"
        f"  (decoy rate on this artifact: "
        f"{', '.join(f'{t} {rates[t]:.1%}' for t in TIERS if t in rates)})\n"
    )

    for name in sorted(VIEWS) if args.view == "every" else [args.view]:
        note, keep = VIEWS[name]
        report([r for r in records if keep(r)], name, note, args.show, tiers)

    out = pathlib.Path(args.scan).with_suffix(".confirmed.json")
    out.write_text(
        json.dumps(
            {
                "scan": args.scan,
                "repo": args.repo,
                "files": {k: len(v) for k, v in groups.items()},
                "unread": unread,
                "views": {
                    name: {
                        tier: {
                            v: sum(
                                1
                                for r in records
                                if keep(r) and r["strength"] == tier and r["verdict"] == v
                            )
                            for v in ("confirmed", "absent", "unchecked")
                        }
                        for tier in TIERS
                    }
                    for name, (_, keep) in VIEWS.items()
                },
                "records": records,
            },
            indent=2,
        )
        + "\n"
    )
    print(f"  wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
