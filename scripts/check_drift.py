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
import os
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
#: (committed file, command, volatile fields, external inputs it needs)
#:
#: The last element names inputs that live outside this repository. `figures.json` counts a
#: quotation corpus that spans seventeen manuscripts and a shared citations library, so it is
#: reproducible on a machine that has them and nowhere else. Where they are absent the file is
#: reported as unverifiable rather than skipped quietly -- an unchecked artifact that prints
#: nothing is the failure this script exists to prevent.
GENERATED: tuple[tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "paper/figures.json",
        ("python", "scripts/generate_figures.py"),
        (),
        ("$CITATIONS_HOME/enrichment.yaml",),
    ),
    (
        "paper/repro.yaml",
        ("python", "scripts/build_self_audit.py"),
        # All three are facts about the checkout rather than about the content: the commit
        # moves with every commit, `dirty` depends on the working tree, and the remote URL
        # differs between a local clone and a CI checkout of the same repository.
        ("provenance.commit", "provenance.dirty", "provenance.repository"),
        (),
    ),
)


def available(requires: tuple[str, ...]) -> list[str]:
    """External inputs that are not present, expanded from the environment."""
    missing = []
    for raw in requires:
        expanded = pathlib.Path(os.path.expandvars(raw)).expanduser()
        if "$" in str(expanded) or not expanded.exists():
            missing.append(raw)
    return missing


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
    # An already-modified derived file is not a reason to refuse. These are outputs: running
    # the generator overwrites them, and the question this asks is whether the regenerated
    # content matches what is committed, which is answered the same either way. Say so, since
    # a hand edit to a derived file is about to be discarded.
    already = dirty([path for path, _, _, _ in GENERATED])
    for path in already:
        print(f"  note {path} was already modified; regenerating overwrites it")

    unverifiable = []
    for path, command, _, requires in GENERATED:
        missing = available(requires)
        if missing:
            unverifiable.append((path, missing))
            print(f"  SKIP {path}: needs {', '.join(missing)}, not present here")
            continue
        built = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        if built.returncode != 0:
            print(f"  FAIL {' '.join(command)} exited {built.returncode}")
            print((built.stderr or built.stdout)[-1500:])
            return 1
        print(f"  ran {' '.join(command)}")

    drifted = dirty([path for path, _, _, _ in GENERATED])

    # A file differing only in a volatile field is not stale. Restore it so the tree is left
    # as it was found, and say which fields were ignored rather than ignoring them silently.
    volatile_only = [
        path
        for path, _, volatile, _ in GENERATED
        if path in drifted and only_volatile_changed(path, volatile)
    ]
    if volatile_only:
        subprocess.run(["git", "checkout", "--", *volatile_only], cwd=ROOT, capture_output=True)
        for restored in volatile_only:
            fields = next(v for p, _, v, _ in GENERATED if p == restored)
            print(f"  {restored}: unchanged except {', '.join(fields)} (restored)")
        drifted = [path for path in drifted if path not in volatile_only]

    if not drifted:
        checked = len(GENERATED) - len(unverifiable)
        print(f"  {checked} of {len(GENERATED)} derived artifacts reproduce exactly")
        if unverifiable:
            print(f"  {len(unverifiable)} could not be checked here for want of external inputs")
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
