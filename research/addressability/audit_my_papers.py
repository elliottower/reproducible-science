"""Which numbers in a manuscript do not appear in the result files beside it.

An internal check, not a measurement. It reads the newest manuscript in a repository, indexes
every readable result file, and lists the printed values it cannot find. The point is to look
at each one and decide whether the paper is wrong, the file is stale, or the number was never
stored -- not to produce a rate.

Only values with four or more constraining digits are reported. A shorter number matches
something in an artifact of any size, so its absence is informative and its presence is not:
finding `0.42` proves nothing, while failing to find `0.9489` is worth a look.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "packages/results/src"))

from results.manuscript import NUMBER, body, constraining_digits, needs_no_claim

READABLE = {
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
    ".md",
    ".html",
}
SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv", ".ipynb_checkpoints"}

#: Directories holding other people's manuscripts, or copies of one's own kept for
#: comparison. Picking a file from one of these audits the wrong paper: on one repository the
#: newest `.tex` was a reference copy of a different project entirely.
NOT_OURS = {
    "reference",
    "prior_art",
    "related",
    "submissions_old",
    "retired",
    "archive",
    "backup",
    "old",
    "perplexity_review",
    "reviews",
}

#: A value matches by coincidence when the artifact holds more distinct numbers than the
#: value can distinguish. With `N` values indexed, a `d`-digit number collides with
#: probability about `N / 10**d`, so the floor has to move with the repository rather than
#: being fixed: four digits carry information against a 2,000-value index and none at all
#: against 77,000, where every four-digit number matches something.
MAX_COINCIDENCE = 0.02


def digits_needed(index_size: int) -> int:
    """Constraining digits a value needs before its presence is worth reporting."""
    digits = 4
    while digits < 12 and index_size / 10**digits > MAX_COINCIDENCE:
        digits += 1
    return digits


MAX_BYTES = 40_000_000


def newest_manuscript(root: pathlib.Path) -> pathlib.Path | None:
    """The manuscript with the highest version suffix, or the largest if none are versioned."""
    candidates = [
        p
        for p in root.rglob("*.tex")
        if not SKIP & set(p.parts)
        and not NOT_OURS & {q.lower() for q in p.parts}
        and r"\begin{document}" in p.read_text(errors="replace")[:200_000]
    ]
    if not candidates:
        return None

    def key(path: pathlib.Path) -> tuple[int, int]:
        versions = re.findall(r"_v(\d+)", path.name)
        return (int(versions[-1]) if versions else -1, path.stat().st_size)

    return max(candidates, key=key)


def result_index(root: pathlib.Path) -> tuple[dict[str, str], int]:
    """Every numeric string in the repository's readable files, mapped to where it was seen."""
    index: dict[str, str] = {}
    read = 0
    for path in root.rglob("*"):
        if not path.is_file() or SKIP & set(path.parts):
            continue
        if path.suffix.lower() not in READABLE or path.suffix.lower() == ".tex":
            continue
        try:
            if path.stat().st_size > MAX_BYTES:
                continue
            text = path.read_text(errors="replace")
        except OSError:
            continue
        read += 1
        for match in NUMBER.finditer(text):
            index.setdefault(match.group(0), str(path.relative_to(root)))
    return index, read


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo")
    parser.add_argument("--show", type=int, default=14)
    args = parser.parse_args()

    root = pathlib.Path(args.repo).expanduser().resolve()
    paper = newest_manuscript(root)
    if paper is None:
        print(f"  {root.name}: no manuscript with a document body")
        return 0

    index, files = result_index(root)
    floor = digits_needed(len(index))
    printed = []
    for line, cited, source, lineno in body(paper.read_text(errors="replace"), paper):
        for match in NUMBER.finditer(line):
            value = match.group(0)
            if needs_no_claim(value, line, match.start()) is not None:
                continue
            if constraining_digits(value) < floor or cited:
                continue
            printed.append(
                {
                    "value": value,
                    "line": lineno,
                    "source": source,
                    "context": line.strip()[:96],
                    "found": value in index,
                }
            )

    missing = [p for p in printed if not p["found"]]
    found = len(printed) - len(missing)
    print(f"\n  {root.name}")
    print(f"    {paper.relative_to(root)}")
    print(f"    {files} readable files indexed, {len(index):,} distinct values")
    print(
        f"    reporting values with {floor}+ constraining digits "
        f"(coincidence below {MAX_COINCIDENCE:.0%} at that width)"
    )
    if not printed:
        print(f"    no values with {floor} or more constraining digits")
        return 0
    print(
        f"    {len(printed)} checkable values in the manuscript: "
        f"{found} present, {len(missing)} absent\n"
    )
    for entry in missing[: args.show]:
        print(f"      {entry['value']:>12}  {entry['source']}:{entry['line']}")
        print(f"                    {entry['context']}")
    if len(missing) > args.show:
        print(f"      ... {len(missing) - args.show} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
