"""Lint the records with papis doctor, and a `.bib` for keys it defines twice.

    citations lint                 # the records, through papis
    citations lint --json          # machine-readable
    citations lint --bib refs.bib  # duplicate keys, papis not required

The two modes answer different questions about different artifacts. The records mode asks
whether a record carries the fields its entry type requires, and needs papis to know what those
are. The `--bib` mode asks whether a bibliography defines any key twice, which needs nothing but
the file: it runs where papis is not installed, which is most continuous integration.

A repeated key is worth its own check because BibTeX's response to one is non-fatal and surfaces
somewhere else. It keeps the copy the file defines first, skips the repeat, and writes a `.bbl`
without it, so the reference list prints an entry nobody is looking at while the corrected one
sits in the `.bib`. See `add.py`, which refuses to write one.

Papis encodes years of BibTeX edge cases -- which fields each entry type requires, which
BibLaTeX keys are aliases, what counts as junk in an author field. Rediscovering that one
reviewer complaint at a time is a bad use of anyone's time, so this borrows it.

Papis owns nothing. `records/` stays authoritative; this projects each record into the shape
papis expects, runs its checks against the projection, and reports. Nothing is written back.

Note that papis means something different by `cited_by` -- it fetches, from Crossref, the works
that cite a document. Ours records which of our own papers cite it. Same words, opposite
direction, which is why the projection drops the relationship entirely rather than trying to
map it.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import shutil
import subprocess
import tempfile
from typing import Any

import yaml

from citations import bibtex, paths
from citations.exceptions import CitationsError
from citations.models import Record, load_record

#: Venue words that decide which BibTeX entry type a record projects to, and therefore which
#: fields papis will demand of it.
PROCEEDINGS_WORDS = (
    "proceedings",
    "conference",
    "workshop",
    "symposium",
    "neurips",
    "icml",
    "iclr",
    "acl",
    "emnlp",
    "aaai",
    "ijcai",
)
PUBLISHER_WORDS = ("press", "publisher", "wiley", "springer", "mifflin", "mcnally", "routledge")


def find_papis() -> pathlib.Path | None:
    """Wherever papis is, or None.

    Resolved from PATH rather than a fixed path inside this package: an interpreter-relative
    guess is wrong under every install that is not the one it was written for, and it fails
    by reporting that papis is missing rather than by looking in the wrong place out loud.
    """
    found = shutil.which("papis")
    return pathlib.Path(found) if found else None


def project(rec: Record) -> dict:
    """A record in the shape papis judges. Deliberately lossy."""
    authors = []
    for a in rec.authors:
        if "," in a:
            fam, giv = (x.strip() for x in a.split(",", 1))
        else:
            parts = a.split()
            fam, giv = (parts[-1], " ".join(parts[:-1])) if parts else (a, "")
        authors.append({"family": fam, "given": giv})

    doc: dict[str, Any] = {
        "ref": rec.slug,
        "title": rec.title,
        "author": " and ".join(rec.authors),
        "author_list": authors,
    }
    year = rec.year.strip()
    if year.isdigit():
        doc["year"] = int(year)  # papis wants an int; ours are strings from BibTeX

    venue = rec.venue.strip()
    lowered = venue.lower()
    if any(w in lowered for w in PROCEEDINGS_WORDS):
        doc["type"], doc["booktitle"] = "inproceedings", venue
    elif any(w in lowered for w in PUBLISHER_WORDS):
        doc["type"], doc["publisher"] = "book", venue
    elif venue:
        doc["type"], doc["journal"] = "article", venue
    else:
        doc["type"] = "misc"

    for key, value in (("doi", rec.doi), ("url", rec.url)):
        if value:
            doc[key] = value
    return doc


def bib_duplicates(files: list[pathlib.Path], as_json: bool) -> int:
    """Every key each file defines more than once. Exit 1 if any file does.

    Exits 1 under `--json` as well. A machine-readable mode that reports findings and exits 0
    is a check that cannot fail, which is worse in continuous integration than no check: the
    pipeline goes green while the file it examined is broken.
    """
    findings: list[dict[str, Any]] = []
    entries = 0
    for path in files:
        if not path.is_file():
            raise CitationsError(f"no such file: {path}")
        text = bibtex.read(path)
        entries += len(bibtex.key_lines(text))
        for _folded, occurrences in sorted(bibtex.duplicate_keys(text).items()):
            findings.append(
                {
                    "file": str(path),
                    "keys": [key for key, _line in occurrences],
                    "lines": [line for _key, line in occurrences],
                }
            )

    if as_json:
        print(json.dumps(findings, indent=1))
        return 1 if findings else 0

    # Findings sit under the file they were found in. Two bibliographies repeating the same key
    # is one finding each, and a flat list of keys names neither -- copies of one bibliography
    # in different repositories share a basename as well as their defects.
    for path in files:
        print(f"  bib  {path}")
        for f in (x for x in findings if x["file"] == str(path)):
            written = f["keys"] if len(set(f["keys"])) > 1 else [f["keys"][0]]
            lines = ", ".join(str(line) for line in f["lines"])
            print(f"    {' / '.join(written):<44}lines {lines}")
    print(f"\n  {entries} entries, {len(findings)} repeated key(s)")
    if not findings:
        print("  no key is defined twice.")
        return 0
    print("\n  BibTeX keeps the copy a file defines first and skips the repeat, writing a .bbl")
    print("  without it: an entry appended below one that is already there never reaches the")
    print("  reference list, and the file gives no sign of which copy is being printed. Where")
    print("  two keys differ only in case, the citation goes undefined instead. Delete one, or")
    print("  give it another key.")
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="citations lint", description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument(
        "--bib",
        action="append",
        metavar="FILE",
        help="a bibliography to check for repeated keys, instead of the records; repeatable, "
        "and needs no papis and no library",
    )
    a = ap.parse_args(argv)

    if a.bib:
        return bib_duplicates([pathlib.Path(p).expanduser() for p in a.bib], a.json)

    papis = find_papis()
    if papis is None:
        print("  papis is not on PATH\n  uv tool install papis   (or pip install papis)")
        return 1

    try:
        record_dir = paths.records()
    except CitationsError as e:
        print(str(e))
        return 2

    records = sorted(record_dir.glob("*.yaml"))
    if not records:
        print(f"  no records in {record_dir}")
        return 2

    with tempfile.TemporaryDirectory() as tmp:
        lib = pathlib.Path(tmp) / "lib"
        lib.mkdir()
        for p in records:
            rec = load_record(p)
            d = lib / rec.slug
            d.mkdir(exist_ok=True)
            (d / "info.yaml").write_text(
                yaml.safe_dump(project(rec), sort_keys=False, allow_unicode=True)
            )

        # papis reads its config from the platform location under HOME, not from an env var,
        # so the sandboxed HOME has to contain one. Getting this wrong makes papis fail to
        # find the library and print nothing, which this function would otherwise report as
        # a clean bill of health -- a check that passes by examining nothing.
        cfg = pathlib.Path(tmp) / "Library" / "Application Support" / "papis"
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / "config").write_text(f"[lint]\ndir = {lib}\n")
        proc = subprocess.run(
            [str(papis), "-l", "lint", "doctor", "--all", "--all-checks"],
            capture_output=True,
            text=True,
            env={"HOME": tmp, "PATH": "/usr/bin:/bin"},
        )
        out = proc.stdout
        if proc.returncode != 0 and not out.strip():
            print("  papis could not run; refusing to report a clean result")
            print(f"  {(proc.stderr or '').strip()[:400]}")
            return 2

    issues = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            issues.append({"check": parts[0], "key": parts[1], "slug": pathlib.Path(parts[2]).name})

    if a.json:
        print(json.dumps(issues, indent=1))
        return 0

    counts = collections.Counter((i["check"], i["key"]) for i in issues)
    print(f"  {len(records)} records, {len(issues)} issues\n")
    for (check, key), n in counts.most_common():
        print(f"  {n:>4}  {check:<26}{key}")
        for i in [x for x in issues if (x["check"], x["key"]) == (check, key)][:4]:
            print(f"          {i['slug']}")
        if n > 4:
            print(f"          ... and {n - 4} more")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
