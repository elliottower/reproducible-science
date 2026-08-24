"""Every digest a preregistration cites still names a file that hashes to it.

A registration pins the documents it depends on -- the codebook, the sampling frame, the
locator grammar -- by digest, so a reader can tell whether the plan they are reading is the
plan that was frozen. Nothing enforced that. A markdown formatter rewriting a codebook, or a
trailing-whitespace fix on a specification, breaks the pin silently, and the repair afterwards
is indistinguishable from tampering.

This walks every `experiments/*/PREREG.md`, collects the digests it cites, and checks each one
still matches a file. Read-only.

    uv run python scripts/check_pins.py
"""

from __future__ import annotations

import hashlib
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: A cited digest: sixteen or more hex characters inside backticks. Short enough to be
#: readable in prose, long enough that a collision is not the explanation for a match.
CITED = re.compile(r"`([0-9a-f]{16,64})`")


#: Where a cited digest may live. Anything a registration pins has to be reachable from here.
def candidates(experiment: pathlib.Path) -> list[pathlib.Path]:
    found = [p for p in experiment.rglob("*") if p.is_file() and p.name != "PREREG.md"]
    found += [ROOT / "docs" / "SPEC.md"]
    found += sorted((ROOT / "docs").glob("*.md"))
    return [p for p in found if p.is_file()]


def digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    experiments = sorted((ROOT / "experiments").glob("*/PREREG.md"))
    if not experiments:
        print("  no registrations to check")
        return 0

    failed = False
    for prereg in experiments:
        cited = sorted(set(CITED.findall(prereg.read_text())))
        if not cited:
            print(f"  {prereg.parent.name}: cites no digests")
            continue
        available = {p: digest(p) for p in candidates(prereg.parent)}
        for value in cited:
            match = next((p for p, d in available.items() if d.startswith(value)), None)
            if match:
                print(f"  ok    {prereg.parent.name}  {value[:16]}  {match.relative_to(ROOT)}")
            else:
                failed = True
                print(f"  STALE {prereg.parent.name}  {value[:16]}  matches no file")
    if failed:
        print("\n  A registration cites a digest nothing hashes to. Either a pinned document")
        print("  changed, or the registration cites something that is not in the repository.")
        print("  If the document changed deliberately, record it with `prereg log` and re-pin.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
