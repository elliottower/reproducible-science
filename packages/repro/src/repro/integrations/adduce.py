"""An adduce rule that runs `repro verify` and reports what it found.

**One finding, and one item per assertion.** `adduce.rules.Rule.evaluate` returns a single
`Finding` per repository, and adduce scores, weighs and suppresses findings. Since 0.2.0 a
finding carries `FindingItem`s, which adduce never scores on their own, so each checked
assertion is an item under the one finding: its status, the values compared, and the files
read, taken from the assertion's check record (`claims.record`). The finding's status and
weight are what they were. The full typed report is still written beside it.

`PARTIAL` is the right status for the aggregate and would be wrong for any single assertion.
A quotation is present or absent; a set of them is partially verified. So an item is never
`PARTIAL`: it is `PASS` where its record's outcome is a match a consumer may act on, `FAIL`
where the comparison ran and differed or the address held no value, and `UNKNOWN` where
nothing was compared or the tool failed.

adduce states an envelope of 10,000 items per finding. A manifest with more assertions than
that reports the first 10,000, in the order the manifest declares them, and says how many more
the sidecar holds.
"""

from __future__ import annotations

import json
import pathlib
import posixpath
import shlex

from adduce.rules import Category, Finding, FindingItem, Location, Rule, Status
from claims.exceptions import ReproError
from claims.models import Outcome, Validity
from claims.record import ExportRecord, NormalizedOutcome, check_records, read_outcome
from provenance_core import atomic_write

from repro import load, verify

MANIFEST = "repro.yaml"
SIDECAR = ".adduce/repro-report.json"

#: The most items one finding carries: the envelope adduce states for a finding's children.
MAX_ITEMS = 10_000

#: Directories whose manifests describe fixtures rather than the project. A repository that
#: tests a verifier contains manifests by construction, and auditing one of those reports on
#: the fixture instead of on the work.
FIXTURE_DIRS = ("test", "tests", "fixture", "fixtures", "example", "examples", "conformance")

#: An item's status for each outcome a consumer may act on. A record's outcome is read through
#: `read_outcome`, so a match this version does not understand, or one on an assertion nobody
#: declared, arrives as `not-checked`.
ITEM_STATUS: dict[NormalizedOutcome, Status] = {
    NormalizedOutcome.MATCH: Status.PASS,
    NormalizedOutcome.MISMATCH: Status.FAIL,
    NormalizedOutcome.NOT_FOUND: Status.FAIL,
    NormalizedOutcome.NOT_CHECKED: Status.UNKNOWN,
    NormalizedOutcome.ERROR: Status.UNKNOWN,
}


def candidates(repo) -> list[str]:
    """Manifests that plausibly describe this project, root first.

    A manifest at the root is taken as authoritative and ends the search. Otherwise every
    manifest outside a fixture directory is returned, and more than one is reported rather
    than resolved -- which of several manifests describes a project is a question for its
    author.
    """
    if repo.exists(MANIFEST):
        return [MANIFEST]
    out = []
    # find_names matches the basename exactly, so a file merely ending in the manifest name
    # -- other-repro.yaml, repro.yaml.bak -- is not mistaken for one.
    for entry in repo.find_names(MANIFEST):
        rel = pathlib.PurePosixPath(str(entry.path))
        if any(part.lower() in FIXTURE_DIRS for part in rel.parts[:-1]):
            continue
        out.append(str(rel))
    return sorted(out)


def item_id(record: ExportRecord) -> str:
    """The claim, the assertion's kind and name, and which of that kind and name it is: the
    identity an assertion keeps when others are added or reordered.

    Joined by `/`, each part escaped as an RFC 6901 pointer escapes a key, so a `/` inside a
    claim id or a name cannot make two assertions one id.
    """
    assertion = record.assertion
    parts = (record.claim.id, assertion.kind, assertion.name, str(assertion.position))
    return "/".join(part.replace("~", "~0").replace("/", "~1") for part in parts)


def _attributes(record: ExportRecord) -> dict[str, str | int | None]:
    """The values compared and the rule they were compared under, as JSON scalars. A value
    read from one file is `stored`; from several, `stored.<side or member index>`."""
    attributes: dict[str, str | int | None] = {
        "outcome": record.outcome.value,
        "native_outcome": record.native_outcome,
        "printed": record.printed,
    }
    if record.comparison is not None:
        attributes["mode"] = record.comparison.mode.value
        attributes["places"] = record.comparison.places
        attributes["computed"] = record.comparison.computed
    for index, read in enumerate(record.reads):
        suffix = "" if len(record.reads) == 1 else f".{read.side or index}"
        attributes[f"stored{suffix}"] = read.stored
        attributes[f"converted{suffix}"] = read.converted
        attributes[f"validity{suffix}"] = read.validity.value if read.validity else None
    return attributes


def to_item(record: ExportRecord, manifest: str) -> FindingItem:
    """One checked assertion as an adduce item. `manifest` is the manifest's path from the
    repository root, and each file read is located from there too. The command an item names
    is run from the root."""
    status = ITEM_STATUS[read_outcome(record)]
    here = posixpath.dirname(manifest)
    locations = [Location(path=manifest, line=record.assertion.line)]
    for read in record.reads:
        if read.path and not pathlib.PurePosixPath(read.path).is_absolute():
            locations.append(Location(path=posixpath.normpath(posixpath.join(here, read.path))))
    named = "" if manifest == MANIFEST else f" {shlex.quote(manifest)}"
    return FindingItem(
        id=item_id(record),
        status=status,
        message=": ".join(part for part in (record.native_reason, record.detail) if part),
        # A comparison of bytes is not an estimate, as for the finding.
        confidence=1.0,
        locations=tuple(dict.fromkeys(locations)),
        remediation=""
        if status is Status.PASS
        else f"repro why {shlex.quote(record.claim.id)}{named}",
        kind=record.check_type.value,
        attributes=_attributes(record),
    )


class ReproEvidenceRule(Rule):
    """Every declared evidence assertion holds against the artifact it names."""

    id = "R-REPRO-001"
    category = Category.DRIFT
    title = "Declared evidence assertions verify"
    rationale = (
        "A paper's reported values and quotations can be declared as assertions about pinned "
        "artifacts and checked byte for byte. Where a repository declares them, they should "
        "hold."
    )
    weight = 5
    severity = "high"
    fix_command = "repro verify"

    def applies_to(self, repo) -> bool:
        # Gate on a manifest existing. A repository that declares no assertions is not failing
        # this rule; it is outside its scope, and adduce excludes inapplicable rules from
        # scoring rather than counting them as passes.
        return bool(candidates(repo))

    def evaluate(self, ev):
        root = pathlib.Path(ev.repo.root)
        found = candidates(ev.repo)
        if not found:
            return self.finding(Status.NOT_APPLICABLE, 1.0, f"no {MANIFEST} found.")
        if len(found) > 1:
            # Taking the first would audit whichever manifest the file listing happened to
            # yield, which is how a repository with test fixtures gets scored on a fixture.
            listed = ", ".join(found[:4])
            return self.finding(
                Status.UNKNOWN,
                1.0,
                f"{len(found)} manifests found and none at the repository root: {listed}. "
                f"Which one describes this project is not something this rule should guess.",
                remediation=f"Put the project's manifest at {MANIFEST} in the root.",
            )
        manifest = root / found[0]

        try:
            loaded = load(manifest)
            report = verify(loaded)
            # The items state the report's decisions; nothing is checked twice.
            records = check_records(loaded, verified=report)
        except ReproError as e:
            # A verifier that could not run has found nothing about this repository. Reporting
            # it as a failure would blame the repository for a missing toolchain.
            return self.finding(
                Status.UNKNOWN,
                1.0,
                f"{MANIFEST} could not be verified: {e}",
                remediation="Install repro's extraction dependencies.",
            )

        counts = report.counts
        total = sum(counts.values())
        verified = counts.get(Outcome.VERIFIED.value, 0)
        broken = list(report.artifacts_with(Validity.BROKEN_PIN))
        absent = list(report.artifacts_with(Validity.ARTIFACT_ABSENT))

        if total == 0:
            # Nothing was declared, so nothing failed to verify. This precedes the artifact
            # checks: a rule about whether declared assertions hold has no finding to report
            # when a manifest declares none, whatever state its artifacts are in.
            return self.finding(
                Status.NOT_APPLICABLE, 1.0, f"{MANIFEST} declares no evidence assertions."
            )

        sidecar = self._write_sidecar(root, report)
        locations = [Location(path=found[0])]
        if sidecar:
            locations.append(Location(path=str(sidecar.relative_to(root))))
        items = tuple(to_item(record, found[0]) for record in records[:MAX_ITEMS])
        # Said in every message, so a reader of a finding with fewer items than assertions
        # knows where the rest are.
        rest = (
            f" The first {MAX_ITEMS} assertions are items; {len(records) - MAX_ITEMS} more are "
            f"in {SIDECAR}."
            if len(records) > MAX_ITEMS
            else ""
        )

        def finding(status: Status, message: str, remediation: str = "") -> Finding:
            return self.finding(
                status, 1.0, message + rest, remediation, locations=locations, items=items
            )

        detail = ", ".join(f"{n} {k}" for k, n in sorted(counts.items()))
        if broken:
            return finding(
                Status.FAIL,
                f"{len(broken)} pinned artifact(s) changed since being declared: "
                f"{', '.join(broken[:3])}. {total} assertions checked ({detail}).",
                remediation="Re-run the analysis, or re-pin the artifacts deliberately.",
            )
        if absent:
            return finding(
                Status.FAIL,
                f"{len(absent)} declared artifact(s) are not present: "
                f"{', '.join(absent[:3])}. {total} assertions checked ({detail}).",
                remediation="Produce the artifacts, or drop the assertions that name them.",
            )
        # Confidence is 1.0 throughout: a byte comparison against a hashed artifact is not a
        # signal a rule is more or less sure of. Reporting anything lower would invite the
        # number to be read as strength of evidence, which it is not.
        unpinned = list(report.artifacts_with(Validity.UNPINNED_ARTIFACT))
        if verified == total and unpinned:
            # The rule's rationale is that assertions are checked byte for byte against
            # pinned artifacts. Where nothing is pinned, every assertion can hold against a
            # file that has changed since it was written, so this is not a pass.
            return finding(
                Status.PARTIAL,
                f"All {total} declared evidence assertions verify, but "
                f"{len(unpinned)} artifact(s) carry no digest: {', '.join(unpinned[:3])}. "
                f"They were checked against whatever is on disk.",
                remediation="Record a sha256 for each artifact so the check means something.",
            )
        if verified == total:
            return finding(Status.PASS, f"All {total} declared evidence assertions verify.")
        if verified == 0:
            return finding(
                Status.FAIL,
                f"No declared evidence assertion verifies ({detail}).",
                remediation=f"Run `repro verify` and see {SIDECAR}.",
            )
        return finding(
            Status.PARTIAL,
            f"{verified} of {total} declared evidence assertions verify ({detail}).",
            remediation=f"Each assertion's outcome is an item of this finding, and in {SIDECAR}.",
        )

    @staticmethod
    def _write_sidecar(root: pathlib.Path, report) -> pathlib.Path | None:
        """The full typed report, which holds every assertion past the items' envelope and
        every claim that offers no evidence."""
        out = root / SIDECAR
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            # Atomically: a truncating write killed partway through leaves a sidecar that is
            # not JSON, and the host reads it on the next run.
            atomic_write(out, json.dumps(report.model_dump(mode="json"), indent=2) + "\n")
        except OSError:
            return None
        return out


RULES = [ReproEvidenceRule]
