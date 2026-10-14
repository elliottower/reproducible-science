"""`repro ci`: the checks as one line of a workflow each, with a summary on the run page.

    repro ci prereg     what `prereg check` checks
    repro ci results    what `results verify --files` checks
    repro ci claims     what `repro verify` checks
    repro ci citations  what `citations verify --claims <dir>` checks
    repro ci reruns     what `repro stale` reports of each declared command, running none;
                        with `--run`, what `repro reproduce` runs
    repro ci init       write the workflows that run those, and print the README lines

Nothing is evaluated here that those commands do not evaluate. `claims` calls
`claims.verify.verify`, `reruns` calls `claims.stale.stale` and with `--run`
`repro.reproduce.reproduce`, and the policy grades each as it does there. `prereg`, `results` and `citations` run the tool's own
check in this process, found and pointed as `repro check` finds and points it, and read the
counts from the JSON the tool writes with `--json`. The text printed is the text those commands
print. What this adds is a Markdown summary appended to the file `GITHUB_STEP_SUMMARY` names,
which GitHub shows on the page of the run.

`init` writes one workflow per check, each named for that check, because GitHub's badge is
per workflow and prints the workflow's name beside `passing`. A name that called the study
reproducible would say more than a job that compares printed values with files can establish.

The summaries are pure functions of the report models. Reaches no network, except that
`citations --fetch-sources` runs `citations fetch` first.
"""

from __future__ import annotations

import argparse
import base64
import collections
import importlib.resources
import json
import os
import pathlib
import re
import shlex
import tempfile
import urllib.parse
from collections.abc import Callable

from claims.exceptions import ReproError
from claims.manifest import DEFAULT_NAME, find, load
from claims.models import (
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
    Witness,
)
from claims.numbers import NoTextError, numbers
from claims.policy import PROFILES, STRICT, Assessment, Policy
from claims.stale import reruns as recorded_reruns
from claims.stale import stale
from claims.starter import project_root
from claims.verify import verify
from claims.why import why
from provenance_core import atomic_write
from provenance_core.gitref import try_run
from pydantic import BaseModel, ConfigDict

from repro import __version__, audit
from repro.delegate import BY_NAME
from repro.reproduce import RECORD, append, reproduce

#: The checks a workflow can run, in the order their badges are printed, and the name each
#: workflow takes: the word GitHub's badge prints beside `passing`. A name says which check
#: ran and nothing about the study.
CHECKS = ("prereg", "results", "claims", "citations", "reruns")
NAMES = {
    "prereg": "prereg",
    "results": "results",
    "claims": "claims",
    "citations": "citations",
    "reruns": "reproduced",
}


class ToolCommand(BaseModel):
    """How `repro ci <tool>` reaches one tool: every name of that tool's that this module
    spells. The command itself is `repro.delegate`'s, which `repro check` also runs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    distribution: str
    """The PyPI distribution that provides the tool's command."""
    options: tuple[str, ...] = ()
    """Options added to the command `repro.delegate` gives for the tool."""
    report: str = "--json"
    """The option naming the file the tool writes its findings to, as JSON."""
    fetch: tuple[str, ...] = ()
    """The tool's command that fetches absent sources, where it has one."""

    def argv(self, tool: str, root: pathlib.Path) -> list[str]:
        """The tool's own command over the project at `root`, as a reader would type it."""
        return [tool, *BY_NAME[tool].argv_for(root), *self.options]

    def said(self, tool: str) -> str:
        """The command in a sentence, with no project to point it at."""
        found = BY_NAME[tool]
        pointed = (found.points_at, "<dir>") if found.points_at else ()
        return " ".join([tool, *found.check_argv, *pointed, *self.options])


#: The tools whose own command a workflow runs, in badge order.
TOOL_COMMANDS = {
    "prereg": ToolCommand(distribution=audit.DISTRIBUTIONS["prereg"]),
    "results": ToolCommand(distribution=audit.DISTRIBUTIONS["results"], options=("--files",)),
    "citations": ToolCommand(distribution=audit.DISTRIBUTIONS["citations"], fetch=("fetch",)),
}
TOOLS = tuple(TOOL_COMMANDS)
#: What `init` says of a repository that keeps no record for one.
NO_RECORD = {
    "prereg": "no PREREG.md and no .prereg/ here",
    "results": "no .results/ ledger here",
    "claims": f"no {DEFAULT_NAME} here or above",
    "citations": "no claims directory holding a claims file here",
    "reruns": f"{DEFAULT_NAME} declares no command",
}
NO_RERUN = (
    f"{RECORD.as_posix()} holds no re-run; run `repro reproduce` and commit {RECORD.as_posix()}"
)

#: What each check compares, in a few words, and the section of the documentation that says
#: what it means. A summary opens on these: a badge leads to the page of a run, and nothing on
#: that page says what the check is.
DOCS = "https://reproducible.science/tools/repro/"
ABOUT = {
    "prereg": "each frozen plan, its amendments and its log against the bytes that were frozen",
    "results": "the ledger's chain, and each recorded file against the hash recorded for it",
    "claims": (
        "the manuscript's printed values and quoted passages against the files they are "
        "declared to come from"
    ),
    "citations": "each quoted passage against the source its claims file pins",
    "reruns": "each declared command against the record of its re-runs",
}
ANCHORS = {check: f"{check}-in-ci" for check in CHECKS}

#: The label colour of a branded badge, which the white-on-dark icons are drawn for.
LABEL_COLOR = "24292f"
SHIELDS = "https://img.shields.io/github/actions/workflow/status"
#: Characters in a branded badge's address. shields.io documents no limit on a custom logo;
#: this keeps the address under what servers and Markdown renderers are known to accept.
MAX_BADGE_URL = 2000

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

#: `citations` reads a PDF with `pdftotext` first, and GitHub's Ubuntu runner image does not
#: list poppler-utils among its installed packages.
POPPLER = """\
      - run: sudo apt-get update && sudo apt-get install --yes poppler-utils
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
#: What the word on the reruns badge means, as `claims.models.Regeneration` defines it.
REPRODUCED = (
    "`reproduced` means a command was run again and every number the manuscript prints from "
    "its output still holds; whether the output had the same bytes is recorded beside it."
)
RERUNS_SHOWS = (
    "What this checks: each declared command was run again in this job. "
    + REPRODUCED
    + " Commands the manifest does not declare were not run."
)
RECORD_SHOWS = (
    "What this checks: for each declared command, the record holds a re-run that reproduced, "
    "made over the command and the input files as they are now, whose output is the file now "
    "here. The re-runs were recorded before this job, which read the record and ran no "
    "command; where each was recorded is what the record holds of it, in the table. "
    + REPRODUCED
    + " Commands the manifest does not declare were not run, and this does not show that a "
    "command would reproduce if run now."
)

SHOWS = {
    "prereg": (
        "What this checks: each frozen plan, its amendments and its log are the bytes that "
        "were frozen. It does not show that the study followed the plan."
    ),
    "results": (
        "What this checks: the ledger's chain is intact and each recorded file is the bytes "
        "that were recorded. It does not show that the results are right."
    ),
    "citations": (
        "What this checks: each quoted passage is in the source its claims file pins. It does "
        "not show that the source supports the sentence that quotes it."
    ),
}

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


class NothingToCheckError(ReproError):
    """The repository keeps no record any check reads."""

    def __init__(self, root: pathlib.Path) -> None:
        self.root = root
        super().__init__(
            f"{root} keeps no record a check reads; nothing was written.\n"
            + "\n".join(f"  {check:<10} {NO_RECORD[check]}" for check in CHECKS[:-1])
            + "\n\nWrite a manifest that pins this project's result files:\n\n"
            "    repro manifest init"
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
            f"--name takes WORKFLOW=TEXT, where WORKFLOW is one of {', '.join(CHECKS)}; "
            f"got {given!r}"
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


class NoRerunRecordedError(ReproError):
    """The reruns workflow was asked for and the record of re-runs holds none."""

    def __init__(self) -> None:
        super().__init__(f"{NO_RERUN}; nothing was written.")


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
    """None where the manifest declares no command. Reported and never graded here:
    `repro ci reruns` is the check that fails on it."""
    last_rerun: ReproductionReport | None = None
    """The latest invocation in the record of re-runs. None where it holds none."""
    numbers: NumbersReport | None = None
    """What `repro numbers` counts in the manuscript's text. None where no claim reads its
    sentence from a text. Reported beside the assertions and never graded."""

    @property
    def passed(self) -> bool:
        return self.verified.passed


class RecordRun(BaseModel):
    """What `repro ci reruns` found in the record of re-runs, having run nothing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    staleness: StalenessReport
    assessment: Assessment
    """Under `strict`, which fails a command that is stale, never rerun or undetermined."""


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
        last_rerun=log[-1] if log else None,
        numbers=counted,
    )


class ToolRun(BaseModel):
    """What one tool's own check found, run as `repro check` runs it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    check: str
    command: tuple[str, ...] = ()
    """The tool's command as a reader would type it. Empty where the tool was not run."""
    exit: int | None = None
    outcome: str
    """One of `repro audit`'s four words: passed, failed, could not check, nothing to read."""
    output: str = ""
    account: dict = {}
    """The JSON the tool wrote with `--json`. Empty where it wrote none."""
    fetched: dict | None = None
    """The JSON `citations fetch` wrote, where sources were fetched first."""

    @property
    def code(self) -> int:
        """`repro audit`'s exit code for one step with this outcome."""
        return audit.exit_code({self.check: {"outcome": self.outcome}})


def _account(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def tool(check: str, root: pathlib.Path, *, fetch: bool = False) -> ToolRun:
    """Run one tool's check over the project at `root` and read what it found.

    The tool is found and pointed by `repro.delegate`, run by `repro.audit.run_step`, and its
    outcome is the word `repro.audit.read` gives it, with one difference for `citations`: a run
    in which some quotations were found, none was not found and the rest were unchecked is
    `passed`, as `citations verify` exits 0 for it, where `repro audit` calls any unchecked
    quotation `could not check`. A run that read no source stays `could not check`.
    """
    found = BY_NAME[check]
    if not found.used_by(root):
        return ToolRun(check=check, outcome=audit.NOTHING, output=NO_RECORD[check])
    command = TOOL_COMMANDS[check]
    argv = command.argv(check, root)
    fetched, output = None, ""
    with tempfile.TemporaryDirectory() as scratch:
        if fetch:
            # Its exit code is not taken: a source nobody may redistribute is the ordinary
            # case, and what could not be fetched stays `unchecked` in the check below.
            wrote = pathlib.Path(scratch) / "fetch.json"
            _, output = audit.run_step(
                [check, *command.fetch, *argv[2:], command.report, str(wrote)],
                root,
                found.entry(),
            )
            fetched = _account(wrote)
            output += "\n\n"
        wrote = pathlib.Path(scratch) / "check.json"
        code, said = audit.run_step([*argv, command.report, str(wrote)], root, found.entry())
        account = _account(wrote)
    outcome, _, _ = audit.read(argv, code, said, root)
    if check == "citations" and outcome == audit.COULD_NOT and code == 0:
        # `citations verify` exits 1 for a run that measured nothing, so an exit of 0 with
        # quotations unchecked is a run in which some were found.
        outcome = audit.PASSED
    shown = tuple(
        pathlib.Path(part).relative_to(root).as_posix()
        if pathlib.Path(part).is_absolute() and pathlib.Path(part).is_relative_to(root)
        else part
        for part in argv
    )
    return ToolRun(
        check=check,
        command=shown,
        exit=code,
        outcome=outcome,
        output=output + said,
        account=account,
        fetched=fetched,
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


def _heading(check: str, project: str = "") -> list[str]:
    """The heading, then what the check is and where the documentation says what it means."""
    return [
        f"## {check}: {project}" if project else f"## {check}",
        "",
        f"{check}: {ABOUT[check]}. What this means: {DOCS}#{ANCHORS[check]}",
        "",
    ]


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


def _where(witness: Witness) -> str:
    """Where a re-run happened, as its entry in the record says, with the run linked. The
    clause is `Witness.said`, which `repro why` and `repro stale` print."""
    said = witness.said
    if witness.repository and witness.run_id:
        page = f"https://github.com/{witness.repository}/actions/runs/{witness.run_id}"
        said = said.replace(f"run {witness.run_id}", f"[run {witness.run_id}]({page})", 1)
    return f"{said}, as the environment said"


def _witnesses_found(report: StalenessReport) -> str:
    """Of the re-runs the commands were compared with, how many the record places in a run,
    and how many it places nowhere."""
    compared = [node for node in report.regenerations if node.rerun_at is not None]
    if not compared:
        return "no re-run was compared"
    placed = collections.Counter(_where(node.witness) for node in compared if node.witness)
    unplaced = len(compared) - sum(placed.values())
    parts = [f"{n} recorded {where}" for where, n in placed.items()]
    if unplaced:
        parts.append(
            f"{unplaced} recorded with no witness, which is how a re-run on someone's own "
            "machine is recorded"
        )
    return f"of the {_count(len(compared), 're-run')} compared: " + "; ".join(parts)


def _reruns_found(run: ClaimsRun) -> str:
    if run.staleness is None:
        return "no command is declared"
    if run.last_rerun is None:
        return f"not re-run in this job; `{RECORD.as_posix()}` holds no re-run"
    witness = run.last_rerun.witness
    return (
        f"not re-run in this job; the last recorded re-run, started {run.last_rerun.started_at}"
        + (f" {_where(witness)}" if witness else "")
        + f": {_reproduced(run.last_rerun)}"
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
        *_heading("claims", report.project),
        _verdict("repro ci claims", run.policy, [run.verified]),
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

    return "\n".join([*lines, "", CLAIMS_SHOWS, ""])


def record_summary(run: RecordRun) -> str:
    """The Markdown `repro ci reruns` appends to a step summary where it ran no command."""
    report = run.staleness
    nodes = report.regenerations
    states = collections.Counter(node.state for node in nodes)
    found = (
        f"{states[Freshness.CURRENT]} of {_count(len(nodes), 'declared command')} "
        f"{'has' if len(nodes) == 1 else 'have'} a recorded re-run over the current files that "
        "reproduced"
    )
    for state in (Freshness.STALE, Freshness.NEVER_RERUN, Freshness.UNDETERMINED):
        if states[state]:
            found += f", {states[state]} {_said(state.value)}"
    failing = [
        f"- `{node.artifact}`, written by `{node.id}`: {_said(node.state.value)}"
        + (
            f": upstream `{node.upstream}`"
            if node.upstream
            else "".join(f": {_said(cause.value)}" for cause in node.causes[:1])
        )
        for node in nodes
        if node.state is not Freshness.CURRENT
    ]
    lines = [
        *_heading("reruns", report.project),
        f"`repro ci reruns`: **{'passed' if run.assessment.passed else 'FAILED'}**",
        "",
        *_table(
            [
                ("commands", found),
                ("record", f"`{RECORD.as_posix()}` holds {_count(report.reruns, 're-run')}"),
                ("where", _witnesses_found(report)),
            ]
        ),
    ]
    if failing:
        lines += ["", "### Commands with no current re-run on record", "", *_listed(failing)]
    return "\n".join([*lines, "", RECORD_SHOWS, ""])


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
        *_heading("reruns", report.project),
        _verdict("repro ci reruns --run", run.policy, [run.assessment]),
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
                (
                    "where",
                    f"recorded {_where(report.witness)}"
                    if report.witness
                    else "recorded with no witness: the environment named no GitHub Actions run",
                ),
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


def _tool_verdict(run: ToolRun) -> str:
    word = run.outcome if run.outcome == audit.PASSED else run.outcome.upper()
    if not run.command:
        return f"`repro ci {run.check}`: **{word}**: {run.output}"
    return f"`{' '.join(run.command)}`: **{word}** (exit {run.exit})"


def _nonzero(counts: dict[str, int], states: tuple[str, ...]) -> str:
    return "".join(f", {counts[state]} {state}" for state in states if counts.get(state))


def _prereg_rows(account: dict) -> tuple[list[tuple[str, str]], list[str]]:
    plans = account.get("plans", [])
    frozen = [plan for plan in plans if plan["frozen"]]
    checks = collections.Counter(plan["check"] for plan in frozen)
    drafts = len(plans) - len(frozen)
    found = (
        f"{checks['unchanged']} of {_count(len(frozen), 'frozen plan')} unchanged since "
        f"the freeze"
        + (f", {checks['changed']} changed" if checks["changed"] else "")
        + (
            f", {checks['not frozen']} with an amendment that is not frozen"
            if checks["not frozen"]
            else ""
        )
        + (
            f"; {_count(drafts, 'plan')} of {len(plans)} never frozen, so a draft with nothing "
            "to compare"
            if drafts
            else ""
        )
    )
    entries = sum(plan["log_entries"] for plan in frozen)
    rows = [
        ("plans", found),
        (
            "amendments",
            f"{_count(sum(plan['amendments'] for plan in frozen), 'frozen amendment')}, "
            f"{_count(sum(plan['amendment_drafts'] for plan in frozen), 'draft')}",
        ),
        ("log", f"{entries} log entr{'y' if entries == 1 else 'ies'}"),
    ]
    if pinned := account.get("commit_pinned", []):
        statuses = collections.Counter(document["status"] for document in pinned)
        rows.append(
            (
                "frozen by a commit line",
                f"{statuses['unchanged']} of {_count(len(pinned), 'registration')} unchanged"
                + "".join(
                    f", {n} {status}" for status, n in statuses.items() if status != "unchanged"
                ),
            )
        )
    listed = [
        f"- `{plan['path']}`: " + ("never frozen" if not plan["frozen"] else plan["check"])
        for plan in plans
        if not plan["frozen"] or plan["check"] != "unchanged"
    ] + [
        f"- `{document['path']}`: {document['status']}"
        for document in account.get("commit_pinned", [])
        if document["status"] in ("changed", "pending", "unknown commit")
    ]
    return rows, listed


def _results_rows(account: dict) -> tuple[list[tuple[str, str]], list[str]]:
    files = account.get("files", [])
    states = collections.Counter(file["state"] for file in files)
    chain = account.get("chain", "")
    rows = [
        (
            "chain",
            f"{chain}: {_count(account['events'], 'event')}"
            if "events" in account
            else f"{_said(chain)}: {'; '.join(account.get('problems', []))[: MAX_SHOWN * 3]}",
        ),
        (
            "recorded files",
            f"{states['ok']} of {_count(len(files), 'recorded file')} match "
            f"the hash recorded"
            + _nonzero(states, ("changed", "missing", "resealed", "not a tree", "not a file"))
            if "events" in account
            else "not compared: the chain did not verify",
        ),
    ]
    listed = [f"- `{file['path']}`: {file['state']}" for file in files if file["state"] != "ok"]
    return rows, listed


def _citations_rows(run: ToolRun) -> tuple[list[tuple[str, str]], list[str]]:
    account = run.account
    counts = account.get("counts", {})
    rows = [
        (
            "quotations",
            f"{counts.get('found', 0)} found, {counts.get('not found', 0)} not found, "
            f"{counts.get('unchecked', 0)} unchecked"
            + _nonzero(counts, ("ambiguous", "indeterminate"))
            + f" of {_count(account.get('quotes', 0), 'quotation')}",
        ),
        (
            "sources",
            f"{account.get('sources', 0) - account.get('absent_sources', 0)} of "
            f"{_count(account.get('sources', 0), 'source')} on this machine, "
            f"{account.get('absent_sources', 0)} absent"
            + _nonzero(
                {
                    "not the pinned bytes": account.get("broken_pins", 0),
                    "unpinned": account.get("unpinned_sources", 0),
                },
                ("not the pinned bytes", "unpinned"),
            ),
        ),
    ]
    if run.fetched is not None:
        fetched = run.fetched.get("counts", {})
        rows.append(
            (
                "fetch",
                f"{_count(run.fetched.get('sources', 0), 'source')}: "
                f"{fetched.get('fetched', 0)} fetched and matched to the pinned digest, "
                f"{fetched.get('present', 0)} already present"
                + "".join(
                    f", {n} {state}"
                    for state, n in fetched.items()
                    if n and state not in ("fetched", "present")
                ),
            )
        )
    return rows, []


def tool_summary(run: ToolRun) -> str:
    """The Markdown `repro ci prereg`, `results` and `citations` append to a step summary."""
    lines = [*_heading(run.check), _tool_verdict(run)]
    if run.account:
        if run.check == "citations":
            counts = run.account.get("counts", {})
            total = run.account.get("quotes", 0)
            unresolved = total - counts.get("found", 0) - counts.get("not found", 0)
            if unresolved:
                # Before the table, so a pass is never read without it.
                lines += [
                    "",
                    f"{unresolved} of {_count(total, 'quotation')} were not checked: "
                    f"{run.account.get('absent_sources', 0)} of "
                    f"{_count(run.account.get('sources', 0), 'source')} are not on this machine. "
                    "An unchecked quotation is not a found one.",
                ]
            rows, listed = _citations_rows(run)
        elif run.check == "results":
            rows, listed = _results_rows(run.account)
        else:
            rows, listed = _prereg_rows(run.account)
        lines += ["", *_table(rows)]
        if listed:
            lines += ["", *_listed(listed)]
    return "\n".join([*lines, "", SHOWS[run.check], ""])


# --------------------------------------------------------------------------------- workflows


class Workflow(BaseModel):
    """One workflow `repro ci init` writes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    file: str
    name: str
    text: str

    check: str

    def badge(self, slug: str) -> str:
        """The README line: GitHub's badge for this workflow, linked to its runs."""
        runs = f"https://github.com/{slug}/actions/workflows/{self.file}"
        return f"[![{self.name}]({runs}/badge.svg)]({runs})"

    def branded(self, slug: str) -> str:
        """The same badge drawn by shields.io, with the check's icon on a dark label.

        shields.io reads GitHub's badge for the workflow, so it shows what that badge shows,
        and only for a repository anyone can read.
        """
        runs = f"https://github.com/{slug}/actions/workflows/{self.file}"
        query = urllib.parse.urlencode(
            {"label": self.name, "labelColor": LABEL_COLOR, "logo": logo(self.check)},
            quote_via=urllib.parse.quote,
        )
        return f"[![{self.name}]({SHIELDS}/{slug}/{self.file}?{query})]({runs})"


def logo(check: str) -> str:
    """A check's icon as the data URI shields.io takes for a custom logo."""
    icon = importlib.resources.files("repro").joinpath("icons", f"{check}.svg").read_bytes()
    return "data:image/svg+xml;base64," + base64.b64encode(icon.strip()).decode("ascii")


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
    environment: str = "",
) -> Workflow:
    """The workflow that runs one `repro ci` command, pinned to the installed version of this
    package."""
    if __version__ == "0+unknown":
        raise VersionUnknownError
    return Workflow(
        check=check,
        file=f"{prefix}{check}.yml",
        name=name or NAMES[check],
        text=WORKFLOW.format(
            marker=MARKER,
            name=_scalar(name or NAMES[check]),
            branch=_scalar(branch),
            job=check,
            checkout=CHECKOUT,
            setup_uv=SETUP_UV,
            environment=environment,
            distribution=DISTRIBUTION,
            version=__version__,
            command=command,
        ),
    )


def repository(remote: str) -> str | None:
    """`OWNER/REPO` from a GitHub remote's URL, over https or ssh, or None for any other."""
    found = _GITHUB.search(remote.strip())
    return f"{found['owner']}/{found['repo']}" if found else None


def with_badges(
    readme: str, wanted: list[Workflow], slug: str, *, branded: bool = False
) -> tuple[str, list[str]]:
    """A README with the badge of each workflow it does not already show, and the badges added.

    They go together on one line under the first heading, at the head of a block of badges
    where one is there. A README with no heading takes them at its top.
    """
    added = [
        flow.branded(slug) if branded else flow.badge(slug)
        for flow in wanted
        if f"/actions/workflows/{flow.file}/badge.svg" not in readme
        and f"{SHIELDS}/{slug}/{flow.file}?" not in readme
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
    run_reruns: bool = False,
    fetch_sources: bool = False,
    force: bool = False,
    readme: bool = False,
    branded: bool = False,
    prefix: str = "",
    names: dict[str, str] | None = None,
) -> int:
    """Write a workflow for each check the repository holding `cwd` keeps a record for, and
    print the README lines."""
    top = try_run("rev-parse", "--show-toplevel", cwd=cwd)
    if not top:
        raise NotARepositoryError(cwd)
    root = pathlib.Path(top.strip()).resolve()
    path = find(cwd)
    if path is not None and not path.is_relative_to(root):
        path = None
    declared = bool(path and load(path).regenerations)
    if (reruns or run_reruns) and not declared:
        raise NothingToRerunError(path or root / DEFAULT_NAME)
    # A badge for the record check is written only where there is a record for it to read:
    # without one the workflow could only fail, and its badge would say so from the first run.
    recorded = bool(path and declared and recorded_reruns(path.parent))
    if reruns and not run_reruns and not recorded:
        raise NoRerunRecordedError

    # The workflow runs at the top of the checkout, so a manifest below the top is named.
    relative = path.relative_to(root).as_posix() if path else DEFAULT_NAME
    named = "" if relative == DEFAULT_NAME else f" {shlex.quote(relative)}"
    commands = {
        "claims": f"repro ci claims{named}",
        "citations": "repro ci citations" + (" --fetch-sources" if fetch_sources else ""),
        "reruns": f"repro ci reruns{named}" + (" --run" if run_reruns else ""),
    }
    steps = {"citations": POPPLER, "reruns": ENVIRONMENT if run_reruns else ""}
    kept = {check: BY_NAME[check].used_by(root) for check in TOOLS}
    kept |= {"claims": path is not None, "reruns": declared and (recorded or run_reruns)}
    if not any(kept.values()):
        raise NothingToCheckError(root)
    head = try_run("symbolic-ref", "--short", "refs/remotes/origin/HEAD", cwd=root)
    branch = head.strip().removeprefix("origin/") if head else "main"
    wanted = [
        workflow(
            check,
            commands.get(check, f"repro ci {check}"),
            name=(names or {}).get(check),
            prefix=prefix,
            branch=branch,
            environment=steps.get(check, ""),
        )
        for check in CHECKS
        if kept[check]
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
    for check in CHECKS:
        if not kept[check]:
            why_not = NO_RERUN if check == "reruns" and declared else NO_RECORD[check]
            print(f"skipped {check}: {why_not}")
    print(f"each runs on a push to {branch} and on every pull request")
    if run_reruns:
        print(f"edit {(WORKFLOWS / wanted[-1].file).as_posix()} to install what the commands need")

    if readme and slug:
        text, added = with_badges(target.read_text(encoding="utf-8"), wanted, slug, branded=branded)
        print("\nREADME.md")
        if added:
            atomic_write(target, text)
            print(f"  + {' '.join(added)}")
        else:
            print("  already shows each badge; nothing was added")
    else:
        named_as = slug or "OWNER/REPO"
        print("\nadd to your README, one line per check. GitHub's own badge, which also")
        print("works in a private repository:\n")
        print("\n".join(flow.badge(named_as) for flow in wanted))
        print("\nor, for a public repository, the same status drawn by shields.io with the")
        print("check's icon:\n")
        print("\n".join(flow.branded(named_as) for flow in wanted))
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


def command_claims(args: argparse.Namespace, verify_text: Shown) -> int:
    path = _manifest(args)
    if path is None:
        return 2
    policy = PROFILES[args.policy]
    run = claims(load(path), policy)
    verify_text(path, run.verification, policy, run.verified)
    # Reported, and graded by `repro ci reruns`.
    print(f"\n  freshness: {_freshness_found(run.staleness)}")
    _summarize(args, claims_summary(run))
    return 0 if run.passed else 1


def command_reruns(args: argparse.Namespace, reproduce_text: Shown, stale_text: Shown) -> int:
    path = _manifest(args)
    if path is None:
        return 2
    manifest = load(path)
    if not manifest.regenerations:
        print(f"{path}\n")
        print("  no command is declared, so there is no re-run to look for. A record under")
        print("  `regenerations` names a command, the files it reads and the file it writes.")
        return 2
    if not args.run:
        # Graded under `strict` whatever `--policy` says: this check is the one that fails a
        # command with no current re-run on record, which `publication` only warns of.
        report = stale(manifest)
        found = STRICT.assess_staleness(report)
        stale_text(path, report, STRICT, found)
        _summarize(args, record_summary(RecordRun(staleness=report, assessment=found)))
        return 0 if found.passed else 1
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


def command_tool(args: argparse.Namespace) -> int:
    run = tool(
        args.action, project_root(pathlib.Path.cwd()), fetch=getattr(args, "fetch_sources", False)
    )
    print(run.output)
    if run.command and run.outcome != audit.PASSED:
        print(f"\n{run.outcome}: `repro ci {run.check}` exits {run.code}.")
    _summarize(args, tool_summary(run))
    return run.code


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
        run_reruns=args.run_reruns,
        fetch_sources=args.fetch_sources,
        force=args.force,
        readme=args.readme,
        branded=args.branded,
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
            "The checks as one line of a workflow each. `prereg`, `results` and `citations` "
            "run that tool's own check, `claims` runs what `repro verify` and `repro stale` "
            "run, `reruns` runs what `repro reproduce` runs, and each appends a Markdown "
            "summary to the file GITHUB_STEP_SUMMARY names. `init` writes a workflow for each "
            "check the repository keeps a record for, and prints the README lines."
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

    def tool_check(name: str, text: str, description: str) -> argparse.ArgumentParser:
        made = actions.add_parser(
            name,
            help=text,
            description=description
            + " Exits 0 where the check passed, 1 where it failed, and 2 where it could not "
            "be made or the project keeps nothing for it to read.",
        )
        made.add_argument(
            "--summary",
            metavar="PATH",
            help="append the Markdown summary to this file (default: $GITHUB_STEP_SUMMARY)",
        )
        made.set_defaults(func=command_tool)
        return made

    tool_check(
        "prereg",
        "has any frozen plan changed since its freeze?",
        f"Run `{TOOL_COMMANDS['prereg'].said('prereg')}` over the project: every plan, its "
        "amendments and its log.",
    )
    tool_check(
        "results",
        "does the ledger's chain verify, and is each recorded file the one recorded?",
        f"Run `{TOOL_COMMANDS['results'].said('results')}` over the project.",
    )

    p_claims = checks(
        "claims",
        "check every assertion, then say which claims read a file changed since its re-run",
        "Run what `repro verify` runs. Executes nothing. Exits 1 where the policy fails the "
        "verification, 2 with no manifest, and 0 otherwise. Where the manifest declares a "
        "command, how many assertions read a file current with a recorded re-run is printed "
        "and not graded: `repro ci reruns` is the check that fails on it.",
    )
    p_claims.set_defaults(func=lambda args: command_claims(args, verify))

    tool_check(
        "citations",
        "does every quotation resolve in the source its claims file pins?",
        f"Run `{TOOL_COMMANDS['citations'].said('citations')}` over the project's claims "
        "directory. A run in "
        "which no quotation was found could not check anything and does not pass; one in "
        "which some were found, none was not found and the rest were unchecked passes, and "
        "its summary opens on how many were not checked.",
    ).add_argument(
        "--fetch-sources",
        action="store_true",
        help="fetch first, which downloads each absent source from where its "
        "claims file says an open copy is and keeps only bytes matching the pinned digest",
    )

    p_reruns = checks(
        "reruns",
        "is a re-run of each declared command, over the current files, on record?",
        f"Read {RECORD.as_posix()} as `repro stale` reads it and run nothing: pass where every "
        "declared command has a recorded re-run that reproduced, made over today's command "
        "and inputs, whose output is the file now on disk, and fail where one is stale, never "
        "rerun or undetermined, whatever --policy says. With --run, run what `repro reproduce` "
        f"runs instead, append the re-run to {RECORD.as_posix()} as it does, and grade it "
        "under --policy. Exits 2 with no manifest or no command declared.",
    )
    p_reruns.add_argument(
        "--run",
        action="store_true",
        help="run the declared commands again in this job; this executes what the manifest names",
    )
    p_reruns.add_argument(
        "--only", action="append", metavar="ID", help="with --run, run this record; repeatable"
    )
    p_reruns.add_argument(
        "--skip",
        action="append",
        metavar="ID",
        help="with --run, leave this record out; repeatable",
    )
    p_reruns.set_defaults(func=lambda args: command_reruns(args, reproduce, stale))

    p_init = actions.add_parser(
        "init",
        help="write the workflows and print the README lines",
        description=(
            f"Write a workflow under {WORKFLOWS.as_posix()}/ for each check the repository "
            "keeps a record for (prereg.yml, results.yml, claims.yml, citations.yml), each "
            "running one `repro ci` command on a push to the default branch and on every pull "
            "request, say which were skipped and why, and print two badge lines for each. "
            "reruns.yml, which checks that a re-run of each declared command is on record, is "
            "written where the manifest declares a command and the record holds a re-run. "
            "Each workflow is named for its check. A "
            "workflow this command wrote is replaced only with --force, and any other file "
            "of that name is never replaced."
        ),
    )
    p_init.add_argument(
        "--reruns",
        action="store_true",
        help="require reruns.yml, and write nothing where the manifest declares no command "
        "or the record holds no re-run",
    )
    p_init.add_argument(
        "--run-reruns",
        action="store_true",
        help="write reruns.yml to run the declared commands again in the job, for a project "
        "whose commands can run in CI",
    )
    p_init.add_argument(
        "--fetch-sources",
        action="store_true",
        help="have the citations workflow fetch absent sources before it checks",
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
        "--branded",
        action="store_true",
        help="with --readme, put the shields.io badges, which carry each check's icon and "
        "work only for a public repository",
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
        metavar="WORKFLOW=TEXT",
        help="name a check's workflow, which is what its badge prints; repeatable "
        f"(default: {', '.join(f'{check}={NAMES[check]}' for check in CHECKS)})",
    )
    p_init.set_defaults(func=command_init)


__all__ = [
    "CHECKS",
    "NAMES",
    "ClaimsRun",
    "RerunsRun",
    "ToolRun",
    "Workflow",
    "claims",
    "claims_summary",
    "init",
    "repository",
    "reruns_summary",
    "tool",
    "tool_summary",
    "with_badges",
    "workflow",
]
