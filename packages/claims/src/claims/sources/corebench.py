"""A CORE-Bench capsule and its task, read into a draft manifest and its open items.

A CORE-Bench task names a capsule (a published analysis's code, data and outputs, archived by
DOI) and states, for each question it asks about the analysis, the value the capsule's run
produces: `{"Report the AUC of ...": 0.9375660604380387}`. Where the capsule was run more than
once, `results` holds one such mapping per run. The task states the question and the value; it
does not say which file of the capsule holds the value, or where in it. So the reader writes
what the task states and opens an item for the address:

- every file under the capsule's `results/` in a format a backend reads is an artifact, pinned
  by sha256;
- every question is a claim whose text is the question as written, with one item: for a
  numeric answer, the address of the value in a result file, and for any other answer, the
  passage in a result file that prints it;
- each numeric answer is looked for in the pinned JSON, YAML and delimited files: every
  address at which a check of the task's value, as the task writes it, would match.

The reader binds nothing it finds. Every question is an open item, and what the search found
is listed in it as candidates, each an inferred assertion that is never written into the draft.
A candidate passes the guards where both of these hold, and the item is `unique` where exactly
one candidate passes (it is listed first), with a `reason` otherwise:

1. the value carries at least three significant digits, and is not an integer below 1000, so
   a small count that any file may hold by chance is never a lead;
2. every label of the address the question names agrees: for each set of labels the address
   is one of (the keys of a JSON mapping, a table's column names, the names in a column of
   row labels), a question that names a member of the set names the address's own.

A unique candidate is a lead for whoever fills the item, never an assumption.

Where the runs disagree, the item lists every run's value and no candidate, since no one value
is the one the task states. Nothing in the capsule is run, a file is read only by a parser that
evaluates nothing (JSON, YAML with the safe loader, delimited text), and the reading is guarded
as `claims.sources` says: no link out of the capsule, no Git LFS pointer, no YAML key twice.
"""

from __future__ import annotations

import csv
import decimal
import io
import json
import mimetypes
import os
import pathlib
import re

import yaml
from citations.verify import passage_fold
from pydantic import BaseModel, ConfigDict, ValidationError

from claims import __version__
from claims.adapters.prose import numerals
from claims.adapters.reads import reading_once
from claims.exceptions import ReproError
from claims.models import SCHEMA_VERSION, Basis, Digest, ValueEvidence
from claims.open_items import DRAFT_NAME, Need, OpenItem, Source, write_draft
from claims.resolve import stored as stored_value
from claims.sources import (
    MAX_DEPTH,
    PassedOver,
    RefusedYamlError,
    Written,
    inside,
    is_lfs_pointer,
    load_yaml,
    named,
)
from claims.verify import compare_decimal

READER = "claims from-corebench"
FORMAT = "CORE-Bench task"

#: The folder of a capsule its run writes into.
RESULTS = "results"

#: Suffixes a backend reads, by what it reads them as.
TREE = frozenset({".json", ".yaml", ".yml"})
DELIMITED = frozenset({".csv", ".tsv", ".psv"})
#: Text searched for a value through prose anchors, beside a file with no suffix that holds text.
TEXT = frozenset({".txt", ".log", ".out"})
READABLE = TREE | DELIMITED | frozenset(
    {
        ".txt", ".log", ".out", ".md", ".tex", ".html", ".htm", ".xml", ".xlsx", ".xlsm", ".xls", ".parquet",
        ".feather", ".arrow", ".dta", ".sav", ".zsav", ".rds", ".npy", ".npz", ".h5", ".hdf5",
        ".nc", ".db", ".sqlite", ".sqlite3", ".pdf",
    }
)  # fmt: skip

#: At most this many result files are pinned, in path order.
MAX_FILES = 200
#: A file larger than this is pinned and not searched for candidates.
MAX_SEARCHED_BYTES = 5_000_000
#: At most this many candidates are listed for one item; the count says how many there were.
MAX_CANDIDATES = 20


class CorebenchError(ReproError):
    """A CORE-Bench task, or the capsule it names, could not be read as one."""


class Task(BaseModel):
    """One CORE-Bench task, in the benchmark's own field names."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    capsule_id: str
    capsule_title: str = ""
    capsule_doi: str = ""
    field: str = ""
    language: str = ""
    task_prompt: str = ""
    results: tuple[dict, ...]


#: The fewest significant digits a value needs before a single match of it binds.
MIN_SIGNIFICANT = 3
#: An integer below this never binds, whatever its digits.
SMALL_INTEGER = 1000

#: One set of labels an address belongs to: its own label, and every label of the set.
Labels = tuple[tuple[str, frozenset[str]], ...]


#: Words a question may use to name which split of the data a value is of. A question naming
#: one is about that split, so an address that does not carry one of the same words is not its
#: value: "test accuracy" is not `train_acc`.
QUALIFIERS = (
    frozenset({"test", "testing"}),
    frozenset({"train", "training"}),
    frozenset({"validation", "val", "valid", "dev"}),
)

#: The largest power of ten a searched number may carry. JSON and YAML can write `1e999999999`
#: in eleven bytes, and comparing it at a printed precision takes minutes.
MAX_EXPONENT = 100

#: The longest number, in characters, a search reads. No result prints more digits than this.
MAX_LITERAL = 60

#: How much text before a number a prose candidate takes as its anchor, at most.
ANCHOR_CHARS = 40


class Refused(ReproError):
    """A result file this reader declines to search, and why."""


class Stored(BaseModel):
    """One number in a searched file: where it is, and the labels its address carries."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact: str
    locator: dict
    number: decimal.Decimal
    labels: Labels = ()
    words: tuple[str, ...] = ()
    """The words of the address's own labels and of the file's path, among which a split the
    question names must be."""


class Text(BaseModel):
    """A text file searched for a value, folded as the prose backend reads it."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    artifact: str
    path: pathlib.Path
    folded: str
    spans: tuple[tuple[int, int, decimal.Decimal], ...] = ()
    """Where each number in `folded` starts and ends, and its value, found once for every
    question asked of the file. Digits attached to a letter are a name, and a number no search
    compares (`_within`) is left out."""


def _no_key_twice(pairs: list[tuple[str, object]]) -> dict:
    keys = [key for key, _ in pairs]
    if twice := sorted({key for key in keys if keys.count(key) > 1}):
        raise CorebenchError(f"the key {twice[0]!r} is given twice")
    return dict(pairs)


def _bounded(literal: str) -> decimal.Decimal:
    number = decimal.Decimal(literal)
    if not number.is_finite() or abs(number.adjusted()) > MAX_EXPONENT:
        raise Refused(f"a number out of range, {literal[:20]}")
    return number


def _not_a_number(literal: str) -> object:
    raise Refused(f"{literal}, which is not a number")


def _json_depth(text: str) -> int:
    """How deep a JSON text nests, counted without parsing it, so a deep one is refused before
    the parser recurses into it."""
    depth = deepest = 0
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            deepest = max(deepest, depth)
        elif char in "]}":
            depth -= 1
    return deepest


def _numbers(text: str) -> object:
    """JSON with every number kept as the decimal the file writes, so `0.9375660604380387`
    stays those digits and an answer is never a binary float. Refuses a key given twice, a
    number out of range or not finite, and nesting past `MAX_DEPTH`, each as `Refused`."""
    if _json_depth(text) > MAX_DEPTH:
        raise Refused(f"nested deeper than {MAX_DEPTH}")
    try:
        return json.loads(
            text,
            parse_float=_bounded,
            parse_int=_bounded,
            parse_constant=_not_a_number,
            object_pairs_hook=_no_key_twice,
        )
    except CorebenchError as e:
        raise Refused(str(e)) from e


def task_of(raw: bytes, capsule_id: str) -> Task:
    """The task for one capsule, from a task file holding one task or a list of them."""
    try:
        document = _numbers(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise CorebenchError(f"the task file is not JSON: {e}") from e
    except Refused as e:
        raise CorebenchError(f"the task file is refused: {e}") from e
    tasks = document if isinstance(document, list) else [document]
    matching = [t for t in tasks if isinstance(t, dict) and t.get("capsule_id") == capsule_id]
    if len(matching) != 1:
        raise CorebenchError(
            f"the task file holds {len(matching)} tasks for {capsule_id}, not one; name the "
            "capsule with --capsule-id where its folder is named otherwise"
        )
    try:
        return Task.model_validate(matching[0])
    except ValidationError as e:
        raise CorebenchError(f"the task for {capsule_id} is not a CORE-Bench task: {e}") from e


def _written(value: object) -> str | None:
    """A numeric answer as the task writes it, or None for an answer that is not a number."""
    if isinstance(value, decimal.Decimal) and value.is_finite():
        return str(value)
    return None


def significant(written: str) -> int:
    """The significant digits of a printed number. Trailing zeros count after a decimal point,
    where they were printed on purpose, and not in an integer, where `100` may be a round one."""
    _, digits, exponent = decimal.Decimal(written).as_tuple()
    shown = "".join(map(str, digits)).lstrip("0")
    if isinstance(exponent, int) and exponent >= 0:
        shown = shown.rstrip("0")
    return len(shown)


def specific(written: str) -> bool:
    """Whether a value is specific enough for one match of it to bind."""
    value = decimal.Decimal(written)
    integer = value == value.to_integral_value() and "." not in written
    small = integer and abs(value) < SMALL_INTEGER
    return significant(written) >= MIN_SIGNIFICANT and not small


def _words(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[a-z0-9]+", text.lower()))


def _names(question: tuple[str, ...], label: str) -> bool:
    """Whether the question names a label: its words, in order, among the question's."""
    words = _words(label)
    if not words or not re.search(r"[a-z]", label.lower()) or len("".join(words)) < 2:
        return False
    return any(question[i : i + len(words)] == words for i in range(len(question)))


def qualifiers_agree(question: str, words: tuple[str, ...]) -> bool:
    """Whether the address carries every split the question names: `test` in a label of a
    value for a question about test accuracy."""
    asked, carried = set(_words(question)), set(words)
    return all(carried & split for split in QUALIFIERS if asked & split)


def labels_agree(question: str, labels: Labels) -> bool:
    """Whether every label set the question names a member of, it names through the address's
    own label."""
    words = _words(question)
    for own, members in labels:
        named_here = {label for label in members if _names(words, label)}
        if named_here and own not in named_here:
            return False
    return True


def _slug(text: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60].strip("-") or "question"
    name, n = base, 2
    while name in taken:
        name, n = f"{base}-{n}", n + 1
    taken.add(name)
    return name


def _pointer(keys: list[str | int]) -> str:
    return "".join("/" + str(key).replace("~", "~0").replace("/", "~1") for key in keys)


def _leaves(node: object, keys: list[str | int], labels: Labels):
    """Every number in a parsed tree, with its RFC 6901 pointer and the keys on its path, each
    with the keys beside it."""
    if isinstance(node, dict):
        siblings = frozenset(str(key) for key in node)
        for key, value in node.items():
            yield from _leaves(value, [*keys, str(key)], (*labels, (str(key), siblings)))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _leaves(value, [*keys, index], labels)
    elif isinstance(node, decimal.Decimal) or (
        isinstance(node, int | float) and not isinstance(node, bool)
    ):
        number = decimal.Decimal(str(node))
        if not number.is_finite() or abs(number.adjusted()) > MAX_EXPONENT:
            raise Refused(f"a number out of range at {_pointer(keys) or '/'}")
        yield _pointer(keys), number, labels


def _within(literal: str) -> decimal.Decimal | None:
    """A number written as text, or None where it is not one, or is one no search compares: not
    finite, longer than `MAX_LITERAL` characters, or past `MAX_EXPONENT` powers of ten. A cell
    holding `1e999999999` would otherwise take minutes to compare."""
    literal = literal.strip()
    if not literal or len(literal) > MAX_LITERAL:
        return None
    try:
        number = decimal.Decimal(literal)
    except decimal.InvalidOperation:
        return None
    if not number.is_finite() or abs(number.adjusted()) > MAX_EXPONENT:
        return None
    return number


def _number(cell: str | None) -> decimal.Decimal | None:
    return _within(cell or "")


def _table(artifact: str, text: str, delimiter: str) -> list[Stored]:
    rows = list(csv.DictReader(io.StringIO(text), delimiter=delimiter))
    columns = [column for column in (rows[0] if rows else {}) if column is not None]
    headers = frozenset(columns)
    # A column holding no number is a column of row labels.
    naming = [c for c in columns if all(_number(row.get(c)) is None for row in rows)]
    names = {c: frozenset((row.get(c) or "").strip() for row in rows) for c in naming}
    found = []
    for row_number, row in enumerate(rows):
        row_labels = tuple(((row.get(c) or "").strip(), names[c]) for c in naming)
        for column in columns:
            number = _number(row.get(column))
            if number is not None:
                found.append(
                    Stored(
                        artifact=artifact,
                        locator={"kind": "table_position", "column": column, "row": row_number},
                        number=number,
                        labels=((column, headers), *row_labels),
                    )
                )
    return found


def _own_words(artifact: str, labels: Labels) -> tuple[str, ...]:
    return tuple(word for own, _ in labels for word in _words(own)) + _words(artifact)


def _stored(artifact: str, path: pathlib.Path) -> list[Stored]:
    """Each number in a JSON, YAML or delimited file, with the locator that addresses it.
    Raises `Refused` for a file this reader declines to search, saying why."""
    suffix = path.suffix.lower()
    try:
        text = path.read_text(encoding="utf-8")
        if suffix in DELIMITED:
            delimiter = {".tsv": "\t", ".psv": "|"}.get(suffix, ",")
            found = _table(artifact, text, delimiter)
        else:
            tree = _numbers(text) if suffix == ".json" else load_yaml(text)
            found = [
                Stored(
                    artifact=artifact,
                    locator={"kind": "tree", "pointer": pointer},
                    number=number,
                    labels=labels,
                )
                for pointer, number, labels in _leaves(tree, [], ())
            ]
    except RefusedYamlError as e:
        raise Refused(str(e)) from e
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, yaml.YAMLError, csv.Error) as e:
        raise Refused(f"could not be parsed: {type(e).__name__}") from e
    except ValueError as e:
        # PyYAML builds an integer with `int`, which refuses past 4300 digits.
        raise Refused(f"a number out of range: {e}") from e
    return [
        stored.model_copy(update={"words": _own_words(artifact, stored.labels)}) for stored in found
    ]


def _text(artifact: str, path: pathlib.Path) -> Text:
    """A text file, folded as the prose backend folds it, so an anchor found here is one the
    backend finds."""
    try:
        folded = passage_fold(path.read_text("utf-8"))
        parsed: dict[str, decimal.Decimal | None] = {}
        spans = []
        for start, end, name in numerals(folded):
            literal = folded[start:end]
            if name:
                continue
            if literal not in parsed:
                parsed[literal] = _within(literal)
            if (number := parsed[literal]) is not None:
                spans.append((start, end, number))
        return Text(artifact=artifact, path=path, folded=folded, spans=spans)
    except (OSError, UnicodeDecodeError) as e:
        raise Refused(f"could not be read as text: {type(e).__name__}") from e


def _anchor(folded: str, start: int) -> str:
    """The text before a number, at most `ANCHOR_CHARS`, starting at a word."""
    window = folded[max(0, start - ANCHOR_CHARS) : start]
    if start > ANCHOR_CHARS and " " in window:
        window = window[window.index(" ") + 1 :]
    return window.strip()


def _in_text(claim_id: str, written: str, text: Text, room: int) -> tuple[list[Stored], int]:
    """The places in a text file where a check of `written` would match, as prose locators kept
    only where the prose backend resolves them to that number: at most `room` of them, and how
    many more matched and were not examined. Resolving reads the file, once per verification
    that `reading_once` holds open."""
    found: list[Stored] = []
    beyond = 0
    printed = ValueEvidence(
        artifact=text.artifact,
        name=claim_id,
        reported=written,
        locator={"kind": "prose", "before": "-"},
    )
    target = decimal.Decimal(written)
    # Anything further from the printed value than one unit of its last place cannot round to
    # it, so most numbers in a long log are passed over before the comparison proper, and each
    # distinct numeral is compared once however often the log prints it.
    exponent = target.as_tuple().exponent
    near = decimal.Decimal(1).scaleb(exponent if isinstance(exponent, int) else 0)
    compared: dict[str, bool] = {}
    for start, end, number in text.spans:
        if abs(number - target) > near:
            continue
        literal = text.folded[start:end]
        if literal not in compared:
            compared[literal] = compare_decimal(number, printed)
        if not compared[literal]:
            continue
        if len(found) >= room:
            beyond += 1
            continue
        before = _anchor(text.folded, start)
        if not before:
            continue
        locator = {"kind": "prose", "before": before, "after": text.folded[end : end + 1].strip()}
        evidence = ValueEvidence(
            artifact=text.artifact, name=claim_id, reported=written, locator=locator
        )
        if stored_value(evidence, text.path) != text.folded[start:end]:
            continue
        found.append(
            Stored(
                artifact=text.artifact,
                locator=locator,
                number=number,
                words=_words(before) + _words(text.artifact),
            )
        )
    return found, beyond


def _candidates(
    claim_id: str, written: str, searched: list[Stored], texts: list[Text]
) -> tuple[list[Stored], int]:
    """Every stored number a check of `written` would match, then the places in text files, at
    most `MAX_CANDIDATES` of them, and how many more in text were not examined."""
    in_texts: list[Stored] = []
    beyond = 0
    for text in texts:
        found, more = _in_text(claim_id, written, text, MAX_CANDIDATES - len(in_texts))
        in_texts += found
        beyond += more
    return [
        stored
        for stored in searched
        if compare_decimal(
            stored.number,
            ValueEvidence(
                artifact=stored.artifact, name=claim_id, reported=written, locator=stored.locator
            ),
        )
    ] + in_texts, beyond


def _assertion(claim_id: str, written: str, stored: Stored) -> dict:
    """A candidate, as the inferred assertion whoever fills the item would write."""
    return ValueEvidence(
        artifact=stored.artifact,
        name=claim_id,
        reported=written,
        locator=stored.locator,
        basis=Basis.INFERRED,
    ).model_dump(mode="json")


def _console_log(path: pathlib.Path) -> bool:
    """Whether a file with no suffix is text: Code Ocean writes a run's standard output to
    `results/output`, and the values a task asks about are printed there."""
    if path.suffix:
        return False
    try:
        with path.open("rb") as handle:
            head = handle.read(8192)
        head.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return b"\x00" not in head


def _artifacts(
    capsule: pathlib.Path, directory: pathlib.Path
) -> tuple[list[dict], list[PassedOver], list[PassedOver]]:
    results = capsule / RESULTS
    files = sorted(p for p in results.rglob("*") if p.is_file()) if results.is_dir() else []
    artifacts, passed, unread = [], [], []
    for path in files:
        inside_capsule = path.relative_to(capsule).as_posix()
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        relative = pathlib.Path(os.path.relpath(path.absolute(), directory.absolute())).as_posix()
        if not inside(capsule, path):
            reason = "a link to a file outside the capsule, which is not followed"
            unread.append(PassedOver(file=inside_capsule, reason=reason))
        elif path.suffix.lower() not in READABLE and not _console_log(path):
            passed.append(PassedOver(file=inside_capsule, reason="a format no backend reads"))
        elif len(artifacts) >= MAX_FILES:
            reason = f"past the first {MAX_FILES} files"
            passed.append(PassedOver(file=inside_capsule, reason=reason))
        elif is_lfs_pointer(path):
            reason = "a Git LFS pointer: the file's content is not here, so it is not checked"
            unread.append(PassedOver(file=inside_capsule, reason=reason))
            artifacts.append({"id": inside_capsule, "path": relative, "media_type": media_type})
        else:
            artifacts.append(
                {
                    "id": inside_capsule,
                    "path": relative,
                    "digest": {"algorithm": "sha256", "value": Digest.of_file(path).value},
                    "media_type": "text/plain" if _console_log(path) else media_type,
                }
            )
    return artifacts, passed, unread


def _sorted(question: str, written: str, found: list[Stored]) -> tuple[list[Stored], str]:
    """The candidates, any that pass the guards first, and why none is unique, if none is."""
    if not found:
        return [], "no address in the searched files matches"
    if not specific(written):
        return found, (
            f"{written} has fewer than {MIN_SIGNIFICANT} significant digits or is an integer "
            f"below {SMALL_INTEGER}, so a match of it may be chance"
        )
    passing = [
        stored
        for stored in found
        if labels_agree(question, stored.labels) and qualifiers_agree(question, stored.words)
    ]
    others = [stored for stored in found if stored not in passing]
    if not passing:
        return found, "the question names a label or a split no matching address carries"
    if len(passing) > 1:
        return passing + others, f"{len(passing)} addresses pass the guards, not one"
    return passing + others, ""


def _item(
    claim_id: str,
    question: str,
    values: list[object],
    searched: list[Stored],
    texts: list[Text],
    absent: list[int],
) -> OpenItem:
    """The item one question leaves open, with what the search found for it."""
    written = [_written(value) for value in values]
    context: dict[str, object] = {"question": question, "values": [str(v) for v in values]}
    if absent:
        context["absent_from_runs"] = absent
    if any(value is None for value in written):
        return OpenItem(
            id=f"{claim_id}/passage",
            claim=claim_id,
            need=Need.PASSAGE,
            asks="the passage of a result file that prints this answer",
            context=context,
        )
    found: list[Stored] = []
    reason = "the runs disagree, so no one value is the task's"
    if len(set(written)) == 1:
        matched, beyond = _candidates(claim_id, written[0] or "", searched, texts)
        found, reason = _sorted(question, written[0] or "", matched)
        context["candidates_found"] = len(found) + beyond
        if beyond:
            context["candidates_not_examined"] = beyond
            reason = (
                f"{beyond} more places in text match, past the first {MAX_CANDIDATES}, and were "
                "not examined, so none is known to be the only one"
            )
    return OpenItem(
        id=f"{claim_id}/value",
        claim=claim_id,
        need=Need.VALUE,
        asks="the address of this value in a result file",
        context=context,
        candidates=tuple(
            _assertion(claim_id, written[0] or "", stored) for stored in found[:MAX_CANDIDATES]
        ),
        unique=bool(found) and not reason,
        reason=reason,
    )


def from_corebench(
    capsule: pathlib.Path,
    tasks: pathlib.Path,
    directory: pathlib.Path,
    capsule_id: str | None = None,
) -> Written:
    """Write the draft and the open items one capsule's task gives into `directory`."""
    try:
        raw = tasks.read_bytes()
    except OSError as e:
        raise CorebenchError(f"{tasks} could not be read: {e}") from e
    if not capsule.is_dir():
        raise CorebenchError(f"{capsule} is not a capsule folder")
    task = task_of(raw, capsule_id or capsule.name)
    if not task.results or not all(isinstance(run, dict) for run in task.results):
        raise CorebenchError(f"the task for {task.capsule_id} states no results")

    artifacts, passed, unread = _artifacts(capsule, directory)
    searched: list[Stored] = []
    texts: list[Text] = []
    for artifact in artifacts:
        path = capsule / artifact["id"]
        suffix = path.suffix.lower()
        if "digest" not in artifact:
            continue
        if suffix not in TREE | DELIMITED | TEXT and not _console_log(path):
            continue
        if path.stat().st_size > MAX_SEARCHED_BYTES:
            reason = f"not searched: larger than {MAX_SEARCHED_BYTES} bytes"
            unread.append(PassedOver(file=artifact["id"], reason=reason))
            continue
        try:
            if suffix in TREE | DELIMITED:
                searched += _stored(artifact["id"], path)
            else:
                texts.append(_text(artifact["id"], path))
        except Refused as e:
            unread.append(PassedOver(file=artifact["id"], reason=f"not searched: {e}"))

    claims, items, taken = [], [], set()
    # Every question any run asks, in the order the runs first ask it. A question some runs do
    # not ask is kept, and the item says which runs lack it.
    questions = list(dict.fromkeys(question for run in task.results for question in run))
    with reading_once():
        for question in questions:
            values = [run[question] for run in task.results if question in run]
            claim_id = _slug(question, taken)
            claims.append({"id": claim_id, "text": question})
            absent = [n for n, run in enumerate(task.results) if question not in run]
            items.append(_item(claim_id, question, values, searched, texts, absent))

    provenance = {"generated_by": READER}
    if task.capsule_doi:
        provenance["repository"] = task.capsule_doi
    draft = {
        "schema_version": SCHEMA_VERSION,
        "project": task.capsule_title or task.capsule_id,
        "provenance": provenance,
        "artifacts": artifacts,
        "claims": claims,
    }
    source = Source(
        reader=READER,
        reader_version=__version__,
        format=FORMAT,
        path=named(tasks),
        digest=Digest.of_file(tasks).value,
    )
    written = write_draft(directory, draft, source, tuple(items))
    return Written(
        open_items=written.as_posix(),
        draft=(written.parent / DRAFT_NAME).as_posix(),
        artifacts=len(artifacts),
        pinned=sum("digest" in artifact for artifact in artifacts),
        claims=len(claims),
        items=len(items),
        passed_over=tuple(passed),
        not_checked=tuple(unread),
    )
