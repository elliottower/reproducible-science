"""A project's own result files and manuscript, read into a draft manifest and its open items.

`repro init`, run inside a project that has no `repro.yaml`, reads what `repro verify` reads
there with no manifest: the result files and the one manuscript `claims.starter.scan` finds,
the numbers the manuscript prints, and the places in the result files whose value agrees with
each. The scan states which files there are and which digits agree. It does not state which
sentence reports which value. So the reader writes what the scan states and opens an item for
each number:

- every result file found and the manuscript become artifacts, pinned by sha256 under the ids
  `repro manifest init` gives them. A file that is a symbolic link, or resolves outside the
  project, is not read or declared, and a Git LFS pointer is declared without a pin, each
  listed as not checked with the reason;
- every number the scan reads (`claims.starter.Scan.printed`) becomes a claim whose text is
  the sentence holding it, across line breaks, with no evidence, and one item asking for the
  address of its value in a result file. A Markdown or text manuscript's numbers are those
  `repro verify` compares with no manifest. A LaTeX manuscript's are read from its source
  lines (`claims.starter.tex_lines`), so a number in a table or in inline math is one, and its
  line is the line of the source;
- each item lists as candidates every place the scan found the number in a result file, as
  the inferred assertion that would read it there. They are never written into the draft.

The draft declares no assertion, so every claim stays open and the draft fails `strict` and
`publication` until an author or an agent fills it. An item is `unique` where exactly one
candidate passes the guards the CORE-Bench reader applies (`claims.sources.corebench`): the
value carries at least three significant digits and is not an integer below 1000, every label
the line names among the address's sibling keys, column names or row labels is the address's
own, and every split the line names (test, train, validation) is among the address's words.
The words read for a number are those before it in its own clause, at most `QUESTION_WORDS`:
from the last comma, semicolon, colon, parenthesis or table cell before it, or the number
before it in the same sentence, so `test loss was 0.931` names `loss` and not the `accuracy`
of an earlier clause. Where those words name no label of any candidate and no split, the
whole sentence is read instead, so `Accuracy, measured on the held-out split, was 0.931.` is
read with `Accuracy`. A number in a table row is read with the row's label.
A candidate in an index-like column or key (`claims.starter`), or in a file whose labels the
CORE-Bench reader does not read, never passes. A unique candidate is a lead, never a binding.

Nothing is written through a symbolic link: an output path that is one, dangling or not, or
that resolves outside the project, is refused.
"""

from __future__ import annotations

import json
import pathlib
import re

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
    QUALIFIERS,
    SMALL_INTEGER,
    Refused,
    Stored,
    _names,
    _stored,
    _words,
    labels_agree,
    qualifiers_agree,
    specific,
)
from claims.starter import Candidate, _pins, scan

READER = "repro init"
FORMAT = "a project's result files and manuscript"

#: At most this many candidates are listed for one item; the context says how many there were.
MAX_CANDIDATES = 20
#: At most this many words before a number are read for the labels it names.
QUESTION_WORDS = 8
#: A sentence longer than this is no sentence the reader could find, and its line is used.
MAX_SENTENCE = 400

#: A line that stands alone: a heading, or a row of a table.
_ALONE = re.compile(r"^\s*(?:#|\|)|\s\|\s")
#: The end of a sentence: a full stop, question or exclamation mark before a space.
_END = re.compile(r"[.!?](?=\s|$)")
#: Where a clause starts.
_BOUNDARY = re.compile(r"[,;:(|]")


class NothingToScaffoldError(ReproError):
    """The project holds no result file or no manuscript, so there is nothing to draft."""


class ScaffoldExistsError(ReproError):
    """A draft or an open-items file is already in the project, and `--force` was not given."""


class ScaffoldRefusedError(ReproError):
    """An output path is a symbolic link or resolves outside the project."""


def present(root: pathlib.Path) -> list[str]:
    """The scaffold's files already in the project, a symbolic link at either name included."""
    return [
        name
        for name in (DRAFT_NAME, ITEMS_NAME)
        if (root / name).exists() or (root / name).is_symlink()
    ]


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


def _names_a_label(words: str, places: list[_Place]) -> bool:
    """Whether the words name a label of any place's label sets, or a split."""
    said = _words(words)
    if any(set(said) & split for split in QUALIFIERS):
        return True
    return any(
        _names(said, label)
        for place in places
        if place.stored is not None
        for _, members in place.stored.labels
        for label in members
    )


def _read_words(question: str, sentence: str, places: list[_Place]) -> str:
    """The words the guards read: the number's own clause, or the whole sentence where the
    clause names no label and no split, so `Accuracy, measured on the held-out split, was
    0.931.` is read with `Accuracy`."""
    return question if _names_a_label(question, places) else sentence


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
    question: str,
    manuscript: str,
    places: list[_Place],
    ids: dict[str, str],
    compared: bool,
) -> OpenItem:
    value = number.value or ""
    read_words = _read_words(question, line, places)
    ordered, reason = _guarded(read_words, value, places)
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
            "words_before": question,
            "words_read": read_words,
            "candidates_found": len(ordered),
        },
        candidates=tuple(
            _assertion(claim_id, value, place, ids) for place in ordered[:MAX_CANDIDATES]
        ),
        unique=bool(ordered) and not reason,
        reason=reason,
    )


class _Said(BaseModel):
    """Where a number stands in the manuscript: the sentence holding it, and the words before
    it in its own clause."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sentence: str
    words_before: str


def _paragraphs(lines: list[str]) -> dict[int, tuple[int, int]]:
    """For each line, from 0, the paragraph it is in, and where it starts in that paragraph's
    text: the lines joined with single spaces, a blank line, a heading or a table row ending a
    paragraph, and a heading or a table row being one of its own."""
    where: dict[int, tuple[int, int]] = {}
    paragraph, at = -1, 0
    for index, line in enumerate(lines):
        text = line.strip()
        alone = bool(_ALONE.search(line))
        if not text or alone or index == 0 or index - 1 not in where:
            paragraph, at = paragraph + 1, 0
        if not text:
            continue
        where[index] = (paragraph, at)
        at += len(text) + 1
        if alone:
            paragraph, at = paragraph + 1, 0
    return where


def _said(lines: list[str], printed: tuple[PrintedNumber, ...]) -> list[_Said | None]:
    """Each number's sentence and the words before it, or None where its digits are not found
    on its line."""
    where = _paragraphs(lines)
    texts: dict[int, str] = {}
    for index, (paragraph, _) in sorted(where.items()):
        joined = texts.get(paragraph)
        texts[paragraph] = (
            lines[index].strip() if joined is None else f"{joined} {lines[index].strip()}"
        )
    cursor: dict[int, int] = {}
    last_end: dict[int, int] = {}
    said: list[_Said | None] = []
    for number in printed:
        index = (number.line or 0) - 1
        needle = number.text.rstrip("%").lstrip("+-\u2212")
        if index not in where or not needle:
            said.append(None)
            continue
        line = lines[index].strip()
        found = line.find(needle, cursor.get(index, 0))
        if found == -1:
            said.append(None)
            continue
        cursor[index] = found + len(needle)
        paragraph, start = where[index]
        text = texts[paragraph]
        pos, end = start + found, start + found + len(needle)
        ends = list(_END.finditer(text))
        begin = max((m.end() for m in ends if m.end() <= pos), default=0)
        close = min((m.end() for m in ends if m.start() >= end), default=len(text))
        sentence = text[begin:close].strip()
        boundaries = [m.end() for m in _BOUNDARY.finditer(text, 0, pos)]
        clause = max(begin, last_end.get(paragraph, 0), *boundaries)
        last_end[paragraph] = end
        before = text[clause:pos]
        if " | " in line and not re.search(r"\d", label := line.split(" | ")[0]):
            # A table row: the row's label is what names its cells.
            before = label
        words = [word for word in before.split() if re.search(r"\w", word)][-QUESTION_WORDS:]
        said.append(
            _Said(
                sentence=sentence if len(sentence) <= MAX_SENTENCE else line,
                words_before=" ".join(words),
            )
        )
    return said


def _refuse_links(root: pathlib.Path) -> None:
    for name in (DRAFT_NAME, ITEMS_NAME):
        path = root / name
        if path.is_symlink():
            raise ScaffoldRefusedError(
                f"{name} is a symbolic link, and nothing is written through one"
            )
        if path.exists() and not inside(root, path):
            raise ScaffoldRefusedError(f"{name} resolves outside the project")


def from_project(root: pathlib.Path, overwrite: bool = False) -> Scaffold:
    """Write the draft and the open items the project at `root` gives into `root`.

    Raises `ScaffoldRefusedError` where either output path is a symbolic link or resolves
    outside the project, `ScaffoldExistsError` where either file is there and `overwrite` is
    not given, and `NothingToScaffoldError` where the scan finds no result file or no
    manuscript. Nothing is written in any of these cases, and `repro.yaml` is never read or
    written.
    """
    _refuse_links(root)
    if not overwrite and (here := present(root)):
        names = " and ".join(here)
        raise ScaffoldExistsError(
            f"{names} {'is' if len(here) == 1 else 'are'} already here and "
            f"{'was' if len(here) == 1 else 'were'} not replaced; --force replaces "
            f"{DRAFT_NAME} and {ITEMS_NAME}"
        )

    found = scan(root, tex_source=True)
    survey = found.survey
    results = [path for paths in survey.results.values() for path in paths]
    if survey.manuscript is None or not results:
        missing = "no manuscript" if survey.manuscript is None else "no result file"
        raise NothingToScaffoldError(f"{missing} found")

    link = "a symbolic link, which is not followed"
    not_checked = [PassedOver(file=path, reason=link) for path in found.links]
    pinned, unpinned = [], []
    for relative in (*results, survey.manuscript):
        path = root / relative
        if path.is_symlink() or not inside(root, path):
            not_checked.append(PassedOver(file=relative, reason=link))
        elif is_lfs_pointer(path):
            reason = "a Git LFS pointer: the file's content is not here, so it is not checked"
            not_checked.append(PassedOver(file=relative, reason=reason))
            unpinned.append(relative)
        else:
            pinned.append(relative)
    if survey.manuscript not in pinned:
        reason = next(p.reason for p in not_checked if p.file == survey.manuscript)
        raise NothingToScaffoldError(f"the manuscript {survey.manuscript} is {reason}")
    declared = [*pinned, *unpinned]
    artifacts = _pins([root / path for path in declared], root)
    for artifact in artifacts:
        if artifact["path"] in unpinned:
            del artifact["digest"]
    ids = {artifact["path"]: artifact["id"] for artifact in artifacts}

    if found.lines:
        lines = list(found.lines)
    else:
        try:
            lines = extract_uncached(root / survey.manuscript).split("\n")
        except SourceUnreadableError as e:
            raise NothingToScaffoldError(
                f"{survey.manuscript} could not be read: {e.detail}"
            ) from e

    readable = [path for path in results if path in pinned]
    labelled = _labelled(root, readable)
    by_number: dict[int, list[Candidate]] = {}
    for candidate in survey.candidates:
        if candidate.path in readable:
            by_number.setdefault(candidate.offset, []).append(candidate)

    claims, items = [], []
    on_line: dict[int | None, int] = {}
    for position, (number, said) in enumerate(
        zip(found.printed, _said(lines, found.printed), strict=True)
    ):
        on_line[number.line] = on_line.get(number.line, 0) + 1
        if number.line is not None and 0 < number.line <= len(lines):
            claim_id = f"line-{number.line}-{on_line[number.line]}"
            where = f"{survey.manuscript}, line {number.line}"
        else:
            claim_id = f"number-{position + 1}"
            where = survey.manuscript
        if said is None:
            text = lines[number.line - 1].strip() if number.line else number.context.strip(". ")
            question = number.context
        else:
            text, question = said.sentence, said.words_before
        claims.append({"id": claim_id, "text": text, "where": where})
        places = _places(by_number.get(number.offset, []), labelled)
        compared = position < survey.compared
        items.append(
            _item(claim_id, number, text, question, survey.manuscript, places, ids, compared)
        )

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
