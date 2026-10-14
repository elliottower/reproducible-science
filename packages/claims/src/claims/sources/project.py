"""A project's own result files and manuscript, read into a draft manifest and its open items.

`repro init`, run inside a project that has no `repro.yaml`, reads what `repro verify` reads
there with no manifest: the result files and the one manuscript `claims.starter.scan` finds,
the numbers the manuscript prints, and the places in the result files whose value agrees with
each. The scan states which files there are and which digits agree. It does not state which
sentence reports which value. So the reader writes what the scan states and opens an item for
each number:

- every result file found and the manuscript become artifacts, pinned by sha256 under the ids
  `repro manifest init` gives them. A file that resolves outside the project, through a
  symbolic link, is passed over, and a Git LFS pointer is declared without a pin, each with
  the reason;
- every number the scan compares or would compare (`claims.starter.Scan.printed`) becomes a
  claim whose text is its line as the manuscript prints it, with no evidence, and one item
  asking for the address of its value in a result file;
- each item lists as candidates every place the scan found the number in a result file, as
  the inferred assertion that would read it there. They are never written into the draft.

The draft declares no assertion, so every claim stays open and the draft fails `strict` and
`publication` until an author or an agent fills it. An item is `unique` where exactly one
candidate passes the guards the CORE-Bench reader applies (`claims.sources.corebench`): the
value carries at least three significant digits and is not an integer below 1000, every label
the line names among the address's sibling keys, column names or row labels is the address's
own, and every split the line names (test, train, validation) is among the address's words.
A candidate in an index-like column or key (`claims.starter`), or in a file whose labels the
CORE-Bench reader does not read, never passes. A unique candidate is a lead, never a binding.
"""

from __future__ import annotations

import json
import pathlib

from citations.exceptions import SourceUnreadableError
from citations.verify import extract_uncached
from pydantic import BaseModel, ConfigDict

from claims import __version__
from claims.exceptions import ReproError
from claims.models import SCHEMA_VERSION, Basis, Digest, PrintedNumber, ValueEvidence
from claims.open_items import DRAFT_NAME, ITEMS_NAME, Need, OpenItem, Source, write_draft
from claims.sources import PassedOver, Written, inside, is_lfs_pointer
from claims.sources.corebench import (
    MIN_SIGNIFICANT,
    SMALL_INTEGER,
    Refused,
    Stored,
    _stored,
    labels_agree,
    qualifiers_agree,
    specific,
)
from claims.starter import Candidate, _pins, scan

READER = "repro init"
FORMAT = "a project's result files and manuscript"

#: At most this many candidates are listed for one item; the context says how many there were.
MAX_CANDIDATES = 20


class NothingToScaffoldError(ReproError):
    """The project holds no result file or no manuscript, so there is nothing to draft."""


class ScaffoldExistsError(ReproError):
    """A draft or an open-items file is already in the project, and `--force` was not given."""


class Scaffold(BaseModel):
    """What one scaffolding wrote."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    written: Written
    manuscript: str
    results: tuple[str, ...]
    open: int
    """Numbers left open: one per claim, and every claim is open."""
    unique: int
    """Items with exactly one candidate passing the guards."""


class _Place(BaseModel):
    """One place a printed number agrees with, and the labels its address carries."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    locator: dict[str, str | int]
    candidate: Candidate
    stored: Stored | None
    """As the CORE-Bench reader reads the address, or None where it reads no labels for it."""


def _key(path: str, locator: dict) -> str:
    return json.dumps([path, locator], sort_keys=True)


def _labelled(root: pathlib.Path, paths: list[str]) -> dict[str, Stored]:
    """Every number of these files as the CORE-Bench reader reads it, by file and locator. A
    file it refuses, or reads no labels from, gives nothing."""
    found = {}
    for path in paths:
        try:
            read = _stored(path, root / path)
        except Refused:
            continue
        for stored in read:
            found[_key(path, stored.locator)] = stored
    return found


def _places(candidates: list[Candidate], labelled: dict[str, Stored]) -> list[_Place]:
    """Each candidate, and every other place it stands for, as a place of its own."""
    places = []
    for candidate in candidates:
        for locator in (candidate.locator, *(also.locator for also in candidate.also)):
            places.append(
                _Place(
                    path=candidate.path,
                    locator=locator,
                    candidate=candidate,
                    stored=labelled.get(_key(candidate.path, locator)),
                )
            )
    return places


def _guarded(question: str, value: str, places: list[_Place]) -> tuple[list[_Place], str]:
    """The places, any that pass the guards first, and why none is unique, if none is."""
    if not places:
        return [], "no address in the result files matches"
    if not specific(value):
        return places, (
            f"{value} has fewer than {MIN_SIGNIFICANT} significant digits or is an integer "
            f"below {SMALL_INTEGER}, so a match of it may be chance"
        )
    readable = [p for p in places if p.stored is not None and not p.candidate.index_like]
    if not readable:
        return places, (
            "every match is in an index-like column or key, or in a file whose labels are not "
            "read, so none is called unique"
        )
    passing = [
        place
        for place in readable
        if place.stored is not None
        and labels_agree(question, place.stored.labels)
        and qualifiers_agree(question, place.stored.words)
    ]
    others = [place for place in places if place not in passing]
    if not passing:
        return places, "the line names a label or a split no matching address carries"
    if len(passing) > 1:
        return passing + others, f"{len(passing)} addresses pass the guards, not one"
    return passing + others, ""


def _assertion(claim_id: str, value: str, place: _Place, ids: dict[str, str]) -> dict:
    return ValueEvidence(
        artifact=ids[place.path],
        name=claim_id,
        reported=value,
        locator=place.locator,
        conversion=place.candidate.conversion,
        basis=Basis.INFERRED,
    ).model_dump(mode="json")


def _item(
    claim_id: str,
    number: PrintedNumber,
    line: str,
    manuscript: str,
    places: list[_Place],
    ids: dict[str, str],
    compared: bool,
) -> OpenItem:
    value = number.value or ""
    ordered, reason = _guarded(line, value, places)
    if not compared:
        reason = "not compared: the survey stopped at its limit of comparisons"
    where = f"on line {number.line}" if number.line is not None else "in its text"
    return OpenItem(
        id=f"{claim_id}/value",
        claim=claim_id,
        need=Need.VALUE,
        asks=f"the address in a result file of the value {manuscript} prints as "
        f"{number.text} {where}",
        context={
            "printed": number.text,
            "value": value,
            "percent": number.text.endswith("%"),
            "line": number.line,
            "text": line,
            "candidates_found": len(ordered),
        },
        candidates=tuple(
            _assertion(claim_id, value, place, ids) for place in ordered[:MAX_CANDIDATES]
        ),
        unique=bool(ordered) and not reason,
        reason=reason,
    )


def from_project(root: pathlib.Path, overwrite: bool = False) -> Scaffold:
    """Write the draft and the open items the project at `root` gives into `root`.

    Raises `NothingToScaffoldError` where the scan finds no result file or no manuscript, and
    `ScaffoldExistsError` where either file is there and `overwrite` is not given. Nothing is
    written in either case, and `repro.yaml` is never read or written.
    """
    if not overwrite:
        present = [name for name in (DRAFT_NAME, ITEMS_NAME) if (root / name).exists()]
        if present:
            raise ScaffoldExistsError(f"{' and '.join(present)} already here")

    found = scan(root)
    survey = found.survey
    results = [path for paths in survey.results.values() for path in paths]
    if survey.manuscript is None or not results:
        missing = "no manuscript" if survey.manuscript is None else "no result file"
        raise NothingToScaffoldError(f"{missing} found")

    not_checked: list[PassedOver] = []
    pinned, unpinned = [], []
    for relative in (*results, survey.manuscript):
        path = root / relative
        if not inside(root, path):
            not_checked.append(PassedOver(file=relative, reason="a link out of the project"))
        elif is_lfs_pointer(path):
            reason = "a Git LFS pointer: the file's content is not here, so it is not checked"
            not_checked.append(PassedOver(file=relative, reason=reason))
            unpinned.append(relative)
        else:
            pinned.append(relative)
    if survey.manuscript not in pinned:
        raise NothingToScaffoldError(f"{survey.manuscript} is not a file of the project to read")
    declared = [*pinned, *unpinned]
    artifacts = _pins([root / path for path in declared], root)
    for artifact in artifacts:
        if artifact["path"] in unpinned:
            del artifact["digest"]
    ids = {artifact["path"]: artifact["id"] for artifact in artifacts}

    try:
        lines = extract_uncached(root / survey.manuscript).split("\n")
    except SourceUnreadableError as e:
        raise NothingToScaffoldError(f"{survey.manuscript} could not be read: {e.detail}") from e

    readable = [path for path in results if path in pinned]
    labelled = _labelled(root, readable)
    by_number: dict[int, list[Candidate]] = {}
    for candidate in survey.candidates:
        if candidate.path in readable:
            by_number.setdefault(candidate.offset, []).append(candidate)

    claims, items = [], []
    on_line: dict[int | None, int] = {}
    for position, number in enumerate(found.printed):
        on_line[number.line] = on_line.get(number.line, 0) + 1
        if number.line is not None and 0 < number.line <= len(lines):
            claim_id = f"line-{number.line}-{on_line[number.line]}"
            line = lines[number.line - 1].strip()
            where = f"{survey.manuscript}, line {number.line}"
        else:
            claim_id = f"number-{position + 1}"
            line = number.context.strip(". ")
            where = survey.manuscript
        claims.append({"id": claim_id, "text": line, "where": where})
        places = _places(by_number.get(number.offset, []), labelled)
        compared = position < survey.compared
        items.append(_item(claim_id, number, line, survey.manuscript, places, ids, compared))

    draft = {
        "schema_version": SCHEMA_VERSION,
        "project": root.name,
        "provenance": {"generated_by": READER},
        "artifacts": artifacts,
        "claims": claims,
    }
    source = Source(
        reader=READER,
        reader_version=__version__,
        format=FORMAT,
        path=survey.manuscript,
        digest=Digest.of_file(root / survey.manuscript).value,
        pins={
            artifact["path"]: artifact["digest"]["value"]
            for artifact in artifacts
            if "digest" in artifact and artifact["path"] != survey.manuscript
        },
    )
    written = write_draft(root, draft, source, tuple(items), overwrite=overwrite)
    return Scaffold(
        written=Written(
            open_items=written.as_posix(),
            draft=(written.parent / DRAFT_NAME).as_posix(),
            artifacts=len(artifacts),
            pinned=sum("digest" in artifact for artifact in artifacts),
            claims=len(claims),
            items=len(items),
            not_checked=tuple(not_checked),
        ),
        manuscript=survey.manuscript,
        results=tuple(readable),
        open=len(items),
        unique=sum(item.unique for item in items),
    )
