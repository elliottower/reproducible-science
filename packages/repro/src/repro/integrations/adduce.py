"""An adduce rule that runs `repro verify` and reports what it found.

**Why one finding and not many.** `adduce.rules.Rule.evaluate` returns a single `Finding` per
repository. A manifest can declare thousands of assertions -- one corpus here holds 5,686
quotations -- so the per-assertion outcomes have nowhere to live in that interface. This rule
therefore reports an aggregate and writes the full typed report beside it, so nothing is lost
and the summary is still usable inside adduce's own report.

`PARTIAL` is the right status for the aggregate and would be wrong for any single assertion.
A quotation is present or absent; a set of them is partially verified. That is the difference
between a rule that summarizes many items and a check on one proposition, and it is why the
aggregate lives in this adapter rather than in the verification engine.
"""

from __future__ import annotations

import json
import pathlib

from adduce.rules import Category, Location, Rule, Status

from repro import load, verify
from repro.exceptions import ReproError
from repro.models import Outcome, Validity

MANIFEST = "repro.yaml"
SIDECAR = ".adduce/repro-report.json"

#: Directories whose manifests describe fixtures rather than the project. A repository that
#: tests a verifier contains manifests by construction, and auditing one of those reports on
#: the fixture instead of on the work.
FIXTURE_DIRS = ("test", "tests", "fixture", "fixtures", "example", "examples", "conformance")


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
            report = verify(load(manifest))
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
        locations = [Location(path=str(manifest.relative_to(root)))]
        if sidecar:
            locations.append(Location(path=str(sidecar.relative_to(root))))

        detail = ", ".join(f"{n} {k}" for k, n in sorted(counts.items()))
        if broken:
            return self.finding(
                Status.FAIL,
                1.0,
                f"{len(broken)} pinned artifact(s) changed since being declared: "
                f"{', '.join(broken[:3])}. {total} assertions checked ({detail}).",
                remediation="Re-run the analysis, or re-pin the artifacts deliberately.",
                locations=locations,
            )
        if absent:
            return self.finding(
                Status.FAIL,
                1.0,
                f"{len(absent)} declared artifact(s) are not present: "
                f"{', '.join(absent[:3])}. {total} assertions checked ({detail}).",
                remediation="Produce the artifacts, or drop the assertions that name them.",
                locations=locations,
            )
        # Confidence is 1.0 throughout: a byte comparison against a hashed artifact is not a
        # signal a rule is more or less sure of. Reporting anything lower would invite the
        # number to be read as strength of evidence, which it is not.
        unpinned = list(report.artifacts_with(Validity.UNPINNED_ARTIFACT))
        if verified == total and unpinned:
            # The rule's rationale is that assertions are checked byte for byte against
            # pinned artifacts. Where nothing is pinned, every assertion can hold against a
            # file that has changed since it was written, so this is not a pass.
            return self.finding(
                Status.PARTIAL,
                1.0,
                f"All {total} declared evidence assertions verify, but "
                f"{len(unpinned)} artifact(s) carry no digest: {', '.join(unpinned[:3])}. "
                f"They were checked against whatever is on disk.",
                remediation="Record a sha256 for each artifact so the check means something.",
                locations=locations,
            )
        if verified == total:
            return self.finding(
                Status.PASS,
                1.0,
                f"All {total} declared evidence assertions verify.",
                locations=locations,
            )
        if verified == 0:
            return self.finding(
                Status.FAIL,
                1.0,
                f"No declared evidence assertion verifies ({detail}).",
                remediation=f"Run `repro verify` and see {SIDECAR}.",
                locations=locations,
            )
        return self.finding(
            Status.PARTIAL,
            1.0,
            f"{verified} of {total} declared evidence assertions verify ({detail}).",
            remediation=f"Per-assertion outcomes are in {SIDECAR}.",
            locations=locations,
        )

    @staticmethod
    def _write_sidecar(root: pathlib.Path, report) -> pathlib.Path | None:
        """The full typed report, since one Finding cannot carry per-assertion outcomes."""
        out = root / SIDECAR
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report.model_dump(mode="json"), indent=2) + "\n")
        except OSError:
            return None
        return out


RULES = [ReproEvidenceRule]
