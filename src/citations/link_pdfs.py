"""Point pdfs/ at the real files, wherever the papers keep them.

This repository owns no artifacts. Each paper keeps the PDFs it cites, and this builds a
symlink farm into them, named by record slug, so a hash check or a quote check can run here
without a second copy of 1.4 GB.

Symlinks are right here and wrong inside a paper repository. A paper has to be self-contained
-- it gets submitted, cloned, and built somewhere else, and a link into a sibling directory
breaks all three. This repository is never submitted and is regenerable from the papers, so a
dangling link costs nothing and is reported rather than fatal.

    python link_pdfs.py            # build pdfs/, report coverage
    python link_pdfs.py --verify   # confirm each link resolves and matches its recorded sha256
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent
RECORDS = ROOT / "records"
PDFS = ROOT / "pdfs"
GITHUB = ROOT.parent

# Where each paper keeps its own store. The -NEW repositories own theirs; the predecessors
# either symlink forward or are on their way out.
STORES = [
    GITHUB / "mechanistic-validity-NEW2" / "reference",
    GITHUB / "mechanistic-views-NEW" / "reference",
    GITHUB / "mechanistic-reference-NEW" / "reference",
    GITHUB / "neural-geometry-reliability" / "reference",
    GITHUB / "epistatic-circuits" / "reference",
]


def index() -> dict[str, pathlib.Path]:
    """Every PDF any paper holds, by filename. First store wins on a name collision."""
    found: dict[str, pathlib.Path] = {}
    for s in STORES:
        if not s.exists():
            continue
        for f in s.rglob("*.pdf"):
            found.setdefault(f.name, f.resolve())
    return found


def sha256(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()

    have = index()
    linked = missing = mismatched = 0
    misses = []

    PDFS.mkdir(exist_ok=True)
    for p in sorted(RECORDS.glob("*.yaml")):
        r = yaml.safe_load(p.read_text()) or {}
        local = r.get("local")
        if not local:
            continue
        name = pathlib.Path(local).name
        src = have.get(name)
        if not src or not src.exists():
            missing += 1
            misses.append((r["slug"], name))
            continue
        link = PDFS / f"{r['slug']}.pdf"
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(src)
        linked += 1
        if a.verify and r.get("sha256"):
            if sha256(src) != r["sha256"]:
                mismatched += 1
                print(f"  HASH MISMATCH  {r['slug']}  {src}")

    print(f"  {len(have)} PDFs across {sum(1 for s in STORES if s.exists())} paper stores")
    print(f"  linked      {linked}")
    print(f"  named but not on disk  {missing}")
    if a.verify:
        print(f"  hash mismatches        {mismatched}")
    for slug, name in misses[:12]:
        print(f"    missing: {name}  (record {slug[:34]})")
    if len(misses) > 12:
        print(f"    ... and {len(misses) - 12} more")
    return 1 if mismatched else 0


if __name__ == "__main__":
    sys.exit(main())
