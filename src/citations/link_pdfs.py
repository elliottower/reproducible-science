"""Point pdfs/ at the real files, wherever the papers keep them.

The library owns no artifacts. Each paper keeps the PDFs it cites, and this builds a symlink
farm into them, named by record slug, so a hash check or a quote check can run against the
library without a second copy of 1.4 GB.

Symlinks are right here and wrong inside a paper repository. A paper has to be self-contained
-- it gets submitted, cloned, and built somewhere else, and a link into a sibling directory
breaks all three. The library is never submitted and is regenerable from the papers, so a
dangling link costs nothing and is reported rather than fatal.

Where the papers are is discovered, not hardcoded: every `reference/` directory beside the
library. `-NEW` repositories sort first, so when two of them hold a file under the same name
the current one wins. `--store` overrides discovery entirely.

    citations link             # build pdfs/, report coverage
    citations link --verify    # confirm each link resolves and matches its recorded sha256
"""
from __future__ import annotations

import argparse
import pathlib

from citations import paths
from citations.exceptions import CitationsError
from citations.models import load_record
from citations.verify import sha256


def discover_stores(library: pathlib.Path) -> list[pathlib.Path]:
    """Every `reference/` directory beside the library, current repositories first.

    Discovery rather than a hardcoded list: the list went stale the moment a repository was
    renamed, and a stale entry is silent -- it contributes no files and the run still reports
    a total.
    """
    parent = library.resolve().parent
    stores = [p / "reference" for p in sorted(parent.iterdir())
              if p.is_dir() and (p / "reference").is_dir()]
    # A `-NEW` repository supersedes its predecessor, and first store wins on a name
    # collision, so the current one has to be seen first.
    return sorted(stores, key=lambda s: ("-NEW" not in s.parent.name, s.parent.name))


def index(stores: list[pathlib.Path]) -> dict[str, pathlib.Path]:
    """Every PDF any paper holds, by filename. First store wins on a name collision."""
    found: dict[str, pathlib.Path] = {}
    for s in stores:
        if not s.is_dir():
            continue
        for f in s.rglob("*.pdf"):
            found.setdefault(f.name, f.resolve())
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="citations link", description=__doc__.split("\n")[0])
    ap.add_argument("--verify", action="store_true",
                    help="also confirm each linked file matches its recorded sha256")
    ap.add_argument("--store", action="append", default=[], metavar="DIR",
                    help="a directory of PDFs; repeatable. Overrides discovery")
    a = ap.parse_args(argv)

    try:
        library = paths.home()
    except CitationsError as e:
        print(str(e))
        return 2

    stores = ([pathlib.Path(s).expanduser().resolve() for s in a.store]
              if a.store else discover_stores(library))
    have = index(stores)

    # A run that found no artifacts cannot link any, and reporting `linked 0` as success is
    # how a broken store list looks exactly like a library with nothing to link.
    if not have:
        print(f"  no PDFs found in {len(stores)} store{'s' if len(stores) != 1 else ''}")
        for s in stores[:8]:
            print(f"    {s}")
        print("\n  name one explicitly:  citations link --store <dir>")
        return 2

    pdfs = paths.pdfs()
    pdfs.mkdir(exist_ok=True)
    linked = missing = mismatched = 0
    misses: list[tuple[str, str]] = []

    for p in sorted(paths.records().glob("*.yaml")):
        rec = load_record(p)
        if not rec.local:
            continue
        name = pathlib.Path(rec.local).name
        src = have.get(name)
        if not src or not src.exists():
            missing += 1
            misses.append((rec.slug, name))
            continue
        link = pdfs / f"{rec.slug}.pdf"
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(src)
        linked += 1
        if a.verify and rec.is_pinned and sha256(src) != rec.sha256.strip().lower():
            mismatched += 1
            print(f"  HASH MISMATCH  {rec.slug}  {src}")

    print(f"  {len(have)} PDFs across {sum(1 for s in stores if s.is_dir())} paper stores")
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
    raise SystemExit(main())
