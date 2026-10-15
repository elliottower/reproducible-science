"""`repro verify`: every record a project keeps, checked in one pass, with one exit code.

    claims      the manifest's claims, as `claims verify` checks them
    staleness   what `repro stale` reports of each declared command, read from the record
    prereg      `prereg check`
    results     `results verify --files`
    citations   `citations verify --claims <dir>`
    cross-tool  a ledger claim naming a freeze no frozen plan records

A record the project does not keep is named as not used and is not run: reporting it as passing
would be a clean line standing for a check that never happened. The three tools are found,
pointed and run as `repro ci` runs them, in this process, and their counts are read from the
JSON each writes. Executes nothing a manifest declares and reaches no network: `repro
reproduce` is the command that runs things. `claims verify` is the claims alone, and the
fast check.

The exit code is 0 where every check that ran passed, 1 where one failed (a tool that could
not check counts as not passing, and is said as `could not check`), and 2 where nothing was
checked: no manifest, and no other record.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from claims.cli import (
    _checked,
    _stale_lines,
    _stale_summary,
    _survey_lines,
    _verify_text,
    add_verify,
)
from claims.manifest import DEFAULT_NAME, find
from claims.models import Manifest, StalenessReport
from claims.policy import PROFILES, Assessment, Policy
from claims.renderers import survey_to_sarif, to_sarif
from claims.stale import stale as run_stale
from claims.starter import SURVEY_SCHEMA, survey
from pydantic import BaseModel, ConfigDict

from repro import __version__, audit, ci, crosscheck

#: The sections of the report other than the claims, in the order they are printed.
TOOLS = ci.TOOLS
SECTIONS = ("claims", "staleness", *TOOLS, "cross_tool")

#: What the report says of the staleness check where the manifest declares no command.
NO_COMMAND = f"{DEFAULT_NAME} declares no command under `regenerations`"


class Staleness(BaseModel):
    """What `repro stale` would report, graded under the same policy as the claims."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    used: bool
    reason: str = ""
    report: StalenessReport | None = None
    assessment: Assessment | None = None

    @property
    def passed(self) -> bool | None:
        return self.assessment.passed if self.assessment else None


class CrossTool(BaseModel):
    """What reading two tools' records together finds that neither finds alone."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    unmatched: tuple[dict[str, str], ...] = ()
    """Ledger claims naming a freeze no frozen plan under the project records. Fails."""
    confirmatory_without_a_plan: tuple[str, ...] = ()
    """Confirmatory claims in a project that has frozen no plan. Reported, never failed: a
    plan frozen elsewhere is a real arrangement this cannot see."""

    @property
    def passed(self) -> bool | None:
        """False where a claim names an unrecorded freeze; None, not a check that ran, else."""
        return False if self.unmatched else None


class Project(BaseModel):
    """Everything `repro verify` checks beside the claims."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    root: str
    staleness: Staleness
    tools: dict[str, ci.ToolRun]
    cross_tool: CrossTool


def tool_passed(run: ci.ToolRun) -> bool | None:
    """None for a tool the project does not use, which was not run."""
    return run.outcome == audit.PASSED if run.command else None


def check(root: Path, manifest: Manifest | None, policy: Policy) -> Project:
    """Check every record the project at `root` keeps beside the manifest's claims."""
    if manifest is None:
        staleness = Staleness(used=False, reason=f"no {DEFAULT_NAME} here or above")
    elif not manifest.regenerations:
        staleness = Staleness(used=False, reason=NO_COMMAND)
    else:
        report = run_stale(manifest)
        staleness = Staleness(used=True, report=report, assessment=policy.assess_staleness(report))
    return Project(
        root=root.as_posix(),
        staleness=staleness,
        tools={name: ci.tool(name, root) for name in TOOLS},
        cross_tool=CrossTool(
            unmatched=tuple({"claim": c.claim, "ref": c.ref} for c in crosscheck.unmatched(root)),
            confirmatory_without_a_plan=tuple(crosscheck.confirmatory_without_a_plan(root)),
        ),
    )


def verdicts(claims: bool | None, project: Project) -> dict[str, bool | None]:
    """Each section's verdict: True passed, False did not, None not used and not run."""
    return {
        "claims": claims,
        "staleness": project.staleness.passed,
        **{name: tool_passed(run) for name, run in project.tools.items()},
        "cross_tool": project.cross_tool.passed,
    }


def exit_code(found: dict[str, bool | None]) -> int:
    ran = [passed for passed in found.values() if passed is not None]
    if not ran:
        return 2
    return 0 if all(ran) else 1


def words(project: Project, found: dict[str, bool | None]) -> dict[str, str]:
    """Each section's verdict in words: `passed`, `failed` or `not used`, and for a tool the
    outcome its own check gave, so `could not check` and `nothing to read` stay apart from
    `failed`. Either counts against the exit code as a failure does."""
    said = {
        name: "not used" if passed is None else "passed" if passed else "failed"
        for name, passed in found.items()
    }
    return said | {name: run.outcome for name, run in project.tools.items() if run.command}


def sections(project: Project, found: dict[str, bool | None]) -> dict:
    """The keys `--format json` adds beside the claims' own, which it leaves as they were."""
    staleness = project.staleness
    return {
        "staleness": {
            "used": staleness.used,
            "passed": staleness.passed,
            "reason": staleness.reason,
            "report": staleness.report.model_dump(mode="json") if staleness.report else None,
            "assessment": (
                staleness.assessment.model_dump(mode="json") if staleness.assessment else None
            ),
        },
        **{
            name: {
                "used": bool(run.command),
                "passed": tool_passed(run),
                **run.model_dump(mode="json", exclude={"fetched"}),
            }
            for name, run in project.tools.items()
        },
        "cross_tool": {"passed": project.cross_tool.passed, **project.cross_tool.model_dump()},
        "project": {
            "root": project.root,
            "checks": words(project, found),
            "exit_code": exit_code(found),
        },
    }


def _tool_lines(run: ci.ToolRun) -> list[str]:
    if not run.command:
        return [f"  {run.check:<12} not used here: {run.output}"]
    said = " ".join(run.command)
    if run.outcome == audit.PASSED:
        missed = ci.unchecked(run)
        note = f", {ci.verified(run)}: {missed} not checked" if missed else ""
        return [f"  {run.check:<12} passed{note}  ({said})"]
    lines = [f"  {run.check:<12} {run.outcome.upper()} (exit {run.exit})  ({said})"]
    return lines + [f"      {line}" for line in run.output.rstrip().splitlines()]


def _project_text(
    project: Project, policy: Policy, found: dict[str, bool | None], claims: str = ""
) -> None:
    """The sections beside the claims. `claims` is the line said of them where they were not
    checked, which is printed among the others."""
    print(f"\n{project.root}\n")
    if claims:
        print(f"  {'claims':<12} not used here: {claims}")
    staleness = project.staleness
    if staleness.report is None or staleness.assessment is None:
        print(f"  {'staleness':<12} not used here: {staleness.reason}")
    else:
        word = "passed" if staleness.assessment.passed else "FAILED"
        print(
            f"  {'staleness':<12} {word} under policy {policy.name}  "
            f"({len(staleness.assessment.errors)} errors, "
            f"{len(staleness.assessment.warnings)} warnings)"
        )
        for line in [*_stale_lines(staleness.report), *_stale_summary(staleness.report)]:
            print(f"    {line}" if line else "")
    for run in project.tools.values():
        print("\n".join(_tool_lines(run)))

    cross = project.cross_tool
    if cross.unmatched:
        print("\n  claims naming a freeze that no frozen plan records:")
        for c in cross.unmatched:
            print(f"      {c['claim'][:58]}  cites {c['ref']}")
        print("      `results` checks that the reference resolves to a commit, not that a plan")
        print("      was frozen at it, so a citation like this passes every tool on its own.")
    if unplanned := cross.confirmatory_without_a_plan:
        print("\n  confirmatory claims, and no frozen plan in this project:")
        for text in unplanned[:10]:
            print(f"      {text[:70]}")
        if len(unplanned) > 10:
            print(f"      ... and {len(unplanned) - 10} more")
        print("      Reported, not failed: a plan frozen elsewhere or registered on OSF is a")
        print(
            "      real arrangement this cannot see. What it can say is nothing here records one."
        )

    print()
    print("\n".join(_summary(project, found)))


def _summary(project: Project, found: dict[str, bool | None]) -> list[str]:
    """How many checks passed, the others by their word, and the sections not used."""
    said = words(project, found)
    ran = [name for name, passed in found.items() if passed is not None]
    passed = [name for name in ran if found[name]]
    lines = []
    if ran:
        by_word: dict[str, list[str]] = {}
        for name in ran:
            if not found[name]:
                by_word.setdefault(said[name], []).append(name)
        lines.append(
            f"{len(passed)} of {len(ran)} checks passed"
            + "".join(f"; {word}: {', '.join(names)}" for word, names in by_word.items())
        )
    unused = [name for name, passed in found.items() if passed is None and name != "cross_tool"]
    if unused:
        lines.append(f"not used here: {', '.join(unused)}")
    return lines


def locate(given: str | None) -> tuple[Path, Path | None]:
    """The project's root and its manifest. A directory names the project, and its manifest
    is the one at its top. A file is the manifest, and the project is the folder holding it.
    With neither, the manifest is the one at or above the working directory and the project is
    its folder, or the working directory where there is none."""
    if given is not None:
        path = Path(given)
        if path.is_dir():
            manifest = path / DEFAULT_NAME
            return path.resolve(), manifest if manifest.is_file() else None
        return path.resolve().parent, path
    found = find()
    return (found.resolve().parent if found else Path.cwd().resolve()), found


def command(args: argparse.Namespace) -> int:
    root, path = locate(args.manifest)
    policy = PROFILES[args.policy]
    if path is None:
        project = check(root, None, policy)
        found = verdicts(None, project)
        listed = survey(root)
        if args.format == "json":
            print(
                json.dumps(
                    {
                        "schema_version": SURVEY_SCHEMA,
                        "manifest": None,
                        "verified": 0,
                        "survey": listed.model_dump(mode="json"),
                        **sections(project, found),
                    },
                    indent=2,
                )
            )
        elif args.format == "sarif":
            print(
                json.dumps(
                    _with_checks(survey_to_sarif(listed, version=__version__), project, found),
                    indent=2,
                )
            )
        elif exit_code(found) == 2:
            # Nothing at all to check: what `claims verify` prints, which says what a manifest
            # could pin, and then the sections not used.
            print(f"no {DEFAULT_NAME} here or above.\n")
            print("\n".join(_survey_lines(listed)))
            print("write one that pins this project's result files, with example claims to edit:\n")
            print("    repro manifest init\n")
            print("\n".join(_summary(project, found)))
        else:
            # Other records were checked, so the claims are one section among them, not used.
            _project_text(
                project,
                policy,
                found,
                claims=f"no {DEFAULT_NAME} here or above; `repro manifest init` writes one",
            )
        return exit_code(found)

    manifest, report, policy, assessment = _checked(args, path)
    project = check(root, manifest, policy)
    found = verdicts(assessment.passed, project)
    if args.format == "sarif":
        sarif = to_sarif(report, assessment, version=__version__)
        print(json.dumps(_with_checks(sarif, project, found), indent=2))
    elif args.format == "json":
        print(
            json.dumps(
                {
                    "report": report.model_dump(mode="json"),
                    "assessment": assessment.model_dump(mode="json"),
                    **sections(project, found),
                },
                indent=2,
            )
        )
    else:
        _verify_text(path, report, policy, assessment)
        _project_text(project, policy, found)
    return exit_code(found)


def _with_checks(sarif: dict, project: Project, found: dict[str, bool | None]) -> dict:
    """The claims' SARIF run, with each section's verdict and the exit code under `checks` in
    its property bag, beside the `project` name the claims' log already gives. A result is an
    assertion, so a tool's verdict is a property of the run, not a result."""
    sarif["runs"][0]["properties"]["checks"] = {
        "sections": words(project, found),
        "exit_code": exit_code(found),
    }
    return sarif


DESCRIPTION = (
    "Check every record the project keeps, in one report with one exit code: the claims "
    f"{DEFAULT_NAME} declares, as `claims verify` checks them; each declared command against "
    "the record of its re-runs, as `repro stale` reports it, graded under --policy; `prereg "
    "check`; `results verify --files`; `citations verify` over the claims directory; and a "
    "ledger claim naming a freeze no frozen plan records. A record the project does not keep "
    "is named as not used and is not run. Executes nothing a manifest declares and reaches no "
    "network. Exits 0 where every check that ran passed, 1 where one failed or could not "
    "check, and 2 where nothing was checked. `claims verify` checks the claims alone."
)


def add_parser(sub: argparse._SubParsersAction) -> argparse.ArgumentParser:
    # `claims.cli.add_verify` holds the options, so `repro verify` and `claims verify` take the
    # same ones and write the same record of checks.
    return add_verify(
        sub,
        func=command,
        summary="check the claims and every other record this project keeps, in one pass",
        description=DESCRIPTION,
        target=f"{DEFAULT_NAME}, or the project's directory (default: the {DEFAULT_NAME} here "
        "or above)",
    )


__all__ = [
    "SECTIONS",
    "CrossTool",
    "Project",
    "Staleness",
    "add_parser",
    "check",
    "command",
    "exit_code",
    "verdicts",
]
