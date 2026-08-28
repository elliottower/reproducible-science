"""A closed vocabulary of tags, and which records carry them.

`cited_by` groups a record by which paper cites it, and it is derived: `citations build` reads
the bibliographies and rewrites it, so it cannot drift from what the papers actually cite. A
tag has no such source. None of the 1,202 entries across this registry's bibliographies carries
a `keywords` field, so a tag is something a person asserts and nothing regenerates.

That is the whole design problem. Declared metadata with no forcing function goes stale
quietly, and free-text tags go stale fastest of all: `ai-safety` and `ai-saftey` are two tags,
both plausible, and nothing notices. So the vocabulary is closed. `tags.yaml` names every tag
that may be used and what it means, and a tag the vocabulary does not name is reported as an
error rather than accepted as a new tag. A typo becomes a finding.

The second half is where a tag is written. Tagging records directly, a project at a time, puts
on each record exactly what `cited_by` already says -- and then stops being true, because the
next fifty records the project cites do not get it and nothing notices. So a tag goes on the
*paper*, in `papers.yaml`, and reaches records through `cited_by`, which `citations build`
maintains. One line covers 377 records and cannot drift from them.

A record may still carry its own `tags`, for the work whose subject is not its citing paper's
and for the 232 records no paper cites at all. Its tags add to the ones it inherits.

Hierarchy is the `/` in a name and nothing more. `ai-safety/governance` sits under `ai-safety`
because of the separator, so a tree needs no second structure to declare and cannot disagree
with the names. Counts roll up by *record*: a work tagged both `ai-safety/governance` and
`ai-safety/evaluation` counts once under `ai-safety`, because the question the count answers is
how many works the tag covers.
"""

from __future__ import annotations

import argparse
import enum
import pathlib
from dataclasses import dataclass, field

import yaml

from citations import paths, projects
from citations.exceptions import CitationsError

#: The vocabulary file, at the library root beside `papers.yaml`.
VOCABULARY = "tags.yaml"

#: What separates a tag from its parent. A tag is a path, and the tree is read off the name.
SEP = "/"


@dataclass(frozen=True)
class Tag:
    """One declared tag: its full name, what it means, and where it sits."""

    name: str
    description: str = ""

    @property
    def depth(self) -> int:
        return self.name.count(SEP)

    @property
    def parent(self) -> str | None:
        head, sep, _ = self.name.rpartition(SEP)
        return head if sep else None

    def covers(self, other: str) -> bool:
        """Whether `other` is this tag or sits beneath it."""
        return other == self.name or other.startswith(self.name + SEP)


class Kind(enum.StrEnum):
    """What a name in the tree is, which is not the same as whether it was written down."""

    DECLARED = "declared"
    """Named in `tags.yaml`. The only kind a record may carry."""

    NAMESPACE = "namespace"
    """A level implied by a declared name, like `ai-safety` under `ai-safety/governance`.

    Not written down anywhere and not a defect. Reporting it as undeclared would put a
    finding on every parent in the tree, which is the report crying wolf on its own
    structure."""

    UNDECLARED = "undeclared"
    """On a record, named by no vocabulary. The finding this module exists to produce."""


@dataclass
class Use:
    """One tag as the library actually uses it."""

    tag: str
    kind: Kind
    records: set[str] = field(default_factory=set)

    @property
    def count(self) -> int:
        return len(self.records)


def vocabulary(library: pathlib.Path) -> dict[str, Tag]:
    """Every declared tag, by name. Empty where the library declares none.

    A tag may be declared with a description or with nothing; `ai-safety:` on its own is a
    tag whose meaning is its name.
    """
    path = pathlib.Path(library) / VOCABULARY
    if not path.exists():
        return {}
    try:
        loaded = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:
        raise CitationsError(f"{path}: not valid YAML: {e}") from e
    declared = loaded.get("tags") or {}
    if not isinstance(declared, dict):
        raise CitationsError(f"{path}: `tags` must be a mapping of name to description")
    return {str(k): Tag(str(k), str(v or "")) for k, v in declared.items()}


def namespaces(names: set[str]) -> set[str]:
    """Every prefix implied by a declared name, so a tree can show the levels between.

    Declaring `ai-safety/governance` and `ai-safety/evaluation` and nothing called `ai-safety`
    still means there is an `ai-safety` level. It is shown, and it is not applicable: only a
    declared name may be put on a record.
    """
    out: set[str] = set()
    for name in names:
        parts = name.split(SEP)
        for i in range(1, len(parts)):
            out.add(SEP.join(parts[:i]))
    return out - names


def project_tags(library: pathlib.Path) -> dict[str, list[str]]:
    """What each paper in `papers.yaml` is tagged with. The primary place a tag is written."""
    out: dict[str, list[str]] = {}
    for name, cfg in (projects.registry(pathlib.Path(library)) or {}).items():
        declared = (cfg or {}).get("tags") or []
        if isinstance(declared, str):
            raise CitationsError(
                f"papers.yaml: {name}: `tags` must be a list, not a string. "
                f"Write `tags: [{declared}]`."
            )
        out[str(name)] = [str(t) for t in declared]
    return out


def record_tags(library: pathlib.Path) -> dict[str, list[str]]:
    """What each record carries in its own `tags`, by slug. The exception, not the rule."""
    out: dict[str, list[str]] = {}
    for record in sorted((pathlib.Path(library) / "records").glob("*.yaml")):
        try:
            loaded = yaml.safe_load(record.read_text()) or {}
        except yaml.YAMLError:
            continue
        own = loaded.get("tags") or []
        if own:
            out[record.stem] = [str(t) for t in own]
    return out


def effective(library: pathlib.Path) -> dict[str, set[str]]:
    """Every tag each record has, inherited from its citing papers plus its own.

    A record cited by three papers inherits all three papers' tags. This is derived on every
    read and written nowhere, which is what stops it from going stale.
    """
    library = pathlib.Path(library)
    by_project = project_tags(library)
    own = record_tags(library)

    out: dict[str, set[str]] = {}
    for record in sorted((library / "records").glob("*.yaml")):
        try:
            loaded = yaml.safe_load(record.read_text()) or {}
        except yaml.YAMLError:
            continue
        tags = set(own.get(record.stem, ()))
        for project in loaded.get("cited_by") or {}:
            tags |= set(by_project.get(str(project), ()))
        if tags:
            out[record.stem] = tags
    return out


def applied(library: pathlib.Path) -> dict[str, set[str]]:
    """Which records carry each tag, inheritance included."""
    out: dict[str, set[str]] = {}
    for slug, tags in effective(library).items():
        for tag in tags:
            out.setdefault(tag, set()).add(slug)
    return out


def total_records(library: pathlib.Path) -> int:
    return len(list((pathlib.Path(library) / "records").glob("*.yaml")))


def survey(library: pathlib.Path) -> list[Use]:
    """Every tag the library declares or uses, with the records covered, roll-ups included.

    A declared tag with no records is kept: a vocabulary entry nothing uses is worth seeing,
    and dropping it would make an unused tag indistinguishable from one that was never
    declared.
    """
    known = vocabulary(library)
    used = applied(library)
    levels = {n: Tag(n) for n in namespaces(set(known))}

    out: list[Use] = []
    for name, tag in sorted({**known, **levels}.items()):
        covered: set[str] = set()
        for applied_name, records in used.items():
            if tag.covers(applied_name):
                covered |= records
        out.append(Use(name, Kind.DECLARED if name in known else Kind.NAMESPACE, records=covered))

    for name, records in sorted(used.items()):
        if name not in known and name not in levels:
            out.append(Use(name, Kind.UNDECLARED, records=set(records)))
    return out


def undeclared_in_registry(library: pathlib.Path) -> dict[str, set[str]]:
    """Tags `papers.yaml` puts on a paper that the vocabulary does not name, by tag."""
    known = set(vocabulary(library))
    out: dict[str, set[str]] = {}
    for project, tags in project_tags(library).items():
        for tag in tags:
            if tag not in known:
                out.setdefault(tag, set()).add(project)
    return out


def undeclared_on_records(library: pathlib.Path) -> dict[str, set[str]]:
    """Tags a record carries itself that the vocabulary does not name, by tag."""
    known = set(vocabulary(library))
    out: dict[str, set[str]] = {}
    for slug, tags in record_tags(library).items():
        for tag in tags:
            if tag not in known:
                out.setdefault(tag, set()).add(slug)
    return out


def undeclared(library: pathlib.Path) -> dict[str, set[str]]:
    """Every tag the vocabulary does not name, wherever it is used. The check this exists for."""
    out = {k: set(v) for k, v in undeclared_in_registry(library).items()}
    for tag, slugs in undeclared_on_records(library).items():
        out.setdefault(tag, set()).update(slugs)
    return out


def untagged(library: pathlib.Path) -> int:
    """How many records no tag reaches, inherited or their own."""
    return total_records(library) - len(effective(library))


def _selected(library: pathlib.Path, cited_by: str) -> list[pathlib.Path]:
    """Records a query picks out. Only ever called with a query: see `apply`."""
    out = []
    for record in sorted((pathlib.Path(library) / "records").glob("*.yaml")):
        try:
            loaded = yaml.safe_load(record.read_text()) or {}
        except yaml.YAMLError:
            continue
        if cited_by in (loaded.get("cited_by") or {}):
            out.append(record)
    return out


def apply(
    library: pathlib.Path, tag: str, cited_by: str, remove: bool = False
) -> list[pathlib.Path]:
    """Put `tag` on every record a query picks out, or take it off. Returns what changed.

    A query is required and there is no "everything" query. Tagging is a bulk write over
    hundreds of files -- the case this exists for puts one tag on 384 records -- and a command
    that could do that to the whole library on a missing argument is a command that will.

    Removal exists for the same reason: the undo for a bulk write has to be as cheap as the
    write, or a mistaken one gets repaired by hand across 384 files.
    """
    library = pathlib.Path(library)
    known = vocabulary(library)
    if tag not in known and not remove:
        raise CitationsError(
            f"{tag!r} is not in {VOCABULARY}. Declare it there first -- an undeclared tag is "
            f"how `ai-safety` and `ai-saftey` both come to exist."
        )

    changed: list[pathlib.Path] = []
    for record in _selected(library, cited_by):
        loaded = yaml.safe_load(record.read_text()) or {}
        current = [str(t) for t in (loaded.get("tags") or [])]
        wanted = [t for t in current if t != tag] if remove else sorted({*current, tag})
        if wanted == current:
            continue
        if wanted:
            loaded["tags"] = wanted
        else:
            loaded.pop("tags", None)
        record.write_text(yaml.safe_dump(loaded, sort_keys=False, width=100, allow_unicode=True))
        changed.append(record)
    return changed


def _render(uses: list[Use], total: int) -> None:
    print(f"  {'records':>8}  tag")
    for use in uses:
        indent = "  " * use.tag.count(SEP)
        mark = "   undeclared" if use.kind is Kind.UNDECLARED else ""
        print(f"  {use.count:>8,}  {indent}{use.tag}{mark}")
    print(f"\n  {total:,} record(s) in the library")


def main(argv: list[str] | None = None) -> int:
    """`citations tags`: what the vocabulary declares, what the records use, and the gap."""
    ap = argparse.ArgumentParser(
        prog="citations tags",
        description=__doc__.split("\n")[0],
        epilog=(
            "A tag is declared in tags.yaml or it is an error. Nothing derives tags from the "
            "bibliographies -- no entry in them carries a keywords field -- so the closed "
            "vocabulary is the only thing standing between this and free text."
        ),
    )
    ap.add_argument("--library", help="the library to read (default: the resolved one)")
    ap.add_argument("--add", metavar="TAG", help="put TAG on every record the query selects")
    ap.add_argument("--remove", metavar="TAG", help="take TAG off every record the query selects")
    ap.add_argument("--cited-by", metavar="PROJECT", help="the query: records that PROJECT cites")
    a = ap.parse_args(argv)

    library = pathlib.Path(a.library).expanduser() if a.library else paths.home()

    if a.add or a.remove:
        if not a.cited_by:
            print("--add and --remove need a query. --cited-by PROJECT is the one there is.")
            return 2
        tag = a.add or a.remove
        changed = apply(library, tag, a.cited_by, remove=bool(a.remove))
        verb = "removed from" if a.remove else "put on"
        print(f"  {tag} {verb} {len(changed)} record(s) cited by {a.cited_by}")
        return 0

    uses = survey(library)
    print(f"{library}\n")
    if not uses:
        print(f"no tags declared. Write {VOCABULARY} to start one.")
        return 0
    _render(uses, total_records(library))

    tagged_papers = {p: t for p, t in project_tags(library).items() if t}
    if tagged_papers:
        print(f"\n  from {len(tagged_papers)} tagged paper(s) in papers.yaml:")
        # Derived, so a project name longer than a written-down width cannot weld itself to
        # its tags. `cross-design-evidence-discordance` is 33 characters and did exactly that.
        width = max(len(p) for p in tagged_papers) + 2
        for project, tags in sorted(tagged_papers.items()):
            print(f"    {project:<{width}}{', '.join(sorted(tags))}")
    own = record_tags(library)
    if own:
        print(f"\n  {len(own)} record(s) also carry a tag of their own")

    blank = untagged(library)
    if blank:
        print(f"  {blank:,} of them carry no tag")

    in_registry = undeclared_in_registry(library)
    on_records = undeclared_on_records(library)
    if not in_registry and not on_records:
        return 0
    total = len(set(in_registry) | set(on_records))
    print(f"\n{total} tag(s) no vocabulary declares:")
    for name, papers_using in sorted(in_registry.items()):
        print(f"  {name}: on {', '.join(sorted(papers_using))} in papers.yaml")
        print(f"      declare it in {VOCABULARY}, or correct the entry")
    for name, slugs in sorted(on_records.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        print(f"  {name}: on {len(slugs)} record(s)")
        print(f"      declare it in {VOCABULARY}, or take it off with --remove")
    return 1
