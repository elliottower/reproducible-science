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

import pathlib
import shlex
from collections.abc import Callable

import yaml
from claims.manifest import find, load
from claims.models import Manifest
from claims.origins import origins as check_origins
from claims.reruns import RECORD as RERUNS
from claims.reruns import reruns as read_reruns
from claims.starter import project_root
from provenance_core.chain import ChainError, read_ledger
from provenance_core.gitref import try_run
from pydantic import BaseModel, ConfigDict

from repro import badges, crosscheck

#: Where `results` keeps its ledger, from the top of the project.
LEDGER = badges.LEDGER

#: The file a project names its archived release in, where it names one.
CITATION = "CITATION.cff"

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

LICENSE_FILES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING")
README_FILES = ("README.md", "README.rst", "README.txt", "README")


class Finding(BaseModel):
    """One fact, and the record it was read from."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    record: str
    """The record, as a path from the top of the project, or `git config` for the remote."""
    said: str
    """The fact, in words generated from the record."""


class Project(BaseModel):
    """The project whose records are read: its top, and its manifest where it has one."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    root: pathlib.Path
    manifest: Manifest | None = None

    @classmethod
    def at(cls, cwd: pathlib.Path) -> Project:
        """The project holding `cwd`, with the manifest that governs it, if any."""
        root = project_root(cwd)
        path = find(cwd)
        return cls(root=root, manifest=load(path) if path is not None else None)

    def shown(self, path: pathlib.Path) -> str:
        """A path as named from the top of the project."""
        path = path.resolve()
        return (
            path.relative_to(self.root).as_posix() if path.is_relative_to(self.root) else str(path)
        )

    @property
    def manifest_record(self) -> str:
        assert self.manifest is not None and self.manifest.path is not None
        return self.shown(self.manifest.path)


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
    events = _events(project)
    if isinstance(events, list):
        bound = [event for event in events if event.get("event") == "claim"]
        if bound:
            confirmatory = sum(bool(event.get("confirmatory")) for event in bound)
            found.append(
                Finding(
                    record=LEDGER.as_posix(),
                    said=(
                        f"binds {_plural(len(bound), 'claim')} to recorded runs, "
                        f"{confirmatory} of them confirmatory"
                    ),
                )
            )
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
                said=f"`{record.id}` runs `{shlex.join(record.command)}` and writes {writes}",
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
                f"`{check.artifact_id}` was copied from {check.origin.repository} at commit "
                f"{check.origin.commit[:12]}, path {check.origin.path}; origin check: "
                f"{check.state.value} ({check.reason})"
            ),
        )
        for check in report.origins
    )


# ---------------------------------------------------------------------- the record of re-runs


def _latest_reruns(project: Project):
    """The last re-run of each declared command, by id, with the invocation it was part of."""
    if project.manifest is None or project.manifest.path is None:
        return {}
    latest = {}
    for report in read_reruns(project.manifest.path.resolve().parent):
        for state in report.regenerations:
            latest[state.regeneration_id] = (report, state)
    return latest


def _rerun_record(project: Project) -> str:
    assert project.manifest is not None and project.manifest.path is not None
    return project.shown(project.manifest.path.resolve().parent / RERUNS)


def reruns(project: Project) -> tuple[Finding, ...]:
    """The outcome of the last re-run of each declared command."""
    latest = _latest_reruns(project)
    if not latest:
        return ()
    record = _rerun_record(project)
    found = []
    for regeneration_id, (report, state) in sorted(latest.items()):
        when = f" on {report.started_at[:10]}" if report.started_at else ""
        took = f", {state.duration_seconds:.1f} s" if state.duration_seconds is not None else ""
        found.append(
            Finding(
                record=record,
                said=f"`{regeneration_id}` last re-run{when}: {state.state.value}{took}",
            )
        )
    return tuple(found)


def rerun_time(project: Project) -> tuple[Finding, ...]:
    """How long the last re-run of each declared command took, added up."""
    latest = _latest_reruns(project)
    timed = [state.duration_seconds for _, state in latest.values() if state.duration_seconds]
    if not timed:
        return ()
    return (
        Finding(
            record=_rerun_record(project),
            said=(
                f"the last re-run of {_plural(len(timed), 'declared command')} took "
                f"{sum(timed):.1f} s in total"
            ),
        ),
    )


def rerun_environment(project: Project) -> tuple[Finding, ...]:
    """Where the most recent re-run ran, as its record says."""
    latest = _latest_reruns(project)
    if not latest:
        return ()
    report = max((report for report, _ in latest.values()), key=lambda r: r.started_at)
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


def _events(project: Project) -> list[dict] | str | None:
    """The ledger's events, None where there is no ledger, or the reason it could not be read."""
    path = project.root / LEDGER
    if not path.is_file():
        return None
    try:
        return read_ledger(path)
    except ChainError as e:
        return str(e)


def ledger(project: Project) -> tuple[Finding, ...]:
    """How many runs the ledger records, and how many had their inputs sealed before them."""
    events = _events(project)
    if events is None:
        return ()
    if isinstance(events, str):
        return (Finding(record=LEDGER.as_posix(), said=f"could not be read: {events}"),)
    counted = badges.runs(events)
    seals = sum(event.get("event") == "seal" for event in events)
    return (
        Finding(
            record=LEDGER.as_posix(),
            said=(
                f"records {_plural(seals, 'seal')} of inputs and "
                f"{_plural(counted.runs, 'run')}, {counted.sealed} of them recorded after a seal"
            ),
        ),
    )


def plans(project: Project) -> tuple[Finding, ...]:
    """Each plan frozen with `prereg`, and the commit it was frozen at."""
    return tuple(
        Finding(
            record=project.shown(freeze.path),
            said=f"frozen at commit {freeze.ref[:12]}",
        )
        for freeze in crosscheck.frozen_plans(project.root)
    )


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


def archive(project: Project) -> tuple[Finding, ...]:
    """The DOI `CITATION.cff` names, at its top level or among its identifiers."""
    data = _citation(project)
    dois = [str(data["doi"])] if data.get("doi") else []
    for identifier in data.get("identifiers") or ():
        if isinstance(identifier, dict) and identifier.get("type") == "doi":
            value = str(identifier.get("value", ""))
            if value and value not in dois:
                dois.append(value)
    return tuple(Finding(record=CITATION, said=f"names DOI {doi}") for doi in dois)


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
        Finding(record=name, said=f"is present; its first line reads `{_first_line(path)}`")
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


def remote(project: Project) -> tuple[Finding, ...]:
    """The repository `git remote get-url origin` names."""
    url = (try_run("remote", "get-url", "origin", cwd=project.root) or "").strip()
    return (Finding(record="git config", said=f"remote `origin` is {url}"),) if url else ()


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
    "license": licenses,
    "environment": environment,
    "documentation": documentation,
    "remote": remote,
}


__all__ = ["READERS", "Finding", "Project"]
