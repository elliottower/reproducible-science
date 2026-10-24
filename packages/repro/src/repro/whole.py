"""`repro verify`: every record a project keeps, checked in one pass, with one exit code.

    claims      the manifest's claims, as `claims verify` checks them
    staleness   what `repro stale` reports of each declared command, read from the record
    prereg      `prereg check`
    results     `results verify --files`
    citations   `citations verify --claims <dir>`
    cross-tool  a ledger claim naming a freeze no frozen plan records
    coverage    `citations coverage` and `results coverage` over the manuscript: a quotation
                nothing pins, a number nothing binds (see `repro.coverage`)

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
from claims.models import Manifest, StalenessReport, VerificationReport
from claims.policy import PROFILES, STRICT, Assessment, Policy, Severity, Violation
from claims.renderers import survey_to_sarif, to_sarif
from claims.stale import stale as run_stale
from claims.starter import SURVEY_SCHEMA, survey
from pydantic import BaseModel, ConfigDict

from repro import __version__, audit, ci, crosscheck
from repro import coverage as manuscript

#: The sections of the report other than the claims, in the order they are printed.
TOOLS = ci.TOOLS
SECTIONS = ("claims", "staleness", *TOOLS, "cross_tool", "coverage")

#: The quotation states `citations verify --strict` fails as reaching no verdict.
CITATIONS_UNRESOLVED = ("unchecked", "indeterminate", "ambiguous")

#: The claims' rule for numbers no assertion accounts for, which coverage reports instead where
#: it counts them.
UNBOUND_RULE = "numbers.unbound"

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
    coverage: manuscript.Coverage


def tool_passed(run: ci.ToolRun) -> bool | None:
    """None for a tool the project does not use, which was not run."""
    return run.outcome == audit.PASSED if run.command else None


def check(
    root: Path, manifest: Manifest | None, policy: Policy, limit: int | None = None
) -> Project:
    """Check every record the project at `root` keeps beside the manifest's claims. `limit` is
    `--max-unbound`, which the coverage section applies where it counts unbound numbers."""
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
        tools={name: ci.tool(name, root, strict=policy.name == STRICT.name) for name in TOOLS},
        cross_tool=CrossTool(
            unmatched=tuple({"claim": c.claim, "ref": c.ref} for c in crosscheck.unmatched(root)),
            confirmatory_without_a_plan=tuple(crosscheck.confirmatory_without_a_plan(root)),
        ),
        coverage=manuscript.coverage(root, manifest, policy.name, limit),
    )


def verdicts(claims: bool | None, project: Project) -> dict[str, bool | None]:
    """Each section's verdict: True passed, False did not, None not used and not run."""
    return {
        "claims": claims,
        "staleness": project.staleness.passed,
        **{name: tool_passed(run) for name, run in project.tools.items()},
        "cross_tool": project.cross_tool.passed,
        # Named only where it ran, so a project with no manuscript to cover reads as before.
        **({"coverage": project.coverage.passed} if project.coverage.used else {}),
    }


def strict_failures(
    project: Project, policy: Policy, report: VerificationReport | None = None
) -> tuple[Violation, ...]:
    """Every finding `strict` fails that `policy` does not, read off results already in hand.

    Nothing is run again: the claims report, the staleness report and the coverage findings
    are graded a second time under `strict`, and a finding counts where `strict` makes it an
    error and `policy` did not. The claims report carries the notes on `reported` values
    (a coarse precision, a loose tolerance), so they count here as graded. What `results` and
    `citations` pass and fail only under their own `--strict` is added from their accounts.
    Empty under `strict`. A check that grades by policy adds its own findings here, so the line
    `repro verify` closes on counts them too.
    """
    if policy.name == STRICT.name:
        return ()
    pairs: list[tuple[tuple[Violation, ...], tuple[Violation, ...]]] = []
    if report is not None:
        pairs.append((STRICT.assess(report).violations, policy.assess(report).violations))
    if project.staleness.report is not None:
        staleness = project.staleness.report
        pairs.append(
            (
                STRICT.assess_staleness(staleness).violations,
                policy.assess_staleness(staleness).violations,
            )
        )
    if project.coverage.used:
        pairs.append((project.coverage.under(STRICT.name), project.coverage.violations))
    found = []
    for strict, applied in pairs:
        failed = {(v.rule, v.subject) for v in applied if v.severity is Severity.ERROR}
        found += [
            v for v in strict if v.severity is Severity.ERROR and (v.rule, v.subject) not in failed
        ]
    return (*found, *_tool_strict(project))


def _tool_strict(project: Project) -> list[Violation]:
    """What a tool reports and passes, and fails under its own `--strict`: a claim printing
    numbers its run's outputs do not hold, a claim whose run's outputs were all retired and a
    timestamp proof history holds and the disk does not, and an output recorded again with no
    input sealed between, from `results verify`; and from `citations verify`, each found
    quotation carrying a warning its `--strict` fails, a pin finding it fails, and each
    unresolved quotation, unpinned source and unparsed claims file. Under
    `--policy strict` both run with `--strict`, so these are what that run fails."""

    def error(rule: str, subject: str, detail: str) -> Violation:
        return Violation(severity=Severity.ERROR, rule=rule, subject=subject, detail=detail)

    found = []
    results = project.tools.get("results")
    if results is not None and results.command:
        for account in (results.account, *results.account.get("nested", [])):
            found += [
                error(
                    "results.claim_numbers_not_in_outputs",
                    str(c.get("run_id")),
                    f"{', '.join(c.get('numbers', []))} in: {c.get('claim', '')}",
                )
                for c in account.get("claims_numbers_not_in_outputs", [])
            ]
            found += [
                error("results.claim_on_retired_outputs", "", str(claim))
                for claim in account.get("claims_on_retired_outputs", [])
            ]
            found += [
                error("results.timestamp_proof_missing", str(p.get("path")), "deleted from disk")
                for p in account.get("missing_proofs", [])
            ]
            found += [
                error("results.rerecorded", str(path), "recorded again with no input sealed")
                for path in account.get("rerecorded", [])
            ]
    citations = project.tools.get("citations")
    if citations is not None and citations.command:
        account = citations.account
        failing = set(account.get("strict_warnings", []))
        # One finding per quotation, as `citations verify --strict` lists them: a quotation
        # carrying two warnings it fails on is one line there, and one here.
        per_quote: dict[tuple[str, str], list[str]] = {}
        for warning, quotes in account.get("warnings", {}).items():
            if warning not in failing:
                continue
            for q in quotes:
                if q.get("state") == "found":
                    key = (str(q.get("claim")), str(q.get("quote")))
                    per_quote.setdefault(key, []).append(warning.replace(" ", "_"))
        found += [
            error(f"citations.{'+'.join(sorted(warnings))}", claim, quote)
            for (claim, quote), warnings in per_quote.items()
        ]
        found += [
            error("citations.pins", str(f.get("file")), str(f.get("finding")))
            for f in account.get("strict_findings", [])
        ]
        # Counted and not listed by `citations verify`, so one finding each, by count.
        counts = account.get("counts", {})
        unresolved = sum(counts.get(state, 0) for state in CITATIONS_UNRESOLVED)
        found += [
            error("citations.unresolved", "", "a quotation no verdict was reached on")
        ] * unresolved
        found += [error("citations.unpinned", "", "a source with no digest")] * account.get(
            "unpinned_sources", 0
        )
        found += [error("citations.skipped", "", "a claims file that did not parse")] * account.get(
            "skipped_files", 0
        )
    return found


def _unbound_once(assessment: Assessment, project: Project) -> Assessment:
    """The claims' assessment without `numbers.unbound` where the coverage section counts the
    manuscript's unbound numbers, so they are reported, and `--max-unbound` applied, in one
    place. Where coverage counts none, having no ledger, the claims section keeps them."""
    if not project.coverage.numbers:
        return assessment
    kept = tuple(v for v in assessment.violations if v.rule != UNBOUND_RULE)
    if len(kept) == len(assessment.violations):
        return assessment
    return Assessment(
        policy=assessment.policy,
        violations=kept,
        passed=not any(v.severity is Severity.ERROR for v in kept),
    )


def _strict_said(failures: tuple[Violation, ...], policy: Policy) -> str:
    """` (default policy; strict: 2 failures)`, or nothing where strict would add none."""
    if not failures:
        return ""
    named = "default policy" if policy.name == "publication" else f"policy {policy.name}"
    return f" ({named}; strict: {len(failures)} failure{'' if len(failures) == 1 else 's'})"


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


def sections(
    project: Project, found: dict[str, bool | None], stricter: tuple[Violation, ...] = ()
) -> dict:
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
        "coverage": {"passed": project.coverage.passed, **project.coverage.model_dump(mode="json")},
        "project": {
            "root": project.root,
            "checks": words(project, found),
            "exit_code": exit_code(found),
            "strict_failures": [v.model_dump(mode="json") for v in stricter],
        },
    }


def _tool_lines(run: ci.ToolRun) -> list[str]:
    if not run.command:
        return [f"  {run.check:<12} not used here: {run.output}"]
    said = " ".join(run.command)
    if run.outcome == audit.PASSED:
        missed = ci.unchecked(run)
        note = f", {ci.verified(run)}: {missed} not checked" if missed else ""
        # What the tool itself flagged without failing, such as a freeze held to an access
        # floor lowered after the fact, so a pass does not hide it.
        flagged = [f"      note: {n}" for n in (run.account or {}).get("notes", [])]
        return [f"  {run.check:<12} passed{note}  ({said})", *flagged, *_resealed(run)]
    lines = [f"  {run.check:<12} {run.outcome.upper()} (exit {run.exit})  ({said})"]
    return lines + [f"      {line}" for line in run.output.rstrip().splitlines()]


def _resealed(run: ci.ToolRun) -> list[str]:
    """Each path `results verify` passed as RESEALED, which a passing line would hide: a path
    recorded under more than one hash is one a reader should see, though it does not fail."""
    if run.check != "results":
        return []
    paths = [
        f.get("path", "?")
        for account in (run.account, *run.account.get("nested", []))
        for f in account.get("files", [])
        if f.get("state") == "resealed"
    ]
    return [f"      RESEALED   {path}  recorded under more than one hash" for path in paths]


def _project_text(
    project: Project,
    policy: Policy,
    found: dict[str, bool | None],
    claims: str = "",
    stricter: tuple[Violation, ...] = (),
    explain: bool = False,
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
    if project.coverage.used:
        print("\n".join(manuscript.lines(project.coverage, policy.name)))

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
    print("\n".join(_summary(project, found, policy, stricter, explain)))


def _summary(
    project: Project,
    found: dict[str, bool | None],
    policy: Policy = STRICT,
    stricter: tuple[Violation, ...] = (),
    explain: bool = False,
) -> list[str]:
    """How many checks passed, the others by their word, and the sections not used. Where all
    passed, how many findings `strict` would fail, and with `explain` each of them."""
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
            + (_strict_said(stricter, policy) if not by_word else "")
        )
        if explain and stricter and not by_word:
            lines += [f"  strict: {v.rule}  {v.subject}  {v.detail[:70]}" for v in stricter]
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
        project = check(root, None, policy, getattr(args, "max_unbound", None))
        found = verdicts(None, project)
        stricter = strict_failures(project, policy)
        listed = survey(root)
        if args.format == "json":
            print(
                json.dumps(
                    {
                        "schema_version": SURVEY_SCHEMA,
                        "manifest": None,
                        "verified": 0,
                        "survey": listed.model_dump(mode="json"),
                        **sections(project, found, stricter),
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
                stricter=stricter,
                explain=args.explain,
            )
        return exit_code(found)

    manifest, report, policy, assessment = _checked(args, path)
    project = check(root, manifest, policy, getattr(args, "max_unbound", None))
    assessment = _unbound_once(assessment, project)
    found = verdicts(assessment.passed, project)
    stricter = strict_failures(project, policy, report)
    if args.format == "sarif":
        sarif = to_sarif(report, assessment, version=__version__)
        print(json.dumps(_with_checks(sarif, project, found), indent=2))
    elif args.format == "json":
        print(
            json.dumps(
                {
                    "report": report.model_dump(mode="json"),
                    "assessment": assessment.model_dump(mode="json"),
                    **sections(project, found, stricter),
                },
                indent=2,
            )
        )
    else:
        _verify_text(path, report, policy, assessment)
        _project_text(project, policy, found, stricter=stricter, explain=args.explain)
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
    "ledger claim naming a freeze no frozen plan records; and, where the project keeps a claims "
    "directory or a ledger, every quotation the manuscript makes that nothing pins and every "
    "number it prints that no run binds, a warning by default and a failure under strict. A "
    "record the project does not keep "
    "is named as not used and is not run. Executes nothing a manifest declares and reaches no "
    "network. Exits 0 where every check that ran passed, 1 where one failed or could not "
    "check, and 2 where nothing was checked. `claims verify` checks the claims alone."
)


def add_parser(sub: argparse._SubParsersAction) -> argparse.ArgumentParser:
    # `claims.cli.add_verify` holds the options, so `repro verify` and `claims verify` take the
    # same ones and write the same record of checks. `--explain` is this command's own.
    parser = add_verify(
        sub,
        func=command,
        summary="check the claims and every other record this project keeps, in one pass",
        description=DESCRIPTION,
        target=f"{DEFAULT_NAME}, or the project's directory (default: the {DEFAULT_NAME} here "
        "or above)",
    )
    parser.add_argument(
        "--explain",
        action="store_true",
        help="where every check passed under a policy other than strict, list each finding "
        "strict would fail; the summary line counts them either way",
    )
    return parser


__all__ = [
    "SECTIONS",
    "CrossTool",
    "Project",
    "Staleness",
    "add_parser",
    "check",
    "command",
    "exit_code",
    "strict_failures",
    "verdicts",
]
