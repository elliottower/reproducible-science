"""The freeze a claim names, checked against the plans that were actually frozen.

`results claim --frozen-at <ref>` takes a git reference and uses its commit date to decide
whether an exposure to outcomes could have reached the plan. It verifies that the reference
resolves to a commit, and it cannot verify more than that: `results` never reads a
preregistration, so any commit in the repository is accepted. `prereg` records the freeze but
never reads the ledger, so it cannot see what a claim cited.

Neither tool can close that, and it does not need new data to close: `prereg freeze` already
writes the commit into the plan, as `**Status:** FROZEN at \\`<sha>\\``, and the ledger already
records what each claim named. Reading both is the whole check, and reading both is what the
umbrella is for.

What this does not do is decide whether the run a plan governs came after it. `repro.verify`
already answers that, through `_ordering`, entirely within this package's own manifest: it
reads `claim.confirmatory`, the runs that produced the claim's artifacts, and their
registration authority. It never reads a preregistration or a ledger, which is exactly the
seam left here. The two are complementary and neither subsumes the other.
"""

from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass

#: `prereg freeze` writes this line into the plan. The short form is what it records; a claim
#: may cite the same commit at any length, so comparison is on a common prefix.
FROZEN_AT = re.compile(r"^\*\*Status:\*\*\s*FROZEN at\s*`([0-9a-f]{7,40})`", re.M)

#: How much of two abbreviations must agree before they are the same commit. Git's own default
#: abbreviation is seven, and `prereg` writes twelve.
PREFIX = 7


@dataclass(frozen=True)
class Freeze:
    """A plan that has been frozen, and the commit it was frozen at."""

    path: pathlib.Path
    ref: str

    def matches(self, other: str) -> bool:
        n = min(len(self.ref), len(other), PREFIX) or PREFIX
        return bool(other) and self.ref[:n].lower() == other[:n].lower()


#: The ledger field holding a claim's text. `results.record.claim` writes `claim`, and this
#: module read `claim_id` and `id` -- neither of which it has ever written -- so every claim
#: in a real report rendered as `?`. The tests wrote `claim_id` too, so they agreed with the
#: reader and neither agreed with the writer.
CLAIM_TEXT = "claim"


@dataclass(frozen=True)
class Citation:
    """A claim in the ledger, and the freeze reference it named."""

    claim: str
    ref: str


def frozen_plans(root: pathlib.Path) -> list[Freeze]:
    """Every frozen plan under `root`, by reading the header `freeze` wrote.

    Markdown rather than a registry, because that is where the freeze lives: a repository
    pinning its registrations by a status line in the plan is the convention this follows
    rather than retrofitting a directory it would then have to keep in step.
    """
    out: list[Freeze] = []
    for md in sorted(root.rglob("*.md")):
        if any(part in {".git", "node_modules", ".venv"} for part in md.parts):
            continue
        try:
            found = FROZEN_AT.search(md.read_text(errors="replace"))
        except OSError:
            continue
        if found:
            out.append(Freeze(md, found.group(1)))
    return out


def cited_freezes(root: pathlib.Path) -> list[Citation]:
    """Every freeze reference named by a claim in the ledger."""
    ledger = root / ".results" / "ledger.jsonl"
    if not ledger.exists():
        return []
    out: list[Citation] = []
    for line in ledger.read_text(errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        ref = event.get("frozen_at")
        if event.get("event") == "claim" and ref:
            out.append(Citation(str(event.get(CLAIM_TEXT) or "(no text recorded)"), str(ref)))
    return out


def confirmatory_without_a_plan(root: pathlib.Path) -> list[str]:
    """Confirmatory claims in a project that has frozen no plan at all.

    `results` records that a claim is confirmatory; it has no way to ask whether anything was
    ever registered. `prereg` knows what was registered and never sees a claim. So a project
    can assert a confirmatory result, pass both tools, and hold no preregistration -- which is
    the exact arrangement preregistration exists to make visible.

    Reported, not failed. A plan frozen in another repository, or registered on OSF and pinned
    by a line this does not read, is a real arrangement and this cannot see it. What it can say
    is that nothing here records one.
    """
    if frozen_plans(root):
        return []
    ledger = root / ".results" / "ledger.jsonl"
    if not ledger.exists():
        return []
    out: list[str] = []
    for line in ledger.read_text(errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("event") == "claim" and event.get("confirmatory"):
            out.append(str(event.get(CLAIM_TEXT) or "(no text recorded)"))
    return out


def unmatched(root: pathlib.Path) -> list[Citation]:
    """Claims naming a freeze that no frozen plan under `root` records.

    A claim citing a commit that is not any plan's freeze is the failure this exists for: the
    reference resolves, `results` accepts it, and it stands for a registration that was never
    made. An empty list where there are no claims is not a pass, which is why the caller is
    given the citations as well and reports on having found none.
    """
    plans = frozen_plans(root)
    return [c for c in cited_freezes(root) if not any(p.matches(c.ref) for p in plans)]
