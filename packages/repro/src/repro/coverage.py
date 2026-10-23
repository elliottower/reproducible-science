"""The manuscript's coverage: is every quotation it makes pinned, and every number bound to a run?

`citations verify` checks the quotations a claims file pins, and `results verify` the claims a
ledger records. Neither reads the manuscript, so a quotation added to the paper and never
pinned, or a number printed and never bound, passes both: nothing was checked, and the report
comes back clean. `citations coverage` and `results coverage` read the manuscript and say what
it holds that nothing pins or binds, and this is where `repro verify` runs them.

The manuscript is each text a claim reads its sentence from, as `repro numbers` finds it, or,
where no claim does, each declared artifact with a manuscript's suffix. Quotations are read
with `citations.coverage`, in this process; numbers with `results coverage --strict`, through
`repro.delegate`, because the verifier imports none of the ledger's code.

Graded by the policy's name, here and nowhere else: reported under `exploratory`, a warning
under `publication`, and a failure under `strict`. Nothing is failed by default, because an
unpinned quotation or an unbound number is an omission, not evidence of a wrong one.
"""

from __future__ import annotations

import pathlib
import re

from citations.coverage import cover, pinned_spans, quotations
from citations.exceptions import ClaimFileError
from citations.models import load_claim_file
from claims.models import Manifest
from claims.numbers import texts
from claims.policy import Severity, Violation
from pydantic import BaseModel, ConfigDict

from repro import audit
from repro.delegate import BY_NAME

#: What a manuscript is written in, where no claim names the text. `results coverage` reads
#: these and refuses a rendered PDF, which loses the structure that says what a number is.
MANUSCRIPT_SUFFIXES = (".tex", ".md", ".qmd", ".rst")

#: How each policy grades an uncovered quotation or an unbound number.
SEVERITY = {
    "exploratory": Severity.IGNORE,
    "publication": Severity.WARNING,
    "strict": Severity.ERROR,
}

#: The count `results coverage` prints of the numbers bound to nothing.
UNBOUND = re.compile(r"yours, bound to nothing\s+(\d+)")


class Quotation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    manuscript: str
    line: int
    text: str
    status: str
    """`covered`, `uncovered`, or `unresolvable` where it is too short to search for."""
    detail: str = ""


class Numbers(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    manuscript: str
    unbound: int | None
    """Numbers the manuscript prints that no ledger claim names. None where the count could
    not be read, which is said in `output`."""
    exit: int
    output: str = ""


class Coverage(BaseModel):
    """What the two coverage checks found, and how the policy grades it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    used: bool
    reason: str = ""
    manuscripts: tuple[str, ...] = ()
    quotations_read: bool = False
    """Whether the quotations were read: only where the project keeps a claims directory."""
    quotations: tuple[Quotation, ...] = ()
    """Every quotation the manuscript makes, where the project keeps a claims directory."""
    numbers: tuple[Numbers, ...] = ()
    """One per manuscript, where the project keeps a ledger."""
    violations: tuple[Violation, ...] = ()
    """Each finding, at the severity the policy gives it; IGNORE ones are kept, so another
    policy's grade can be read off the same findings."""

    @property
    def passed(self) -> bool | None:
        if not self.used:
            return None
        return not any(v.severity is Severity.ERROR for v in self.violations)

    def under(self, policy: str) -> tuple[Violation, ...]:
        """The same findings graded under another policy, with nothing run again."""
        severity = SEVERITY.get(policy, Severity.WARNING)
        return tuple(v.model_copy(update={"severity": severity}) for v in self.violations)


def manuscripts(manifest: Manifest) -> tuple[pathlib.Path, ...]:
    """The manuscript's files: the texts a claim reads its sentence from, or else every
    declared artifact with a manuscript's suffix."""
    named = texts(manifest)
    chosen = [a for a in manifest.artifacts if a.id in named] or [
        a for a in manifest.artifacts if a.path.suffix.lower() in MANUSCRIPT_SUFFIXES
    ]
    return tuple(p for a in chosen if (p := manifest.resolve(a)).is_file())


def _shown(path: pathlib.Path, root: pathlib.Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def _quotations(root: pathlib.Path, papers: tuple[pathlib.Path, ...]) -> tuple[Quotation, ...]:
    claims_dir = BY_NAME["citations"].data_dir(root)
    if claims_dir is None:
        return ()
    files = []
    for path in sorted(claims_dir.glob("*.yaml")):
        try:
            files.append(load_claim_file(path))
        except ClaimFileError:
            # `citations verify`, which runs beside this, reports a file it cannot read.
            continue
    pool = pinned_spans(files)
    return tuple(
        Quotation(
            manuscript=_shown(paper, root),
            line=found.quotation.line,
            text=found.quotation.raw.strip()[:200],
            status=found.status,
            detail=found.detail,
        )
        for paper in papers
        for found in (cover(q, pool) for q in quotations(paper.read_text(errors="replace")))
    )


def _numbers(root: pathlib.Path, papers: tuple[pathlib.Path, ...]) -> tuple[Numbers, ...]:
    if not (root / ".results").is_dir():
        return ()
    found = []
    for paper in papers:
        code, said = audit.run_step(
            ["results", "coverage", str(paper), "--strict"], root, BY_NAME["results"].entry()
        )
        counted = UNBOUND.search(said)
        # `--strict` exits 0 only where nothing is unbound; a manuscript with no number that
        # owes a run prints no count and exits 0.
        unbound = int(counted.group(1)) if counted else (0 if code == 0 else None)
        found.append(
            Numbers(
                manuscript=_shown(paper, root),
                unbound=unbound,
                exit=code,
                output=said.replace(f"{root}/", "").replace(str(root), "."),
            )
        )
    return tuple(found)


def coverage(
    root: pathlib.Path, manifest: Manifest | None, policy: str, limit: int | None = None
) -> Coverage:
    """Run both coverage checks over the manuscript and grade what they find under `policy`.
    With `limit`, more unbound numbers than that in a manuscript is an error under any policy,
    as `--max-unbound` says.

    Not used where there is no manifest, no manuscript, or neither a claims directory nor a
    ledger to cover it with.
    """
    if manifest is None:
        return Coverage(used=False, reason="no manifest names a manuscript")
    papers = manuscripts(manifest)
    if not papers:
        return Coverage(used=False, reason="the manifest declares no manuscript")
    pins = BY_NAME["citations"].data_dir(root) is not None
    if not pins and not (root / ".results").is_dir():
        return Coverage(
            used=False, reason="no claims directory and no ledger to cover the manuscript with"
        )
    quoted, counted = _quotations(root, papers), _numbers(root, papers)
    severity = SEVERITY.get(policy, Severity.WARNING)
    violations = [
        Violation(
            severity=severity,
            rule=f"coverage.quotation_{q.status}",
            subject=f"{q.manuscript}:{q.line}",
            detail=q.detail or "no pinned quote contains it",
        )
        for q in quoted
        if q.status != "covered"
    ]
    for n in counted:
        if n.unbound is None:
            violations.append(
                Violation(
                    severity=severity,
                    rule="coverage.numbers_unread",
                    subject=n.manuscript,
                    detail=f"`results coverage` exited {n.exit} and printed no count",
                )
            )
        elif n.unbound:
            over = limit is not None and n.unbound > limit
            violations.append(
                Violation(
                    severity=Severity.ERROR if over else severity,
                    rule="coverage.numbers_unbound",
                    subject=n.manuscript,
                    detail=f"{n.unbound} printed number(s) no ledger claim names"
                    + (f"; at most {limit} allowed" if limit is not None else ""),
                )
            )
    return Coverage(
        used=True,
        quotations_read=pins,
        manuscripts=tuple(_shown(p, root) for p in papers),
        quotations=quoted,
        numbers=counted,
        violations=tuple(violations),
    )


def lines(found: Coverage, policy: str) -> list[str]:
    """What `repro verify` prints of coverage, after the other sections."""
    if not found.used:
        return [f"  {'coverage':<12} not used here: {found.reason}"]
    word = "passed" if found.passed else "FAILED"
    errors = sum(v.severity is Severity.ERROR for v in found.violations)
    warnings = sum(v.severity is Severity.WARNING for v in found.violations)
    out = [
        f"  {'coverage':<12} {word} under policy {policy}  ({errors} errors, {warnings} warnings)"
    ]
    if found.quotations_read:
        covered = sum(q.status == "covered" for q in found.quotations)
        out.append(
            f"    quotations: {covered} of {len(found.quotations)} pinned"
            if found.quotations
            else "    quotations: none read in the manuscript"
        )
    for n in found.numbers:
        said = "could not be read" if n.unbound is None else f"{n.unbound} bound to no run"
        out.append(f"    numbers in {n.manuscript}: {said}")
    for v in found.violations:
        out.append(f"      {v.subject}  {v.rule.removeprefix('coverage.')}: {v.detail[:70]}")
    return out


__all__ = ["SEVERITY", "Coverage", "coverage", "lines", "manuscripts"]
