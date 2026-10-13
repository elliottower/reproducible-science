"""`repro ci`: the checks as one line of a workflow each, with a summary on the run page.

    repro ci claims    what `repro verify` checks, then what `repro stale` reports
    repro ci reruns    what `repro reproduce` runs
    repro ci init      write the workflows that run those, and print the README lines

Nothing is evaluated here that those three commands do not evaluate. `claims` calls
`repro.verify.verify` and `repro.stale.stale`, `reruns` calls `repro.reproduce.reproduce`, the
policy grades each as it does there, and the text printed is the text those commands print.
What this adds is a Markdown summary appended to the file `GITHUB_STEP_SUMMARY` names, which
GitHub shows on the page of the run.

`init` writes one workflow per check, each named for that check, because GitHub's badge is
per workflow and prints the workflow's name beside `passing`. A name that called the study
reproducible would say more than a job that compares printed values with files can establish.

The summaries are pure functions of the report models. Reaches no network.
"""

from __future__ import annotations

import argparse
import collections
import os
import pathlib
import re
import shlex
from collections.abc import Callable

from provenance_core import atomic_write
from provenance_core.gitref import try_run
from pydantic import BaseModel, ConfigDict

from repro import __version__
from repro.exceptions import ReproError
from repro.manifest import DEFAULT_NAME, find, load
from repro.models import (
    AssertionAccount,
    ClaimAccount,
    Freshness,
    Manifest,
    NumbersReport,
    Outcome,
    Reading,
    Reason,
    Regeneration,
    ReproductionReport,
    StalenessReport,
    Standing,
    Validity,
    VerificationReport,
)
from repro.numbers import NoTextError, numbers
from repro.policy import PROFILES, Assessment, Policy
from repro.reproduce import RECORD, append, reproduce
from repro.stale import reruns as recorded_reruns
from repro.stale import stale
from repro.verify import verify
from repro.why import why

#: The checks a workflow can run, in the order their badges are printed, and the name each
#: workflow takes: the word GitHub's badge prints beside `passing`. A name says which check
#: ran and nothing about the study.
CHECKS = ("claims", "reruns")
NAMES = {"claims": "claims", "reruns": "reruns"}

WORKFLOWS = pathlib.Path(".github") / "workflows"

#: The first line of every workflow `init` writes, and how it knows one of its own.
MARKER = "# Written by `repro ci init`."

#: Pinned by commit, with the release in a comment, as the workflows of this repository are.
#: `test_ci.py` holds these equal to the pins in `.github/workflows/claims.yml`.
CHECKOUT = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1  # v7.0.1"
SETUP_UV = "astral-sh/setup-uv@c18668ad3cf93ea998bef934396af7bb5c839dc7  # v10.2.0"

DISTRIBUTION = "reproducible-science"

WORKFLOW = """\
{marker} The workflow runs one command and is named for the check that
# command makes: https://reproducible.science/tools/repro/#in-ci
name: {name}

on:
  push:
    branches: [{branch}]
  pull_request:

permissions:
  contents: read

jobs:
  {job}:
    runs-on: ubuntu-latest
    steps:
      - uses: {checkout}
        with:
          persist-credentials: false
      - uses: {setup_uv}
{environment}      - run: uvx --from {distribution}=={version} {command}
"""

#: Where the reruns workflow installs what the project's commands need. A comment, because
#: only the project knows what that is.
ENVIRONMENT = """\
      # Install what this project's commands need here, before they are run again:
      # - run: uv sync
"""

#: Lines in each list of a summary. GitHub refuses a step summary over 1 MiB, and a manifest
#: can declare thousands of assertions.
MAX_LISTED = 20
#: Characters of one printed or stored value shown in a summary.
MAX_SHOWN = 80
#: Files shown for one assertion.
MAX_READS = 3

CLAIMS_SHOWS = (
    "What this checks: each declared value or passage is in the file the manifest names, at "
    "the address it declares, and each file matches its pin. It does not show that the "
    "analysis is right."
)
RERUNS_SHOWS = (
    "What this checks: each declared command was run again on this machine, and `reproduced` "
    "means every number the manuscript prints from its output still holds. Commands the "
    "manifest does not declare were not run."
)

_GITHUB = re.compile(r"github\.com[:/](?P<owner>[^/\s]+)/(?P<repo>[^/\s]+?)(?:\.git)?/?$")
_HEADING = re.compile(r"^#{1,6} ")
_PLAIN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._/-]*$")


class NotARepositoryError(ReproError):
    """`repro ci init` was run where git finds no repository."""

    def __init__(self, where: pathlib.Path) -> None:
        self.where = where
        super().__init__(
            f"{where} is not inside a git repository; nothing was written. A workflow lives "
            f"under {WORKFLOWS.as_posix()}/ at the top of one."
        )


class NoManifestError(ReproError):
    """The repository holds no manifest for a workflow to check."""

    def __init__(self, root: pathlib.Path) -> None:
        self.root = root
        super().__init__(
            f"no {DEFAULT_NAME} here or above, inside {root}; nothing was written. Write one "
            "that pins this project's result files:\n\n    repro manifest init"
        )


class WorkflowExistsError(ReproError):
    """A workflow is already where one would be written. Nothing is overwritten."""

    def __init__(self, ours: tuple[pathlib.Path, ...], foreign: tuple[pathlib.Path, ...]) -> None:
        self.ours = ours
        self.foreign = foreign
        said = []
        if foreign:
            said.append(
                f"{', '.join(str(path) for path in foreign)} exists and `repro ci init` did not "
                "write it. `--prefix repro-` writes beside it, under another file name."
            )
        if ours:
            said.append(
                f"{', '.join(str(path) for path in ours)} exists. `--force` replaces a workflow "
                "this command wrote."
            )
        super().__init__(" ".join(said) + " Nothing was written.")


class UnknownCheckError(ReproError):
    """`--name` named a check there is no workflow for."""

    def __init__(self, given: str) -> None:
        self.given = given
        super().__init__(
            f"--name takes CHECK=TEXT, where CHECK is one of {', '.join(CHECKS)}; got {given!r}"
        )


class NothingToRerunError(ReproError):
    """A reruns workflow was asked for and the manifest declares no command."""

    def __init__(self, path: pathlib.Path) -> None:
        self.path = path
        super().__init__(
            f"{path} declares no command, so a reruns workflow would have nothing to run; "
            "nothing was written. A record under `regenerations` names a command, the files "
            "it reads and the file it writes."
        )


class ReadmeError(ReproError):
    """`--readme` was given and the badge lines cannot be put in a README."""

    def __init__(self, detail: str) -> None:
        super().__init__(
            f"{detail}; nothing was written. Run without `--readme` and add the lines."
        )


class VersionUnknownError(ReproError):
    """The package is not installed, so there is no version for a workflow to pin."""

    def __init__(self) -> None:
        super().__init__(
            f"{DISTRIBUTION} is not installed, so there is no version for the workflow to pin; "
            "nothing was written."
        )


# ----------------------------------------------------------------------------------- reports


class ClaimsRun(BaseModel):
    """What `repro ci claims` found: the verifier's report and the staleness report, each with
    the policy's assessment of it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy: str
    verification: VerificationReport
    verified: Assessment
    not_verified: tuple[ClaimAccount, ...] = ()
    """The account `repro why` gives of each claim with an assertion that is not verified, for
    the first `MAX_LISTED` such assertions."""
    staleness: StalenessReport | None = None
    """None where the manifest declares no command."""
    fresh: Assessment | None = None
    last_rerun: ReproductionReport | None = None
    """The latest invocation in the record of re-runs. None where it holds none."""
    numbers: NumbersReport | None = None
    """What `repro numbers` counts in the manuscript's text. None where no claim reads its
    sentence from a text. Reported beside the assertions and never graded."""

    @property
    def passed(self) -> bool:
        return self.verified.passed and (self.fresh is None or self.fresh.passed)


class RerunsRun(BaseModel):
    """What `repro ci reruns` found."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy: str
    reproduction: ReproductionReport
    assessment: Assessment


def claims(manifest: Manifest, policy: Policy) -> ClaimsRun:
    """Verify the manifest and compare it with its record of re-runs. Executes nothing and
    writes nothing."""
    verification = verify(manifest)
    accounts, listed = [], 0
    for claim in verification.claims:
        failing = sum(d.outcome is not Outcome.VERIFIED for d in claim.decisions)
        if failing and listed < MAX_LISTED:
            accounts.append(why(manifest, claim.claim_id))
            listed += failing
    staleness = stale(manifest) if manifest.regenerations else None
    try:
        counted = numbers(manifest)
    except NoTextError:
        counted = None
    root = manifest.path.parent if manifest.path else pathlib.Path.cwd()
    log = recorded_reruns(root)
    return ClaimsRun(
        policy=policy.name,
        verification=verification,
        verified=policy.assess(verification),
        not_verified=tuple(accounts),
        staleness=staleness,
        fresh=policy.assess_staleness(staleness) if staleness else None,
        last_rerun=log[-1] if log else None,
        numbers=counted,
    )


# --------------------------------------------------------------------------------- summaries


def _said(value: str) -> str:
    return value.replace("_", " ")


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def _code(text: object) -> str:
    """A value as inline code, on one line and no longer than `MAX_SHOWN`."""
    flat = " ".join(str(text).split())
    shown = flat if len(flat) <= MAX_SHOWN else f"{flat[:MAX_SHOWN]}..."
    return f"`` {shown} ``" if "`" in shown else f"`{shown}`"


def _listed(lines: list[str]) -> list[str]:
    """At most `MAX_LISTED` lines, and how many were left out."""
    more = len(lines) - MAX_LISTED
    return [*lines[:MAX_LISTED], *([f"- and {more} more"] if more > 0 else [])]


def _verdict(command: str, policy: str, assessments: list[Assessment]) -> str:
    errors = sum(len(a.errors) for a in assessments)
    warnings = sum(len(a.warnings) for a in assessments)
    passed = all(a.passed for a in assessments)
    return (
        f"`{command}` under policy `{policy}`: **{'passed' if passed else 'FAILED'}** "
        f"({errors} errors, {warnings} warnings)"
    )


def _table(rows: list[tuple[str, str]]) -> list[str]:
    return [
        "| checked | found |",
        "|---|---|",
        *(f"| {label} | {found} |" for label, found in rows),
    ]


def _assertions_found(report: VerificationReport) -> str:
    outcomes = collections.Counter(d.outcome for d in report.decisions)
    total = len(report.decisions)
    found = f"{outcomes[Outcome.VERIFIED]} of {_count(total, 'assertion')} verified"
    for outcome in (Outcome.MISMATCH, Outcome.NOT_FOUND, Outcome.UNCHECKED, Outcome.ERROR):
        if outcomes[outcome]:
            found += f", {outcomes[outcome]} {_said(outcome.value)}"
    if unoffered := report.counts.get(Outcome.NOT_OFFERED.value, 0):
        found += f"; {unoffered} of {_count(len(report.claims), 'claim')} offer no evidence"
    # A warning qualifies an outcome and is not one, so it is counted beside them.
    warnings = collections.Counter(w.value for d in report.decisions for w in d.warnings)
    if warnings:
        found += "; warnings: " + ", ".join(
            f"{n} {_said(name)}" for name, n in sorted(warnings.items())
        )
    if ties := sum(d.tie is not None for d in report.decisions):
        found += f"; {ties} verified on an exact tie between two printed values"
    return found


def _numbers_found(report: NumbersReport | None) -> str:
    """Every number the text prints, by where it stands, as `repro numbers` closes on it. The
    assertions are the ones the author declared; this is the denominator the text gives."""
    if report is None:
        return "not counted: no claim reads its sentence from a text"
    counts, texts = report.counts, len(report.texts)
    return (
        f"{_count(len(report.numbers), 'number')} in {_count(texts, 'text')}: "
        f"{counts[Standing.BOUND]} bound, {counts[Standing.SET_ASIDE_BY_RULE]} set aside by "
        f"rule, {counts[Standing.SET_ASIDE_WITH_A_REASON]} set aside with a reason, "
        f"{counts[Standing.UNBOUND]} unbound"
    )


def _files_found(report: VerificationReport) -> str:
    states = collections.Counter(a.validity for a in report.artifacts)
    found = (
        f"{states[Validity.AUTHORITATIVE]} of {_count(len(report.artifacts), 'declared file')} "
        f"match their pins"
    )
    for validity, said in (
        (Validity.BROKEN_PIN, "not the pinned bytes"),
        (Validity.ARTIFACT_ABSENT, "absent"),
        (Validity.UNPINNED_ARTIFACT, "unpinned"),
    ):
        if states[validity]:
            found += f", {states[validity]} {said}"
    return found


def _reproduced(report: ReproductionReport) -> str:
    """`7 of 7 commands reproduced`, then each other outcome that occurred."""
    states = collections.Counter(s.state for s in report.regenerations)
    found = (
        f"{states[Regeneration.REPRODUCED]} of "
        f"{_count(len(report.regenerations), 'command')} reproduced"
    )
    for state, said in (
        (Regeneration.CHANGED, "changed"),
        (Regeneration.UNCHECKED, "unchecked"),
        (Regeneration.FAILED, "failed"),
        (Regeneration.NOT_RERUN, "not re-run"),
    ):
        if states[state]:
            found += f", {states[state]} {said}"
    return found


def _reruns_found(run: ClaimsRun) -> str:
    if run.staleness is None:
        return "no command is declared"
    if run.last_rerun is None:
        return f"not re-run in this job; `{RECORD.as_posix()}` holds no re-run"
    return (
        f"not re-run in this job; the last recorded re-run, started {run.last_rerun.started_at}: "
        f"{_reproduced(run.last_rerun)}"
    )


def _freshness_found(report: StalenessReport | None) -> str:
    """The count `repro stale` closes on, with its denominator."""
    if report is None:
        return "no command is declared, so no file has a recorded producer to compare it with"
    assertions = [assertion for claim in report.claims for assertion in claim.assertions]
    outside = (Freshness.NO_PRODUCER, Freshness.PARTLY_OUTSIDE)
    covered = collections.Counter(a.state for a in assertions if a.state not in outside)
    total = sum(covered.values())
    found = (
        f"{covered[Freshness.CURRENT]} current of {_count(total, 'assertion')} that "
        f"read{'s' if total == 1 else ''} a file with a recorded producer"
    )
    for state in (Freshness.STALE, Freshness.NEVER_RERUN, Freshness.UNDETERMINED):
        if covered[state]:
            found += f", {covered[state]} {_said(state.value)}"
    return found + f"; {len(assertions) - total} read files no command is recorded for"


def _assertion_said(claim_id: str, assertion: AssertionAccount) -> str:
    """One assertion that is not verified: what the manuscript prints, what each file holds
    at the declared address, and the outcome."""
    outcome = _said(assertion.outcome.value)
    if assertion.outcome is not Outcome.MISMATCH or assertion.reason is Reason.PLACES_MISMATCH:
        outcome += f" ({_said(assertion.reason.value)})"
    label = f"- `{claim_id}` {assertion.kind} {assertion.name}".rstrip()
    if assertion.kind == "quote":
        within = assertion.reads[0].path or assertion.reads[0].artifact if assertion.reads else ""
        return f"{label}: the passage {_code(assertion.printed)} in `{within}`: {outcome}"
    addressed = [read for read in assertion.reads if read.address]
    held = "; ".join(
        (f"{read.side}: " if read.side else "")
        + f"`{read.path or read.artifact}` at {_code(read.address)} "
        + (f"holds {_code(read.stored)}" if read.stored is not None else "holds no value read")
        + (
            f", {_code(read.converted)} {read.conversion.said}"
            if read.conversion is not None and read.converted is not None
            else ""
        )
        # An `aggregate` reads a value from every run it names.
        for read in addressed[:MAX_READS]
    )
    if len(addressed) > MAX_READS:
        held += f"; and {len(addressed) - MAX_READS} more"
    if assertion.statistic is not None and assertion.computed is not None:
        held += (
            f"; the {assertion.statistic.value} of the {len(assertion.reads)} values is "
            f"{_code(assertion.computed)}"
        )
    printed = (
        f"the manuscript prints {_code(assertion.printed)}; "
        if assertion.printed is not None
        else ""
    )
    return f"{label}: {printed}{held or 'no address was read'}: {outcome}"


def claims_summary(run: ClaimsRun) -> str:
    """The Markdown `repro ci claims` appends to a step summary."""
    report = run.verification
    lines = [
        f"## claims: {report.project}" if report.project else "## claims",
        "",
        _verdict(
            "repro ci claims", run.policy, [run.verified, *([run.fresh] if run.fresh else [])]
        ),
        "",
        *_table(
            [
                ("assertions", _assertions_found(report)),
                ("numbers in the manuscript", _numbers_found(run.numbers)),
                ("pinned files", _files_found(report)),
                ("re-runs", _reruns_found(run)),
                ("freshness", _freshness_found(run.staleness)),
            ]
        ),
    ]

    failing = [
        _assertion_said(account.claim_id, assertion)
        for account in run.not_verified
        for assertion in account.assertions
        if assertion.outcome is not Outcome.VERIFIED
    ][:MAX_LISTED]
    total = sum(d.outcome is not Outcome.VERIFIED for d in report.decisions)
    if failing:
        more = total - len(failing)
        lines += ["", "### Assertions not verified", "", *failing]
        lines += [f"- and {more} more"] if more > 0 else []

    files = [
        f"- `{a.artifact_id}`: not the pinned bytes: pinned `{(a.expected or '')[:12]}`, "
        f"found `{(a.actual or '')[:12]}`"
        if a.validity is Validity.BROKEN_PIN
        else f"- `{a.artifact_id}`: nothing at the declared path"
        for a in report.artifacts
        if a.validity in (Validity.BROKEN_PIN, Validity.ARTIFACT_ABSENT)
    ]
    if files:
        lines += ["", "### Files that do not match their pins", "", *_listed(files)]

    graded = (Freshness.STALE, Freshness.NEVER_RERUN, Freshness.UNDETERMINED)
    commands = [
        f"- `{node.artifact}`, written by `{node.id}`: {_said(node.state.value)}"
        + (
            f": upstream `{node.upstream}`"
            if node.upstream
            else "".join(f": {_said(cause.value)}" for cause in node.causes[:1])
        )
        for node in (run.staleness.regenerations if run.staleness else ())
        if node.state in graded
    ]
    if commands:
        lines += ["", "### Files not current with a recorded re-run", "", *_listed(commands)]

    return "\n".join([*lines, "", CLAIMS_SHOWS, ""])


def reruns_summary(run: RerunsRun) -> str:
    """The Markdown `repro ci reruns` appends to a step summary."""
    report = run.reproduction
    executed = [state for state in report.regenerations if state.executed]
    identical = sum(bool(state.bytes_identical) for state in executed)
    where = report.environment
    machine = ", ".join(
        part
        for part in (
            f"{where.system} {where.machine}".strip(),
            f"Python {where.python}" if where.python else "",
            f"{where.lockfile} `{where.lockfile_digest[:12]}`" if where.lockfile else "",
        )
        if part
    )
    lines = [
        f"## reruns: {report.project}" if report.project else "## reruns",
        "",
        _verdict("repro ci reruns", run.policy, [run.assessment]),
        "",
        *_table(
            [
                ("commands", _reproduced(report)),
                (
                    "bytes",
                    f"{identical} of {_count(len(executed), 'command')} that ran wrote the "
                    "pinned bytes",
                ),
                ("machine", machine),
            ]
        ),
    ]

    failing = []
    for state in report.regenerations:
        if state.state in (Regeneration.REPRODUCED, Regeneration.NOT_RERUN):
            continue
        moved = "; ".join(
            f"{claim.name}: {_code(claim.pinned)} then, {_code(claim.fresh)} now, the "
            f"manuscript prints {_code(claim.printed)}"
            for claim in state.claims
            if claim.reading is Reading.CHANGED
        )
        failing.append(
            f"- `{state.regeneration_id}`: {_said(state.state.value)}: "
            + (moved or _code(state.detail or _said(state.reason.value)))
        )
    if failing:
        lines += ["", "### Commands that did not reproduce", "", *_listed(failing)]

    return "\n".join([*lines, "", RERUNS_SHOWS, ""])


# --------------------------------------------------------------------------------- workflows


class Workflow(BaseModel):
    """One workflow `repro ci init` writes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    file: str
    name: str
    text: str

    def badge(self, slug: str) -> str:
        """The README line: GitHub's badge for this workflow, linked to its runs."""
        runs = f"https://github.com/{slug}/actions/workflows/{self.file}"
        return f"[![{self.name}]({runs}/badge.svg)]({runs})"


def _scalar(text: str) -> str:
    """A string as a YAML scalar, quoted only where it has to be."""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return text if _PLAIN.match(text) else f'"{escaped}"'


def workflow(
    check: str,
    command: str,
    *,
    name: str | None = None,
    prefix: str = "",
    branch: str = "main",
    environment: bool = False,
) -> Workflow:
    """The workflow that runs one `repro ci` command, pinned to the installed version of this
    package."""
    if __version__ == "0+unknown":
        raise VersionUnknownError
    return Workflow(
        file=f"{prefix}{check}.yml",
        name=name or NAMES[check],
        text=WORKFLOW.format(
            marker=MARKER,
            name=_scalar(name or NAMES[check]),
            branch=_scalar(branch),
            job=check,
            checkout=CHECKOUT,
            setup_uv=SETUP_UV,
            environment=ENVIRONMENT if environment else "",
            distribution=DISTRIBUTION,
            version=__version__,
            command=command,
        ),
    )


def repository(remote: str) -> str | None:
    """`OWNER/REPO` from a GitHub remote's URL, over https or ssh, or None for any other."""
    found = _GITHUB.search(remote.strip())
    return f"{found['owner']}/{found['repo']}" if found else None


def with_badges(readme: str, wanted: list[Workflow], slug: str) -> tuple[str, list[str]]:
    """A README with the badge of each workflow it does not already show, and the badges added.

    They go together on one line under the first heading, at the head of a block of badges
    where one is there. A README with no heading takes them at its top.
    """
    added = [
        flow.badge(slug)
        for flow in wanted
        if f"/actions/workflows/{flow.file}/badge.svg" not in readme
    ]
    if not added:
        return readme, []
    lines = readme.splitlines()
    at = next((i + 1 for i, line in enumerate(lines) if _HEADING.match(line)), 0)
    after = next((i for i in range(at, len(lines)) if lines[i].strip()), len(lines))
    if after < len(lines) and lines[after].startswith("[!["):
        lines[after:after] = [" ".join(added)]
    else:
        lines[at:at] = [*([""] if at else []), " ".join(added), *([] if at else [""])]
    return "\n".join(lines) + "\n", added


def init(
    cwd: pathlib.Path,
    *,
    reruns: bool = False,
    force: bool = False,
    readme: bool = False,
    prefix: str = "",
    names: dict[str, str] | None = None,
) -> int:
    """Write a workflow for each check into the repository holding `cwd`, and print the README
    lines."""
    top = try_run("rev-parse", "--show-toplevel", cwd=cwd)
    if not top:
        raise NotARepositoryError(cwd)
    root = pathlib.Path(top.strip()).resolve()
    path = find(cwd)
    if path is None or not path.is_relative_to(root):
        raise NoManifestError(root)
    if reruns and not load(path).regenerations:
        raise NothingToRerunError(path)

    # The workflow runs at the top of the checkout, so a manifest below the top is named.
    relative = path.relative_to(root).as_posix()
    named = "" if relative == DEFAULT_NAME else f" {shlex.quote(relative)}"
    head = try_run("symbolic-ref", "--short", "refs/remotes/origin/HEAD", cwd=root)
    branch = head.strip().removeprefix("origin/") if head else "main"
    chosen = [check for check in CHECKS if check != "reruns" or reruns]
    wanted = [
        workflow(
            check,
            f"repro ci {check}{named}",
            name=(names or {}).get(check),
            prefix=prefix,
            branch=branch,
            environment=check == "reruns",
        )
        for check in chosen
    ]

    there = [root / WORKFLOWS / flow.file for flow in wanted]
    ours = tuple(
        target
        for target in there
        if target.exists() and target.read_text(encoding="utf-8").startswith(MARKER)
    )
    foreign = tuple(target for target in there if target.exists() and target not in ours)
    if foreign or (ours and not force):
        raise WorkflowExistsError(() if force else ours, foreign)
    slug = repository(try_run("remote", "get-url", "origin", cwd=root) or "")
    target = root / "README.md"
    if readme and slug is None:
        raise ReadmeError("`git remote get-url origin` names no GitHub repository")
    if readme and not target.is_file():
        raise ReadmeError(f"no README.md at {root}")

    (root / WORKFLOWS).mkdir(parents=True, exist_ok=True)
    for flow in wanted:
        atomic_write(root / WORKFLOWS / flow.file, flow.text)
        print(f"wrote {root / WORKFLOWS / flow.file}")
        print(f"  name: {flow.name}")
        print(f"  runs: {flow.text.rstrip().splitlines()[-1].split('run: ', 1)[1]}")
    print(f"  on a push to {branch} and on every pull request")
    if reruns:
        print(
            f"  edit {(WORKFLOWS / wanted[-1].file).as_posix()} to install what the commands need"
        )

    if readme and slug:
        text, added = with_badges(target.read_text(encoding="utf-8"), wanted, slug)
        print("\nREADME.md")
        if added:
            atomic_write(target, text)
            print(f"  + {' '.join(added)}")
        else:
            print("  already shows each badge; nothing was added")
    else:
        print("\nadd to your README:\n")
        print("\n".join(flow.badge(slug or "OWNER/REPO") for flow in wanted))
        if slug is None:
            print("\nOWNER/REPO: `git remote get-url origin` names no GitHub repository.")
    print("\nnext: commit and push. Each badge prints its workflow's name beside `passing` or")
    print("`failing`, for the latest run on the default branch.")
    return 0


# ---------------------------------------------------------------------------------- commands

#: The text `repro verify`, `repro reproduce` and `repro stale` print, which `repro.cli` owns.
Shown = Callable[..., None]


def _manifest(args: argparse.Namespace) -> pathlib.Path | None:
    path = pathlib.Path(args.manifest) if args.manifest else find()
    if path is None:
        print(f"no {DEFAULT_NAME} here or above.\n")
        print("write one that pins this project's result files, with example claims to edit:\n")
        print("    repro manifest init")
    return path


def _summarize(args: argparse.Namespace, markdown: str) -> None:
    """Append to the summary file, where one is named. A step summary is shared by every
    command of the step, so it is never replaced."""
    target = args.summary or os.environ.get("GITHUB_STEP_SUMMARY")
    if not target:
        return
    with pathlib.Path(target).open("a", encoding="utf-8") as handle:
        handle.write(markdown + "\n")


def command_claims(args: argparse.Namespace, verify_text: Shown, stale_text: Shown) -> int:
    path = _manifest(args)
    if path is None:
        return 2
    policy = PROFILES[args.policy]
    run = claims(load(path), policy)
    verify_text(path, run.verification, policy, run.verified)
    print()
    if run.staleness is None or run.fresh is None:
        print("  no command is declared, so no file has a recorded producer to compare it with.")
    else:
        stale_text(path, run.staleness, policy, run.fresh)
    _summarize(args, claims_summary(run))
    return 0 if run.passed else 1


def command_reruns(args: argparse.Namespace, reproduce_text: Shown) -> int:
    path = _manifest(args)
    if path is None:
        return 2
    manifest = load(path)
    if not manifest.regenerations:
        print(f"{path}\n")
        print("  no command is declared, so there is nothing to run again. A record under")
        print("  `regenerations` names a command, the files it reads and the file it writes.")
        return 2
    policy = PROFILES[args.policy]
    report = reproduce(manifest, only=tuple(args.only or ()), skip=tuple(args.skip or ()))
    assessment = policy.assess_reproduction(report)
    recorded = append(report, path.resolve().parent)
    reproduce_text(path, report, policy, assessment, recorded)
    _summarize(
        args,
        reruns_summary(RerunsRun(policy=policy.name, reproduction=report, assessment=assessment)),
    )
    return 0 if assessment.passed else 1


def command_init(args: argparse.Namespace) -> int:
    names = {}
    for given in args.name or ():
        check, sep, text = given.partition("=")
        if not sep or check not in CHECKS or not text.strip():
            raise UnknownCheckError(given)
        names[check] = text.strip()
    return init(
        pathlib.Path.cwd(),
        reruns=args.reruns,
        force=args.force,
        readme=args.readme,
        prefix=args.prefix,
        names=names,
    )


def add_parser(
    sub: argparse._SubParsersAction, *, verify: Shown, reproduce: Shown, stale: Shown
) -> None:
    p = sub.add_parser(
        "ci",
        help="run the checks in a workflow, with a summary on the run page",
        description=(
            "The checks as one line of a workflow each. `claims` runs what `repro verify` and "
            "`repro stale` run, `reruns` runs what `repro reproduce` runs, and each appends a "
            "Markdown summary to the file GITHUB_STEP_SUMMARY names. `init` writes the "
            "workflows and prints the README lines."
        ),
    )
    p.set_defaults(func=lambda args: p.print_help() or 1)
    actions = p.add_subparsers(dest="action")

    def checks(name: str, text: str, description: str) -> argparse.ArgumentParser:
        made = actions.add_parser(name, help=text, description=description)
        made.add_argument("manifest", nargs="?", help=f"path to {DEFAULT_NAME}")
        made.add_argument("--policy", choices=sorted(PROFILES), default="publication")
        made.add_argument(
            "--summary",
            metavar="PATH",
            help="append the Markdown summary to this file (default: $GITHUB_STEP_SUMMARY)",
        )
        return made

    p_claims = checks(
        "claims",
        "check every assertion, then say which claims read a file changed since its re-run",
        "Run what `repro verify` runs, then what `repro stale` reports where the manifest "
        "declares a command. Executes nothing. Exits 1 where the policy fails either, 2 with "
        "no manifest, and 0 otherwise.",
    )
    p_claims.set_defaults(func=lambda args: command_claims(args, verify, stale))

    p_reruns = checks(
        "reruns",
        "run the declared commands again on this machine",
        f"Run what `repro reproduce` runs, and append the re-run to {RECORD.as_posix()} as it "
        "does. This executes what the manifest names. Exits 1 where the policy fails a "
        "re-run, 2 with no manifest or no command declared, and 0 otherwise.",
    )
    p_reruns.add_argument(
        "--only", action="append", metavar="ID", help="run this record; repeatable"
    )
    p_reruns.add_argument(
        "--skip", action="append", metavar="ID", help="leave this record out; repeatable"
    )
    p_reruns.set_defaults(func=lambda args: command_reruns(args, reproduce))

    p_init = actions.add_parser(
        "init",
        help="write the workflows and print the README lines",
        description=(
            f"Write {(WORKFLOWS / 'claims.yml').as_posix()}, which runs `repro ci claims` on a "
            "push to the default branch and on every pull request, and print the badge line "
            f"for the README. With --reruns, write {(WORKFLOWS / 'reruns.yml').as_posix()} as "
            "well, which runs `repro ci reruns`. Each workflow is named for its check. A "
            "workflow this command wrote is replaced only with --force, and any other file "
            "of that name is never replaced."
        ),
    )
    p_init.add_argument(
        "--reruns",
        action="store_true",
        help="also write the workflow that runs the declared commands again, for a project "
        "whose commands can run in CI",
    )
    p_init.add_argument(
        "--force", action="store_true", help="replace a workflow this command wrote"
    )
    p_init.add_argument(
        "--readme",
        action="store_true",
        help="put the badges on one line under the first heading of README.md",
    )
    p_init.add_argument(
        "--prefix",
        default="",
        metavar="TEXT",
        help="put this before each workflow's file name, as `repro-` gives repro-claims.yml",
    )
    p_init.add_argument(
        "--name",
        action="append",
        metavar="CHECK=TEXT",
        help="name a check's workflow, which is what its badge prints; repeatable "
        f"(default: {', '.join(f'{check}={NAMES[check]}' for check in CHECKS)})",
    )
    p_init.set_defaults(func=command_init)


__all__ = [
    "CHECKS",
    "NAMES",
    "ClaimsRun",
    "RerunsRun",
    "Workflow",
    "claims",
    "claims_summary",
    "init",
    "repository",
    "reruns_summary",
    "with_badges",
    "workflow",
]
