"""Lint the records with papis doctor.

Papis encodes years of BibTeX edge cases -- which fields each entry type requires, which
BibLaTeX keys are aliases, what counts as junk in an author field. Rediscovering that one
reviewer complaint at a time is a bad use of anyone's time, so this borrows it.

Papis owns nothing. `records/` stays authoritative; this projects each record into the shape
papis expects, runs its checks against the projection, and reports. Nothing is written back.

Note that papis means something different by `cited_by` -- it fetches, from Crossref, the works
that cite a document. Ours records which of our own papers cite it. Same words, opposite
direction, which is why the projection drops the relationship entirely rather than trying to
map it.

    python lint.py             # report
    python lint.py --json      # machine-readable
"""
from __future__ import annotations

import argparse
import collections
import pathlib
import shutil
import subprocess
import sys
import tempfile

import yaml

ROOT = pathlib.Path(__file__).resolve().parent
RECORDS = ROOT / "records"
PAPIS = ROOT / ".venv" / "bin" / "papis"

# What a record has to look like for papis to judge it. Deliberately lossy.
def project(rec: dict) -> dict:
    authors = []
    for a in rec.get("authors") or []:
        if "," in a:
            fam, giv = (x.strip() for x in a.split(",", 1))
        else:
            parts = a.split()
            fam, giv = (parts[-1], " ".join(parts[:-1])) if parts else (a, "")
        authors.append({"family": fam, "given": giv})

    doc = {
        "ref": rec["slug"],
        "title": rec.get("title", ""),
        "author": " and ".join(rec.get("authors") or []),
        "author_list": authors,
    }
    year = str(rec.get("year") or "").strip()
    if year.isdigit():
        doc["year"] = int(year)          # papis wants an int; ours are strings from BibTeX

    venue = (rec.get("venue") or "").strip()
    # Type follows the venue, since that is what decides which fields BibTeX demands.
    lowered = venue.lower()
    if any(w in lowered for w in ("proceedings", "conference", "workshop", "symposium",
                                  "neurips", "icml", "iclr", "acl", "emnlp", "aaai", "ijcai")):
        doc["type"] = "inproceedings"
        doc["booktitle"] = venue
    elif any(w in lowered for w in ("press", "publisher", "wiley", "springer", "mifflin",
                                    "mcnally", "routledge")):
        doc["type"] = "book"
        doc["publisher"] = venue
    elif venue:
        doc["type"] = "article"
        doc["journal"] = venue
    else:
        doc["type"] = "misc"

    for k in ("doi", "url"):
        if rec.get(k):
            doc[k] = rec[k]
    return doc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    if not PAPIS.exists():
        print(f"  papis not installed at {PAPIS}\n  uv pip install --python .venv/bin/python papis")
        return 1

    records = sorted(RECORDS.glob("*.yaml"))
    with tempfile.TemporaryDirectory() as tmp:
        lib = pathlib.Path(tmp) / "lib"
        lib.mkdir()
        for p in records:
            rec = yaml.safe_load(p.read_text()) or {}
            d = lib / rec["slug"]
            d.mkdir(exist_ok=True)
            (d / "info.yaml").write_text(
                yaml.safe_dump(project(rec), sort_keys=False, allow_unicode=True))

        # papis reads its config from the platform location under HOME, not from an env var,
        # so the sandboxed HOME has to contain one. Getting this wrong makes papis fail to
        # find the library and print nothing, which this function would otherwise report as
        # a clean bill of health -- a check that passes by examining nothing.
        cfg = pathlib.Path(tmp) / "Library" / "Application Support" / "papis"
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / "config").write_text(f"[lint]\ndir = {lib}\n")
        proc = subprocess.run(
            [str(PAPIS), "-l", "lint", "doctor", "--all", "--all-checks"],
            capture_output=True, text=True,
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
            issues.append({"check": parts[0], "key": parts[1],
                           "slug": pathlib.Path(parts[2]).name})

    if a.json:
        import json
        print(json.dumps(issues, indent=1))
        return 0

    counts = collections.Counter((i["check"], i["key"]) for i in issues)
    print(f"  {len(records)} records, {len(issues)} issues\n")
    for (check, key), n in counts.most_common():
        print(f"  {n:>4}  {check:<26}{key}")
        for i in [x for x in issues if (x['check'], x['key']) == (check, key)][:4]:
            print(f"          {i['slug']}")
        if n > 4:
            print(f"          ... and {n - 4} more")
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
