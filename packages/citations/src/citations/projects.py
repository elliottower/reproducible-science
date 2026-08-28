"""What a project name in this library refers to, and whether anything still answers to it.

A record carries `cited_by: {project: {key: ...}}`, and `papers.yaml` maps a project to the
bibliography and claims it is built from. The two drift: a repository is renamed and every
record goes on naming the old one, or `papers.yaml` keeps an entry for a paper that no longer
exists. Ninety records in this library name `evaluation-scope`, which was renamed hours before
this was written, and nothing reported it.

The distinction the statuses exist to hold is that **a name the registry does not know is not
the same as a name nothing answers to.** `papers.yaml` says of itself that nothing writes to it
automatically, so an unregistered project is usually a project someone did not get round to
registering, and its records are fine. Reporting those together with genuinely orphaned names
would put three false positives beside every real one, and a report that cries wolf is read as
noise.

One limit is in every verdict here and cannot be removed: **this looks at one machine.** A
library travels and a project may live on another checkout, so `ORPHANED` says nothing here
answers to the name, never that the project is gone. That is why it is worded as it is, and why
nothing in this module edits a record on its own evidence.
"""

from __future__ import annotations

import argparse
import collections
import enum
import pathlib
from dataclasses import dataclass, field

import yaml
from provenance_core import try_run

from citations import paths
from citations.exceptions import CitationsError

#: Where projects are looked for when the registry does not place them. Sibling directories of
#: the library, which is the arrangement every project in this registry actually uses.
SIBLINGS = "siblings"

#: Keys in a `papers.yaml` entry that declare something about the project rather than name a
#: path. Excluded from the path check, which would otherwise read `archived: true` as a file.
DECLARED = frozenset({"archived", "imported"})


class Status(enum.StrEnum):
    """What is known about one project name, and what would settle it."""

    ACTIVE = "active"
    """Registered, the paths it declares are here, and records cite it. Nothing to do."""

    UNCITED = "uncited"
    """Registered and present, and no record names it. Not a defect: a paper may be registered
    before its first citation is recorded. Reported because the reverse -- a registry entry kept
    for a paper nobody cites any more -- looks identical and is worth a glance."""

    DANGLING = "dangling"
    """Registered, and a path it declares is not on this machine. `citations build` reads those
    paths, so a build will skip this project and say nothing about why."""

    UNREGISTERED = "unregistered"
    """Records name it, the registry does not, and a directory of that name is here. Ordinary:
    `papers.yaml` is written by hand. The fix is a registry entry, and until then `citations
    build` does not refresh this project's records."""

    ARCHIVED = "archived"
    """Registered, declared archived, and its paths may or may not still be here.

    An older project whose records stay valid and whose repository nobody is maintaining. Said
    in `papers.yaml` and never inferred: a path being absent is what `dangling` means, and
    guessing that absence meant "retired on purpose" would silence the case the survey exists
    to raise. Declared, this stops being a question; undeclared, it stays one."""

    IMPORTED = "imported"
    """Registered as an import: its records came from a bibliography that is not a project here.

    A reference list read out of somebody else's paper, brought in so its works have records.
    There is no repository, no claims, and no successor, so `orphaned` -- which asks a person
    what the name became -- has no answer and never will. Said in `papers.yaml`, for the same
    reason `archived` is: absence is what the other statuses already mean."""

    ORPHANED = "orphaned"
    """Records name it, the registry does not, and nothing on this machine answers to the name.

    A rename usually. It cannot be settled from here -- the project may exist on another
    checkout -- so this names a question rather than a fault, and the answer is a person's."""


@dataclass(frozen=True)
class Project:
    """One project name, everything found about it, and the status that follows."""

    name: str
    status: Status
    records: int = 0
    registered: bool = False
    missing_paths: tuple[str, ...] = ()
    directory: pathlib.Path | None = None

    @property
    def needs_a_person(self) -> bool:
        """Whether a human decision is required, as opposed to a mechanical one.

        `ORPHANED` and `DANGLING` are the two: nothing here can say what a vanished name became.
        """
        return self.status in (Status.ORPHANED, Status.DANGLING)


@dataclass
class Survey:
    """Every project name this library refers to, by status."""

    projects: list[Project] = field(default_factory=list)

    def by_status(self, status: Status) -> list[Project]:
        return [p for p in self.projects if p.status is status]

    @property
    def unresolved(self) -> list[Project]:
        """The ones that need a person, worst first."""
        return sorted(
            (p for p in self.projects if p.needs_a_person), key=lambda p: (-p.records, p.name)
        )


def registry(library: pathlib.Path) -> dict[str, dict]:
    """The `papers.yaml` mapping, or empty where there is none."""
    path = library / "papers.yaml"
    if not path.exists():
        return {}
    try:
        loaded = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:
        raise CitationsError(f"{path}: not valid YAML: {e}") from e
    return loaded.get("papers") or {}


def _expand(value: str, library: pathlib.Path) -> pathlib.Path:
    p = pathlib.Path(str(value)).expanduser()
    return p if p.is_absolute() else (library / p)


def citing_projects(library: pathlib.Path) -> collections.Counter[str]:
    """How many records name each project, read from every record's `cited_by`."""
    counts: collections.Counter[str] = collections.Counter()
    for record in (library / "records").glob("*.yaml"):
        try:
            loaded = yaml.safe_load(record.read_text()) or {}
        except yaml.YAMLError:
            continue
        for project in loaded.get("cited_by") or {}:
            counts[str(project)] += 1
    return counts


def survey(library: pathlib.Path, search: pathlib.Path | None = None) -> Survey:
    """Every project name the library refers to, with what is known about each.

    `search` is where an unregistered name is looked for; the library's parent by default,
    which is where every project in this registry sits.
    """
    library = pathlib.Path(library).resolve()
    search = (search or library.parent).resolve()
    known = registry(library)
    cited = citing_projects(library)

    out: list[Project] = []
    for name, cfg in sorted(known.items()):
        missing = tuple(
            f"{kind}: {value}"
            for kind, value in (cfg or {}).items()
            if kind not in DECLARED and not _expand(str(value), library).exists()
        )
        n = cited.get(name, 0)
        if (cfg or {}).get("imported"):
            status = Status.IMPORTED
        elif (cfg or {}).get("archived"):
            status = Status.ARCHIVED
        elif missing:
            status = Status.DANGLING
        else:
            status = Status.ACTIVE if n else Status.UNCITED
        out.append(Project(name, status, records=n, registered=True, missing_paths=missing))

    for name, n in sorted(cited.items()):
        if name in known:
            continue
        here = search / name
        out.append(
            Project(
                name,
                Status.UNREGISTERED if here.is_dir() else Status.ORPHANED,
                records=n,
                directory=here if here.is_dir() else None,
            )
        )
    return Survey(out)


def rename(library: pathlib.Path, old: str, new: str) -> list[pathlib.Path]:
    """Move every record's `cited_by` entry from `old` to `new`, returning what changed.

    Only ever called with both names given. Nothing here infers a successor from a similar
    directory: `evaluation-scope` sits beside `evaluation-warrant`, `evaluation-warrant-paper`
    and `evaluation-warrant-working`, and picking one by string distance would rewrite 90
    records on a guess.

    A record already carrying `new` keeps it, and the `old` entry is dropped rather than
    overwriting what is there.
    """
    changed: list[pathlib.Path] = []
    for record in sorted((library / "records").glob("*.yaml")):
        text = record.read_text()
        loaded = yaml.safe_load(text) or {}
        cited = loaded.get("cited_by") or {}
        if old not in cited:
            continue
        entry = cited.pop(old)
        cited.setdefault(new, entry)
        loaded["cited_by"] = cited
        record.write_text(yaml.safe_dump(loaded, sort_keys=False, width=100, allow_unicode=True))
        changed.append(record)
    return changed


def _render(found: Survey) -> None:
    print(f"  {'status':<14}{'records':>8}  project")
    for status in Status:
        for proj in sorted(found.by_status(status), key=lambda p: -p.records):
            note = f"   {proj.missing_paths[0]}" if proj.missing_paths else ""
            print(f"  {proj.status:<14}{proj.records:>8}  {proj.name}{note}")


def main(argv: list[str] | None = None) -> int:
    """`citations projects`: what this library refers to, and what nothing answers to."""
    ap = argparse.ArgumentParser(
        prog="citations projects",
        description=__doc__.split("\n")[0],
        epilog=(
            "A name the registry does not know is not the same as a name nothing answers to, "
            "and `unregistered` and `orphaned` hold those apart. Nothing here infers a "
            "successor for a vanished name: --rename takes both."
        ),
    )
    ap.add_argument("--library", help="the library to survey (default: the resolved one)")
    ap.add_argument("--rename", metavar="OLD=NEW", help="move every cited_by entry from OLD to NEW")
    a = ap.parse_args(argv)

    library = pathlib.Path(a.library).expanduser() if a.library else paths.home()

    if a.rename:
        old, _, new = a.rename.partition("=")
        if not old or not new:
            print("--rename takes OLD=NEW, both named. Nothing here infers a successor.")
            return 2
        changed = rename(library, old, new)
        print(f"  {len(changed)} record(s) moved from {old} to {new}")
        for path in changed[:8]:
            print(f"      {path.name}")
        if len(changed) > 8:
            print(f"      ... and {len(changed) - 8} more")
        return 0

    found = survey(library)
    print(f"{library}\n")
    _render(found)

    unresolved = found.unresolved
    if not unresolved:
        print("\nevery project name resolves.")
        return 0
    print(f"\n{len(unresolved)} name(s) a person has to settle:")
    for proj in unresolved:
        if proj.status is Status.ORPHANED:
            print(f"  {proj.name}: {proj.records} record(s) name it, nothing here answers")
            print(
                f"      when you know what it became: citations projects --rename {proj.name}=NEW"
            )
        else:
            print(
                f"  {proj.name}: registered, {len(proj.missing_paths)} declared path(s) are not "
                f"on this machine"
            )
            print("      `citations build` skips it and says nothing about why")
    return 1


def uncommitted(library: pathlib.Path) -> int:
    """How many records in the library are not committed. Zero where git cannot answer.

    A record is a pin: a digest, a citation, and the claim that this artifact is the one the
    quotation came from. Uncommitted, it exists on one machine and nothing can appeal to it
    later -- which is what `prereg` already says of a freeze, that it is only evidence once it
    is in history. The same holds here and nothing said so.

    Counted, not blocked. A library mid-edit is the ordinary state of working in one, and a
    tool that refused to verify against it would be wrong far more often than right.
    """
    if not (library / ".git").exists():
        return 0
    out = try_run("status", "--porcelain", "--", "records", cwd=library)
    return len([ln for ln in (out or "").splitlines() if ln.strip()])
