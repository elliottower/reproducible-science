"""What a repository records, read as findings a venue's questions can be answered from.

A finding is one fact and the record it was read from: `repro.yaml` declares three claims,
`.repro/reproductions.jsonl` says a command was re-run on a date and took so long, the
ledger counts runs sealed before they were recorded. Nothing here judges a fact, and nothing
here writes prose about what a fact means: whether a re-run makes a paper reproducible is the
authors' sentence to write, and a reader of the draft must be able to tell their sentence from
this module's.

Each reader takes the project and returns its findings, empty where the project keeps no
record of that kind. `READERS` names them, and a venue says which of them bear on each of its
questions. Reaches no network: an origin is compared only with a local clone.
"""

from __future__ import annotations

import json
import pathlib
import re
import shlex
import urllib.parse
from collections.abc import Callable

import yaml
from claims.manifest import find, load
from claims.models import (
    Freshness,
    Manifest,
    RegenerationNode,
    RegenerationState,
    ReproductionReport,
)
from claims.origins import origins as check_origins
from claims.reruns import RECORD as RERUNS
from claims.reruns import reruns as read_reruns
from claims.stale import stale
from claims.starter import project_root
from prereg import record as prereg_record
from prereg.cli import _plans_below as plans_below
from prereg.cli import frozen_digest
from provenance_core.chain import ChainError, ChainStatus, read_ledger, verify
from provenance_core.gitref import try_run
from pydantic import BaseModel, ConfigDict

from repro import badges, crosscheck
from repro.exceptions import ReproError

#: Where `results` keeps its ledger, from the top of the project.
LEDGER = badges.LEDGER

#: The file a project names its archived release in, where it names one.
CITATION = "CITATION.cff"
CODEMETA = "codemeta.json"

#: A DOI, as `CITATION.cff` or `codemeta.json` writes one, bare or as a doi.org address.
DOI = re.compile(r"\b10\.\d{4,9}/[^\s\"'<>]+")
#: A suffix a template leaves in place of a DOI: a run of X, TBD or TODO, a run of zeros, or
#: a placeholder in angle brackets or braces.
PLACEHOLDER = re.compile(r"(?i)x{3,}|tbd|todo|(?<!\d)0{4,}(?!\d)|[<>{}]")
#: Zenodo's DOI prefix, whose suffix is `zenodo.` and the record's number.
ZENODO = re.compile(r"(?i)10\.5281/zenodo\.\d+")


def real_dois(values: list[str]) -> list[str]:
    """Each DOI in `values` that is not a template's placeholder, once. A Zenodo DOI must
    name a record by its number."""
    found = []
    for value in values:
        for match in DOI.finditer(value):
            doi = match.group(0).rstrip(".,;)")
            suffix = doi.split("/", 1)[1]
            if PLACEHOLDER.search(suffix):
                continue
            if doi.startswith("10.5281/") and not ZENODO.fullmatch(doi):
                continue
            found.append(doi)
    return list(dict.fromkeys(found))


#: A Software Heritage persistent identifier, without its qualifiers.
SWHID = re.compile(r"\bswh:1:(?:cnt|dir|rev|rel|snp):[0-9a-f]{40}\b")

#: Said beside every repository a record names: whether it is public is not in any record.
CONFIRM_PUBLIC = "author: confirm this repository is public"

#: Files that pin or describe a software environment, by the name they are found under at the
#: top of a project. Presence is what is recorded; what they pin is not read.
ENVIRONMENT_FILES = (
    "uv.lock",
    "pixi.lock",
    "poetry.lock",
    "Pipfile.lock",
    "requirements.txt",
    "environment.yml",
    "environment.yaml",
    "renv.lock",
    "Manifest.toml",
    "flake.lock",
    "package-lock.json",
    "Dockerfile",
)

#: Folders whose plans are not the project's own: a test fixture or a worked example is frozen
#: to exercise the tool, and reporting it would register a study nobody ran.
NOT_THE_PROJECTS = frozenset({"tests", "test", "testdata", "fixtures", "fixture", "examples"})

LICENSE_FILES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING")
README_FILES = ("README.md", "README.rst", "README.txt", "README")


class Finding(BaseModel):
    """One fact, and the record it was read from."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    record: str
    """The record, as a path from the top of the project, or `git config` for the remote."""
    said: str
    """The fact, in words generated from the record."""


class PlanMissingError(ReproError):
    """`--plan` names a file that is not there."""

    def __init__(self, path: pathlib.Path) -> None:
        self.path = path
        super().__init__(f"--plan {path}: no such file")


class Project(BaseModel):
    """The project whose records are read: its top, and its manifest where it has one."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    root: pathlib.Path
    manifest: Manifest | None = None
    plan: pathlib.Path | None = None
    """The plan named on the command line. None to find plans as `prereg check` does."""

    @classmethod
    def at(cls, cwd: pathlib.Path, plan: pathlib.Path | None = None) -> Project:
        """The project holding `cwd`, with the manifest that governs it, if any."""
        root = project_root(cwd)
        path = find(cwd)
        if plan is not None and not plan.is_file():
            raise PlanMissingError(plan)
        return cls(
            root=root,
            manifest=load(path) if path is not None else None,
            plan=plan.resolve() if plan is not None else None,
        )

    def plans(self) -> list[pathlib.Path]:
        """The plan named, or every `PREREG.md` `prereg check` finds at or below the top,
        leaving out those under a folder of tests, fixtures or examples."""
        if self.plan is not None:
            return [self.plan]
        return [
            path
            for path in plans_below(self.root)
            if not NOT_THE_PROJECTS & set(path.relative_to(self.root).parts[:-1])
        ]

    def shown(self, path: pathlib.Path) -> str:
        """A path as named from the top of the project, or by its name alone where it lies
        outside, so no absolute local path reaches a draft."""
        path = path.resolve()
        return (
            path.relative_to(self.root).as_posix() if path.is_relative_to(self.root) else path.name
        )

    @property
    def manifest_record(self) -> str:
        assert self.manifest is not None and self.manifest.path is not None
        return self.shown(self.manifest.path)


def code(text: str) -> str:
    """`text` as a Markdown code span: fenced by one more backtick than the longest run inside
    it, and padded with a space where it starts or ends with one, so a backtick in a command
    cannot close the span early."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * (longest + 1)
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{pad}{text}{pad}{fence}"


#: A Markdown code span: a run of backticks, the content, and a run of the same length.
_SPAN = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.S)


def spans(text: str) -> list[tuple[bool, str]]:
    """Text split into its code spans and the text between, each marked whether it is code,
    as `code` writes them. A renderer other than Markdown sets each part in its own way."""
    parts, at = [], 0
    for match in _SPAN.finditer(text):
        if match.start() > at:
            parts.append((False, text[at : match.start()]))
        inner = match.group(2)
        if len(inner) > 1 and inner.startswith(" ") and inner.endswith(" "):
            inner = inner[1:-1]
        parts.append((True, inner))
        at = match.end()
    if at < len(text):
        parts.append((False, text[at:]))
    return parts


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


# ------------------------------------------------------------------------------- the manifest


def claims(project: Project) -> tuple[Finding, ...]:
    """How many claims the manifest declares and how many artifacts it pins, and how many
    claims the ledger binds to a run."""
    found = []
    if project.manifest is not None:
        manifest = project.manifest
        pinned = sum(artifact.is_pinned for artifact in manifest.artifacts)
        found.append(
            Finding(
                record=project.manifest_record,
                said=(
                    f"declares {_plural(len(manifest.claims), 'claim')} and "
                    f"{_plural(len(manifest.artifacts), 'artifact')}, {pinned} of them pinned "
                    "by sha256"
                ),
            )
        )
    _, events = _ledger(project)
    bound = [event for event in events if event.get("event") == "claim"]
    if bound:
        runs = {event.get("run_id") for event in events if event.get("event") == "run"}
        named = [event for event in bound if event.get("run_id") in runs]
        confirmatory = sum(bool(event.get("confirmatory")) for event in named)
        said = (
            f"binds {_plural(len(named), 'claim')} to runs it records, "
            f"{confirmatory} of them confirmatory"
        )
        if len(named) < len(bound):
            more = len(bound) - len(named)
            said += f"; {more} more {'names' if more == 1 else 'name'} a run it does not record"
        found.append(Finding(record=LEDGER.as_posix(), said=said))
    return tuple(found)


def regenerations(project: Project) -> tuple[Finding, ...]:
    """Each command the manifest declares, with the file it writes."""
    manifest = project.manifest
    if manifest is None:
        return ()
    found = []
    for record in manifest.regenerations:
        artifact = manifest.artifact(record.output.artifact)
        writes = artifact.path.as_posix() if artifact is not None else record.output.artifact
        found.append(
            Finding(
                record=project.manifest_record,
                said=f"{code(record.id)} runs {code(shlex.join(record.command))} and writes {writes}",
            )
        )
    if found:
        found.append(
            Finding(
                record=project.manifest_record,
                said="`repro reproduce` runs each declared command again",
            )
        )
    return tuple(found)


def origins(project: Project) -> tuple[Finding, ...]:
    """Each artifact the manifest says was copied from another repository, and whether the
    bytes at that origin are the pinned bytes. Only a local clone is read."""
    manifest = project.manifest
    if manifest is None or not any(artifact.origin for artifact in manifest.artifacts):
        return ()
    report = check_origins(manifest)
    return tuple(
        Finding(
            record=project.manifest_record,
            said=(
                f"{code(check.artifact_id)} was copied from {check.origin.repository} at commit "
                f"{check.origin.commit[:12]}, path {check.origin.path}; origin check: "
                f"{check.state.value} ({check.reason})"
            ),
        )
        for check in report.origins
    )


# ---------------------------------------------------------------------- the record of re-runs


def _rerun_record(project: Project) -> str:
    assert project.manifest is not None and project.manifest.path is not None
    return project.shown(project.manifest.path.resolve().parent / RERUNS)


def _freshness(project: Project) -> list[tuple[RegenerationNode, ReproductionReport | None]]:
    """Each declared command as `repro stale` finds it, with the invocation it compared, if
    any. A re-run of a command the manifest no longer declares is not here."""
    manifest = project.manifest
    if manifest is None or manifest.path is None or not manifest.regenerations:
        return []
    by_start = {r.started_at: r for r in read_reruns(manifest.path.resolve().parent)}
    return [
        (node, by_start.get(node.rerun_at) if node.rerun_at else None)
        for node in stale(manifest).regenerations
    ]


def _entry(node: RegenerationNode, report: ReproductionReport | None) -> RegenerationState | None:
    if report is None:
        return None
    return next((e for e in report.regenerations if e.regeneration_id == node.id), None)


def reruns(project: Project) -> tuple[Finding, ...]:
    """Whether each declared command's output is still what a recorded re-run produced, as
    `repro stale` decides it, and when that re-run was."""
    nodes = _freshness(project)
    if not nodes:
        return ()
    found = []
    for node, report in nodes:
        state = node.state.value.replace("_", " ")
        entry = _entry(node, report)
        if node.state is Freshness.CURRENT and report is not None:
            took = (
                f", {entry.duration_seconds:.1f} s"
                if entry is not None and entry.duration_seconds is not None
                else ""
            )
            said = f"{code(node.id)}: current; reproduced by the re-run on {report.started_at[:10]}{took}"
        elif node.rerun_at:
            said = f"{code(node.id)}: {state}; the re-run compared was on {node.rerun_at[:10]}"
        else:
            said = f"{code(node.id)}: {state}"
        found.append(Finding(record=_rerun_record(project), said=said))
    return tuple(found)


def _current(project: Project) -> list[tuple[ReproductionReport, RegenerationState]]:
    """The re-run each current declared command was reproduced by."""
    found = []
    for node, report in _freshness(project):
        entry = _entry(node, report)
        if node.state is Freshness.CURRENT and report is not None and entry is not None:
            found.append((report, entry))
    return found


def rerun_time(project: Project) -> tuple[Finding, ...]:
    """How long the re-runs that are current took, added up."""
    timed = [e.duration_seconds for _, e in _current(project) if e.duration_seconds is not None]
    if not timed:
        return ()
    return (
        Finding(
            record=_rerun_record(project),
            said=(
                f"the current re-runs of {_plural(len(timed), 'declared command')} took "
                f"{sum(timed):.1f} s in total"
            ),
        ),
    )


def rerun_environment(project: Project) -> tuple[Finding, ...]:
    """Where the most recent current re-run ran, as its record says."""
    current = _current(project)
    if not current:
        return ()
    report = max((report for report, _ in current), key=lambda r: r.started_at)
    env = report.environment
    parts = [
        " ".join(part for part in (env.system, env.release, env.machine) if part),
        f"Python {env.python}" if env.python else "",
        f"GPUs: {', '.join(env.gpus)}" if env.gpus else "no GPU reported",
        f"lockfile {env.lockfile}" if env.lockfile else "",
    ]
    said = "; ".join(part for part in parts if part)
    when = f" on {report.started_at[:10]}" if report.started_at else ""
    return (Finding(record=_rerun_record(project), said=f"the re-run{when} ran on {said}"),)


# -------------------------------------------------------------------- the ledger and the plan


def _ledger(project: Project) -> tuple[ChainStatus | None, list[dict]]:
    """Whether the ledger's chain verifies, and its events. None and no events where there is
    no ledger; no events where a line is not an event."""
    path = project.root / LEDGER
    if not path.is_file():
        return None, []
    status, _ = verify(path)
    try:
        events = read_ledger(path)
    except ChainError:
        return status, []
    return status, [event for event in events if isinstance(event, dict)]


def ledger(project: Project) -> tuple[Finding, ...]:
    """Whether the ledger's chain verifies, how many runs it records, and how many had their
    inputs sealed before them."""
    status, events = _ledger(project)
    if status is None:
        return ()
    found = []
    if status is not ChainStatus.INTACT:
        found.append(
            Finding(
                record=LEDGER.as_posix(),
                said=f"does not verify as a chain: `results verify` would report {status.value}",
            )
        )
    if events:
        counted = badges.runs(events)
        seals = sum(event.get("event") == "seal" for event in events)
        found.append(
            Finding(
                record=LEDGER.as_posix(),
                said=(
                    f"records {_plural(seals, 'seal')} of inputs and "
                    f"{_plural(counted.runs, 'run')}, {counted.sealed} of them recorded after a "
                    "seal"
                ),
            )
        )
    return tuple(found)


def plans(project: Project) -> tuple[Finding, ...]:
    """Each plan frozen with `prereg`, and the commit it was frozen at. A plan never frozen
    is not listed."""
    found = []
    for path in project.plans():
        try:
            if frozen_digest(path) is None:
                continue
            whole = prereg_record.read(path)
        except prereg_record.RecordError:
            found.append(
                Finding(record=project.shown(path), said="has an unreadable freeze record")
            )
            continue
        except UnicodeDecodeError:
            found.append(Finding(record=project.shown(path), said="is not UTF-8 text"))
            continue
        if whole is not None:
            commit = whole.commit
        else:
            status = crosscheck.FROZEN_AT.search(path.read_text(encoding="utf-8"))
            commit = status.group(1) if status else ""
        said = f"frozen at commit {commit[:12]}" if commit else "frozen"
        found.append(Finding(record=project.shown(path), said=said))
    return tuple(found)


# ----------------------------------------------------------------------- files at the top


def _citation(project: Project) -> dict:
    path = project.root / CITATION
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _codemeta(project: Project) -> dict:
    path = project.root / CODEMETA
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _strings(value: object) -> list[str]:
    """Every string in a value read from YAML or JSON, however nested."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for item in value.values() for s in _strings(item)]
    if isinstance(value, list):
        return [s for item in value for s in _strings(item)]
    return []


def _swhids(values: list[str]) -> list[str]:
    return list(dict.fromkeys(m.group(0) for value in values for m in SWHID.finditer(value)))


def archive(project: Project) -> tuple[Finding, ...]:
    """This project's own archived copy: a DOI or a Software Heritage ID among its own
    identifiers in `CITATION.cff` (`doi`, and `identifiers` at the top level) or in
    `codemeta.json` (`identifier`). Cited works, references and the README are not read, and
    a GitHub or GitLab address is not an archive."""
    found = []
    citation = _citation(project)
    own = citation.get("identifiers")
    own = [item for item in own if isinstance(item, dict)] if isinstance(own, list) else []
    named = [str(citation["doi"])] if isinstance(citation.get("doi"), str | int | float) else []
    named += [str(item.get("value", "")) for item in own if item.get("type") == "doi"]
    found += [Finding(record=CITATION, said=f"names DOI {d}") for d in real_dois(named)]
    swh = _swhids([str(item.get("value", "")) for item in own if item.get("type") == "swh"])
    found += [Finding(record=CITATION, said=f"names Software Heritage ID {i}") for i in swh]
    identifier = _strings(_codemeta(project).get("identifier"))
    found += [Finding(record=CODEMETA, said=f"names DOI {d}") for d in real_dois(identifier)]
    found += [
        Finding(record=CODEMETA, said=f"names Software Heritage ID {i}")
        for i in _swhids(identifier)
    ]
    return tuple(found)


def repository(project: Project) -> tuple[Finding, ...]:
    """This project's own code repository: `repository-code` in `CITATION.cff` and
    `codeRepository` in `codemeta.json`. Whether it is public cannot be checked offline."""
    found = []
    url = _citation(project).get("repository-code")
    if isinstance(url, str) and url:
        found.append(
            Finding(record=CITATION, said=f"names repository-code {url}; {CONFIRM_PUBLIC}")
        )
    for url in dict.fromkeys(_strings(_codemeta(project).get("codeRepository"))):
        found.append(Finding(record=CODEMETA, said=f"names codeRepository {url}; {CONFIRM_PUBLIC}"))
    return tuple(found)


def _first_line(path: pathlib.Path) -> str:
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            return next((line.strip() for line in fh if line.strip()), "")
    except OSError:
        return ""


def licenses(project: Project) -> tuple[Finding, ...]:
    """The license file at the top of the project, by its first line, and the license
    `CITATION.cff` names."""
    found = [
        Finding(record=name, said=f"is present; its first line reads {code(_first_line(path))}")
        for name in LICENSE_FILES
        if (path := project.root / name).is_file()
    ]
    if named := _citation(project).get("license"):
        found.append(Finding(record=CITATION, said=f"names the license {named}"))
    return tuple(found)


def environment(project: Project) -> tuple[Finding, ...]:
    """The files at the top of the project that pin or describe a software environment."""
    return tuple(
        Finding(record=name, said="is present")
        for name in ENVIRONMENT_FILES
        if (project.root / name).is_file()
    )


def documentation(project: Project) -> tuple[Finding, ...]:
    """The README, a `docs/` folder and a citation file, where present."""
    found = []
    for name in README_FILES:
        path = project.root / name
        if path.is_file():
            lines = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
            found.append(Finding(record=name, said=f"is present, {_plural(lines, 'line')}"))
            break
    docs = project.root / "docs"
    if docs.is_dir():
        count = sum(1 for path in docs.rglob("*") if path.is_file())
        found.append(Finding(record="docs/", said=f"holds {_plural(count, 'file')}"))
    if (project.root / CITATION).is_file():
        found.append(Finding(record=CITATION, said="is present"))
    return tuple(found)


#: `user@host:path`, the scp-like address git accepts for ssh.
_SCP = re.compile(r"[^/@\s]+@([^:/\s]+):(.*)")


def without_userinfo(url: str) -> str:
    """A repository address with any user name, password or token taken out, and its query
    and fragment, which can carry a token as well."""
    if scp := _SCP.fullmatch(url):
        return f"{scp.group(1)}:{re.split(r'[?#]', scp.group(2), maxsplit=1)[0]}"
    parts = urllib.parse.urlsplit(url)
    if not parts.scheme:
        return url
    netloc = parts.netloc.rsplit("@", 1)[-1]
    return urllib.parse.urlunsplit(parts._replace(netloc=netloc, query="", fragment=""))


def remote(project: Project) -> tuple[Finding, ...]:
    """The repository `git remote get-url origin` names, with any credentials taken out.
    Whether it is public cannot be checked offline."""
    url = (try_run("remote", "get-url", "origin", cwd=project.root) or "").strip()
    if not url:
        return ()
    shown = without_userinfo(url)
    return (Finding(record="git config", said=f"remote `origin` is {shown}; {CONFIRM_PUBLIC}"),)


#: Every reader, by the name a venue uses for it.
READERS: dict[str, Callable[[Project], tuple[Finding, ...]]] = {
    "claims": claims,
    "regenerations": regenerations,
    "origins": origins,
    "reruns": reruns,
    "rerun_time": rerun_time,
    "rerun_environment": rerun_environment,
    "ledger": ledger,
    "plans": plans,
    "archive": archive,
    "repository": repository,
    "license": licenses,
    "environment": environment,
    "documentation": documentation,
    "remote": remote,
}


__all__ = ["READERS", "Finding", "Project"]
