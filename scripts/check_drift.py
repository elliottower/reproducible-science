"""Regenerate every committed derived artifact and fail if the tree is not clean.

A derived artifact is a file in the repository produced by a script from other files in the
repository. Committing one means committing a claim: that running the generator today
reproduces it. Nothing checked that claim until this script existed, and the cost of not
checking showed up during the workspace migration -- `generate_figures.py` read its corpus
from a path that had moved, wrote an empty section, and dropped the paper's audit figures
while every test stayed green.

This generalizes that failure. A stale derived artifact is a defect whether it went stale
because a path moved, because a generator changed, or because someone edited the output by
hand.

    uv run python scripts/check_drift.py

Mutates the working tree by design: it runs the generators. Run it on a clean tree.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: Committed file -> the command that produces it, and the fields that legitimately differ
#: between runs. Order matters where one feeds another: the self-audit manifest pins the
#: figures, so the figures are regenerated first.
#:
#: A volatile field is one whose value is a fact about the run rather than about the content.
#: `provenance.commit` records HEAD, so it changes after every commit and would make this
#: check permanently red while saying nothing about whether the artifact is stale. Naming
#: the field keeps the comparison exact everywhere else, which dropping the check would not.
GENERATED: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("paper/figures.json", ("python", "scripts/generate_figures.py"), ()),
    (
        "paper/repro.yaml",
        ("python", "scripts/build_self_audit.py"),
        ("provenance.commit", "provenance.dirty"),
    ),
)


def load(text: str, name: str) -> object:
    return json.loads(text) if name.endswith(".json") else yaml.safe_load(text)


def without(document: object, volatile: tuple[str, ...]) -> object:
    """The document with each dotted path removed, so only content is compared."""
    for path in volatile:
        node = document
        *parents, last = path.split(".")
        for step in parents:
            node = node.get(step) if isinstance(node, dict) else None
            if node is None:
                break
        if isinstance(node, dict):
            node.pop(last, None)
    return document


def only_volatile_changed(path: str, volatile: tuple[str, ...]) -> bool:
    """True when the regenerated file differs from the committed one in volatile fields only."""
    if not volatile:
        return False
    committed = subprocess.run(
        ["git", "show", f"HEAD:{path}"], cwd=ROOT, capture_output=True, text=True
    )
    if committed.returncode != 0:
        return False
    try:
        before = without(load(committed.stdout, path), volatile)
        after = without(load((ROOT / path).read_text(), path), volatile)
    except (json.JSONDecodeError, yaml.YAMLError):
        return False
    return before == after


def dirty(paths: list[str]) -> list[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--", *paths], cwd=ROOT, capture_output=True, text=True
    )
    return [line[3:] for line in result.stdout.splitlines() if line.strip()]


def main() -> int:
    already = dirty([path for path, _, _ in GENERATED])
    if already:
        print("  refusing to run: these are already modified, so drift cannot be attributed")
        for path in already:
            print(f"    {path}")
        return 2

    for _, command, _ in GENERATED:
        built = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        if built.returncode != 0:
            print(f"  FAIL {' '.join(command)} exited {built.returncode}")
            print((built.stderr or built.stdout)[-1500:])
            return 1
        print(f"  ran {' '.join(command)}")

    drifted = dirty([path for path, _, _ in GENERATED])

    # A file differing only in a volatile field is not stale. Restore it so the tree is left
    # as it was found, and say which fields were ignored rather than ignoring them silently.
    volatile_only = [
        path
        for path, _, volatile in GENERATED
        if path in drifted and only_volatile_changed(path, volatile)
    ]
    if volatile_only:
        subprocess.run(["git", "checkout", "--", *volatile_only], cwd=ROOT, capture_output=True)
        for restored in volatile_only:
            fields = next(v for p, _, v in GENERATED if p == restored)
            print(f"  {restored}: unchanged except {', '.join(fields)} (restored)")
        drifted = [path for path in drifted if path not in volatile_only]

    if not drifted:
        print(f"  {len(GENERATED)} derived artifacts reproduce exactly")
        return 0

    print("\n  DRIFT: committed derived artifacts are not what their generators produce")
    for path in drifted:
        print(f"    {path}")
    print("\n  What changed:")
    subprocess.run(["git", "--no-pager", "diff", "--stat", "--", *drifted], cwd=ROOT)
    print("\n  Repair by committing the regenerated files:")
    print(f"    git add {' '.join(drifted)}")
    print("  Review the diff first. A generator that silently drops a section looks the same")
    print("  here as one that legitimately produced a new number.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
