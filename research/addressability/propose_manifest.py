"""Propose addresses for a manuscript's numbers by reading the code that produced them.

Searching a results tree for a printed value does not work: three significant figures cannot
distinguish one location among tens of thousands, and every candidate a search returns is as
likely wrong as right. The address has to come from somewhere else.

It comes from the analysis scripts. A script names the file it writes, and the file names the
quantities inside it. A manuscript row labelled `Cell-type CKA` and a JSON key `cka` are the
same name written twice, and matching those is a comparison between two labels rather than a
search for a number among many.

Three passes, strongest first:

1. **Script outputs.** Find every path an analysis script writes, and index the keys and
   columns of the files at those paths. These are results the repository produced on purpose.
2. **Label matching.** For a value printed beside a label in the manuscript, propose the
   addresses whose own name matches that label, and check the value at each.
3. **Value matching**, reported as weak. Only where the first two find nothing, and annotated
   with how many other locations hold the same value, so a reader can see it proves little.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "packages/results/src"))


SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv", ".ipynb_checkpoints"}

#: How an analysis script names a file it writes. Deliberately literal: a path assembled at
#: run time is not recoverable by reading, and guessing at one invents an address.
WRITES = [
    re.compile(r"""json\.dump\([^,]+,\s*open\(\s*["']([^"']+)["']""", re.S),
    re.compile(r"""to_csv\(\s*["']([^"']+\.[ct]sv)["']"""),
    re.compile(r"""to_json\(\s*["']([^"']+\.json)["']"""),
    re.compile(r"""open\(\s*["']([^"']+\.(?:json|csv|tsv|txt))["']\s*,\s*["']w"""),
    re.compile(r"""(?:OUTPUT_DIR|OUT_DIR|RESULTS_DIR|OUTDIR)\s*=\s*Path\(\s*["']([^"']+)["']"""),
    re.compile(r"""(?:OUTPUT|OUT|RESULTS)\s*=\s*["']([^"']+\.(?:json|csv))["']"""),
]


#: A label in the manuscript reduced to what a key or column would share with it.
def fold(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def script_outputs(root: pathlib.Path) -> dict[str, list[str]]:
    """Paths each analysis script names as somewhere it writes."""
    found: dict[str, list[str]] = {}
    for path in root.rglob("*.py"):
        if SKIP & set(path.parts):
            continue
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        paths = []
        for pattern in WRITES:
            paths += [m.group(1) for m in pattern.finditer(text)]
        if paths:
            found[str(path.relative_to(root))] = sorted(set(paths))
    return found


def leaves(obj, prefix: str = ""):
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield from leaves(value, f"{prefix}/{key}")
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            yield from leaves(value, f"{prefix}/{i}")
    else:
        yield prefix, obj


def addressable(path: pathlib.Path) -> list[tuple[str, float]]:
    """Every numeric leaf in a result file, as (JSON Pointer or column, value)."""
    out: list[tuple[str, float]] = []
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return out
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(text)
        except ValueError:
            return out
        for pointer, value in leaves(data):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                out.append((pointer, float(value)))
    elif path.suffix.lower() in {".csv", ".tsv"}:
        delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
        try:
            rows = list(csv.DictReader(io.StringIO(text), delimiter=delimiter))
        except (csv.Error, ValueError):
            return out
        for i, row in enumerate(rows[:5000]):
            for column, cell in row.items():
                if column is None or cell is None:
                    continue
                try:
                    out.append((f"[{i}]/{column}", float(cell)))
                except ValueError:
                    continue
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo")
    parser.add_argument("manuscript", nargs="?")
    parser.add_argument("--show", type=int, default=12)
    args = parser.parse_args()

    root = pathlib.Path(args.repo).expanduser().resolve()
    scripts = script_outputs(root)
    declared = sorted({p for paths in scripts.values() for p in paths})

    print(f"\n  {root.name}")
    print(f"    {len(scripts)} scripts name {len(declared)} output paths\n")
    for script, paths in sorted(scripts.items())[: args.show]:
        print(f"      {script}")
        for p in paths[:3]:
            exists = (root / p).exists()
            print(f"          -> {p}{'' if exists else '   (not on disk)'}")
    if len(scripts) > args.show:
        print(f"      ... {len(scripts) - args.show} more scripts")

    on_disk = [root / p for p in declared if (root / p).is_file()]
    total = sum(len(addressable(p)) for p in on_disk)
    print(
        f"\n    {len(on_disk)} of {len(declared)} declared outputs are on disk, "
        f"holding {total:,} addressable values"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
