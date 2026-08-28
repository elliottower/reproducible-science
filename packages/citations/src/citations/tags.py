"""A closed vocabulary of tags, and which records carry them.

`cited_by` groups a record by which paper cites it, and it is derived: `citations build` reads
the bibliographies and rewrites it, so it cannot drift from what the papers actually cite. A
tag has no such source. None of the 1,202 entries across this registry's bibliographies carries
a `keywords` field, so a tag is something a person asserts and nothing regenerates.

That is the whole design problem. Declared metadata with no forcing function goes stale
quietly, and free-text tags go stale fastest of all: `ai-safety` and `ai-saftey` are two tags,
both plausible, and nothing notices. So the vocabulary is closed. `tags.yaml` names every tag
that may be used and what it means, and a tag on a record that the vocabulary does not name is
reported as an error rather than accepted as a new tag. A typo becomes a finding.

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

from citations import paths
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


def applied(library: pathlib.Path) -> dict[str, set[str]]:
    """Which records carry each tag, by tag name, read from every record's `tags`."""
    out: dict[str, set[str]] = {}
    for record in sorted((pathlib.Path(library) / "records").glob("*.yaml")):
        try:
            loaded = yaml.safe_load(record.read_text()) or {}
        except yaml.YAMLError:
            continue
        for tag in loaded.get("tags") or []:
            out.setdefault(str(tag), set()).add(record.stem)
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


def undeclared(library: pathlib.Path) -> dict[str, set[str]]:
    """Tags on records that the vocabulary does not name. The check this module exists for."""
    known = set(vocabulary(library))
    return {name: recs for name, recs in applied(library).items() if name not in known}


def untagged(library: pathlib.Path) -> int:
    """How many records carry no tag at all."""
    tagged = {slug for recs in applied(library).values() for slug in recs}
    return total_records(library) - len(tagged)


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

    blank = untagged(library)
    if blank:
        print(f"  {blank:,} of them carry no tag")

    loose = undeclared(library)
    if not loose:
        return 0
    print(f"\n{len(loose)} tag(s) no vocabulary declares:")
    for name, records in sorted(loose.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        print(f"  {name}: {len(records)} record(s)")
    print(f"      declare it in {VOCABULARY}, or take it off with --remove")
    return 1
