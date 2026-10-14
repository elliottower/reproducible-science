"""Writing a first manifest for a project that has none.

`repro manifest init` pins files by content and writes a `repro.yaml` that verifies as written,
so the first thing an author edits is a working file rather than an empty one. The files are
the ones named, or, with none named, the ones `discover` finds, which is a guess and is
reported as one.

The example claims are real where that is cheap: a number read out of a pinned JSON or YAML
file, and a line read out of a pinned text source. Each is run through the engine before it is
written and kept only if every assertion verifies. An example that cannot be made real is
written as a YAML comment, so a starter never declares a claim that fails on its first run.

`survey` reports what the same discovery finds without writing anything, for `repro verify`
in a project with no manifest: the result files, the manuscript, and the numbers the
manuscript prints that agree with a value a JSON or YAML file holds. Those agreements are
guesses, and no decision is made from one.

Nothing here prints. `repro.cli` renders the `Starter` and the `Survey` these return.
"""

from __future__ import annotations

import collections
import decimal
import itertools
import math
import mimetypes
import os
import pathlib
import re
from collections.abc import Iterator

import yaml
from provenance_core.gitref import try_run
from pydantic import BaseModel, ConfigDict

from claims.adapters.array import _ARRAY_SUFFIXES
from claims.adapters.columnar import COLUMNAR_SUFFIXES
from claims.adapters.sheet import WORKBOOK_SUFFIXES
from claims.adapters.sqlite import _SQLITE_SUFFIXES
from claims.adapters.table import _DELIMITERS, read_cells
from claims.adapters.tree import _TREE_SUFFIXES, Written, _load_tree
from claims.exceptions import (
    ArtifactMissingError,
    ArtifactRefusedError,
    ArtifactUnreadableError,
    BackendUnavailableError,
    ManifestExistsError,
)
from claims.manifest import DEFAULT_NAME
from claims.models import (
    SCHEMA_VERSION,
    ArtifactRef,
    Conversion,
    Digest,
    Manifest,
    NumberForm,
    Outcome,
    Standing,
)
from claims.numbers import numbers as printed_numbers
from claims.numbers import telling
from claims.provenance import of_tree
from claims.verify import agrees, verify

#: Where discovery looks for result files, relative to the project top.
CONVENTIONAL = ("results", "paper/artifacts", "outputs", "data")

#: Every suffix a format adapter reads, taken from the adapters. `.txt` is left out although the
#: table adapter accepts it: under `results/` it is as often a log as a table.
DATA_SUFFIXES = (
    set(_TREE_SUFFIXES)
    | set(_DELIMITERS)
    | COLUMNAR_SUFFIXES
    | WORKBOOK_SUFFIXES
    | _SQLITE_SUFFIXES
    | _ARRAY_SUFFIXES
)

#: A manuscript is pinned unasked only under one of these names, at the top of the project or
#: in one of these directories, and only when exactly one such file exists.
MANUSCRIPT_DIRECTORIES = ("", "paper", "manuscript")
MANUSCRIPT_STEMS = ("paper", "manuscript", "main")
TEXT_SUFFIXES = (".tex", ".md", ".txt")

MAX_DISCOVERED = 20
MAX_DEPTH = 3
MAX_ENTRIES = 1000
"""A directory holding more entries than this is a large tree, and is not searched."""
MAX_BYTES = 50 * 1024 * 1024
MAX_QUOTE_TRIES = 5
MAX_VALUES_PER_FILE = 10_000
"""A survey reads at most this many numbers from one result file."""
MAX_COMPARISONS = 1_000_000
"""A survey compares at most this many pairs of a printed number and a stored one."""

_NOT_SEARCHED = {"node_modules", "__pycache__", "venv", "env", "site-packages"}

#: The formats discovery finds: the key a survey groups result files under, the name a reader
#: knows the format by, and the suffixes its adapter reads, in the order a survey lists them.
FORMATS = (
    ("tree", "JSON and YAML", frozenset(_TREE_SUFFIXES)),
    ("delimited", "CSV, TSV and PSV", frozenset(_DELIMITERS)),
    ("columnar", "Parquet, Feather, Stata, SPSS, .rds", frozenset(COLUMNAR_SUFFIXES)),
    ("workbook", "Excel", frozenset(WORKBOOK_SUFFIXES)),
    ("sqlite", "SQLite", frozenset(_SQLITE_SUFFIXES)),
    ("array", "NumPy, HDF5 and NetCDF", frozenset(_ARRAY_SUFFIXES)),
)
FORMAT_NAMES = {key: name for key, name, _ in FORMATS}

#: What a survey's JSON document is, and the revision of its shape.
SURVEY_SCHEMA = "reproducible.science/survey/0.1-experimental"

#: A column, a key repeated across the elements of a list, or any other mapping key, is
#: index-like where one word of its name is one of these or its name is empty; a column or a
#: repeated key also where its values step by one constant amount over `INDEX_MIN_ROWS` rows. A survey lists its guesses after the others and
#: counts them apart, and hides none.
INDEX_NAMES = frozenset({"step", "epoch", "iter", "iteration", "idx", "index", "row", "id", "seed"})
INDEX_MIN_ROWS = 10

#: Text output shortens a pointer longer than this; JSON keeps it whole.
POINTER_SHOWN = 60

#: The standard library's own table, never the host's `mime.types`, so one file gets one media
#: type on every machine. The overrides are suffixes that table lacks in some supported Python:
#: `.md` is in it only from 3.12. `media_type` is recorded and not verified.
_MEDIA_TYPES = mimetypes.MimeTypes()
_MEDIA_TYPE_OVERRIDES = {
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
    ".md": "text/markdown",
}

HEADER = """\
# The evidence manifest for {project}, read by `{program} verify`.
#
# `artifacts` pins files by sha256. An edited file is reported as a broken pin until the
# digest recorded here is replaced with the output of `shasum -a 256 <path>`.
#
# `claims` says what the manuscript states and where a pinned artifact holds it. To add a
# claim, copy an entry under `claims`, give it a new id, and point its evidence at the id of
# an artifact. Claims whose id begins `example-` were written by `{program} manifest init` to show
# the shape, and are there to be edited or removed.
#
# The kinds of evidence. `reported` is the number as the manuscript prints it, in quotes.
#
#   metric          a number at an RFC 6901 JSON Pointer in a JSON or YAML file
#                     {{kind: metric, artifact: ID, name: p, reported: '0.031', pointer: /primary/p}}
#   table           a cell of a CSV, TSV, Parquet, Stata, SPSS or .rds table: `where` or `row`
#                     {{kind: table, artifact: ID, name: acc, reported: '0.648', column: accuracy,
#                      where: {{model: lasso}}}}
#   value           a number at a locator, for every format `repro` reads
#                     {{kind: value, artifact: ID, name: n, reported: '480', locator: {{...}}}}
#   quote           a passage that occurs in a PDF, LaTeX or text source; it reads no number
#                     {{kind: quote, artifact: ID, text: 'A passage copied from the source.'}}
#   correspondence  two artifacts hold the same number, and neither is written here
#                     {{kind: correspondence, name: n, sides: [
#                        {{name: stated, artifact: ID, locator: {{...}}}},
#                        {{name: measured, artifact: ID, locator: {{...}}}}]}}
#   aggregate       a mean, median, min, max, sum or count over every member listed
#                     {{kind: aggregate, members: [{{artifact: ID, locator: {{...}}}},
#                      {{artifact: ID, locator: {{...}}}}], count: 2, statistic: mean,
#                      name: acc, reported: '0.914'}}
#
# The locators a `value`, a side or a member takes:
#
#   JSON, YAML                     {{kind: tree, pointer: /primary/n}}
#   CSV, TSV, PSV, Parquet, Feather,
#   Arrow, Stata, SPSS, .rds       {{kind: table, column: accuracy, where: {{model: lasso}}}}
#   the same, by row from 0        {{kind: table_position, column: accuracy, row: 0}}
#   Excel                          {{kind: sheet, sheet: Table 2, column: auc, where: {{model: lasso}}}}
#   SQLite                         {{kind: sqlite, table: runs, column: loss, where: {{seed: 3}}}}
#   .npy, .npz, HDF5, NetCDF       {{kind: array, array: accuracy, index: [1, 1]}}
#   PDF, LaTeX, text, HTML source  {{kind: prose, before: 'split was', after: '%'}}
#
# `prose` reads the number between two literal anchors, for a sentence or a printed table.
# Anchors are written with single spaces, whatever the padding or line breaks in the file, and
# `after` names what touches the number. The Slope cell of the row `|     7| 0.318| 0.107|`:
#
#   {{kind: prose, before: '| 7|', after: '|'}}
#
# `conversion: percent` on a number says the file stores the fraction of the percentage the
# manuscript prints, 0.042 for 4.2, and `conversion: fraction` the reverse. `places: 2` says
# the manuscript reports the number to two decimal places, and `reported` must be written so.
#
# `mode: absolute` or `relative` with `tolerance: '0.01'` replaces comparison at the precision
# `reported` prints. `where` must match exactly one row.
#
# Check it:
#
#     {program} verify
#
"""

COMMENTED_METRIC = """\
# - id: example-number
#   text: The sentence in the manuscript that reports the number.
#   evidence:
#   - kind: metric
#     artifact: results             # the id of an artifact above
#     name: accuracy
#     reported: '0.93'              # as the manuscript prints it, in quotes
#     pointer: /metrics/accuracy    # RFC 6901 JSON Pointer into the file
"""

COMMENTED_QUOTE = """\
# - id: example-quote
#   text: What the manuscript says the source states.
#   evidence:
#   - kind: quote
#     artifact: paper               # the id of an artifact above
#     text: A passage copied from the source, forty characters or more.
"""


class Starter(BaseModel):
    """What `write` wrote."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: pathlib.Path
    artifacts: tuple[ArtifactRef, ...]
    discovered: bool
    """The artifacts were found by `discover` and not named by the caller."""
    capped: bool = False
    """Discovery found more than `MAX_DISCOVERED` files and pinned the first of them."""
    notes: tuple[str, ...] = ()
    """What discovery passed over, and why."""
    written: tuple[str, ...] = ()
    """Ids of the example claims declared in the manifest. Each verifies."""
    commented: tuple[str, ...] = ()
    """Ids of the example claims written as comments."""


class Also(BaseModel):
    """Another place in the same column, or at the same key of another list element, that the
    number a `Candidate` names also agrees with."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    locator: dict[str, str | int]
    stored: str


class Candidate(BaseModel):
    """A number the manuscript prints that agrees with a value a result file holds.

    A guess. The digits agree at the precision printed, under `conversion` where one is named,
    and nothing says the sentence reports that value. It is never a decision.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    printed: str
    """As the manuscript prints it, with a percent sign where it has one."""
    offset: int
    """Where it starts in the manuscript's normalized text, as `claims.numbers` counts it."""
    line: int | None
    context: str
    path: str
    """The result file, relative to the project."""
    locator: dict[str, str | int]
    """Where the file holds the value, as a `value` assertion's locator would say it: `tree`
    with a pointer, or `table_position` with a column and a row from 0. Where the number
    agrees with several rows of one column, or one key of several list elements, this is one
    whose value equals the number exactly if any does, and `also` holds the rest."""
    stored: str
    """The value there, as the file writes it."""
    conversion: Conversion | None = None
    also: tuple[Also, ...] = ()
    index_like: bool = False
    """The value is in an index-like column or key, so the agreement says less."""


class Survey(BaseModel):
    """What `survey` found. Nothing was written and nothing was verified."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    results: dict[str, tuple[str, ...]]
    """Each result file found, relative to the project, under the key of its format in
    `FORMATS`: `tree`, `delimited`, `columnar`, `workbook`, `sqlite` or `array`."""
    capped: bool = False
    """Discovery found more than `MAX_DISCOVERED` result files and kept the first of them."""
    manuscript: str | None = None
    notes: tuple[str, ...] = ()
    """What discovery passed over, what could not be read, and where a cap was reached. Paths
    are relative to the project."""
    read_from: tuple[str, ...] = ()
    """The result files values were read from: JSON, YAML, and tables a table locator reads."""
    values: int = 0
    """How many numbers were read from those files, at most `MAX_VALUES_PER_FILE` from each."""
    cut: tuple[str, ...] = ()
    """The files holding more than `MAX_VALUES_PER_FILE` numbers, of which the first were read."""
    index_like: tuple[str, ...] = ()
    """The index-like columns and keys, as `path column` or `path pattern`."""
    compared: int = 0
    """How many numbers the manuscript prints were compared with those values: the ones no
    rule sets aside, printed in digits, with two digits or a decimal point."""
    not_compared: int = 0
    """How many such numbers were left uncompared because `MAX_COMPARISONS` was reached."""
    candidates: tuple[Candidate, ...] = ()
    """Guesses outside index-like columns and keys first, those in JSON and YAML before those
    in tables, each in manuscript order; then the guesses in index-like ones, in that order."""


def project_root(start: pathlib.Path) -> pathlib.Path:
    """The top of the project holding `start`: its git root, or `start` outside a repository."""
    top = try_run("rev-parse", "--show-toplevel", cwd=start)
    return pathlib.Path(top.strip() if top else start).resolve()


def _shallowest(directory: pathlib.Path, notes: list[str]) -> list[pathlib.Path]:
    """The data files at the shallowest level of `directory` that holds any.

    A results directory keeps its summaries at the top and per-run output below them, so the
    first level with a readable file is taken and nothing beneath it is searched.
    """
    level = [directory]
    for _ in range(MAX_DEPTH):
        files: list[pathlib.Path] = []
        below: list[pathlib.Path] = []
        for parent in level:
            try:
                entries = list(itertools.islice(parent.iterdir(), MAX_ENTRIES + 1))
            except OSError as e:
                notes.append(f"{parent.name}/ could not be listed: {e.strerror}")
                continue
            if len(entries) > MAX_ENTRIES:
                notes.append(f"{parent.name}/ holds more than {MAX_ENTRIES} entries")
                continue
            for entry in sorted(entries):
                if entry.name.startswith(".") or entry.is_symlink():
                    continue
                if entry.is_dir():
                    if not os.access(entry, os.R_OK | os.X_OK):
                        notes.append(f"{parent.name}/{entry.name}/ could not be listed")
                    elif entry.name not in _NOT_SEARCHED:
                        below.append(entry)
                elif entry.suffix.lower() in DATA_SUFFIXES:
                    if entry.stat().st_size > MAX_BYTES:
                        notes.append(f"{entry.name} is over {MAX_BYTES // 2**20} MB")
                    else:
                        files.append(entry)
        if files:
            return files
        level = below
    return []


def discover(root: pathlib.Path) -> tuple[list[pathlib.Path], bool, list[str]]:
    """Files worth pinning under `root`, whether the cap was hit, and what was passed over."""
    notes: list[str] = []
    found = [
        path
        for name in CONVENTIONAL
        if (root / name).is_dir()
        for path in _shallowest(root / name, notes)
    ]
    capped = len(found) > MAX_DISCOVERED
    found = found[:MAX_DISCOVERED]

    manuscripts = [
        path
        for directory in MANUSCRIPT_DIRECTORIES
        for stem in MANUSCRIPT_STEMS
        for suffix in TEXT_SUFFIXES
        if (path := root / directory / f"{stem}{suffix}").is_file()
    ]
    if len(manuscripts) == 1:
        found.append(manuscripts[0])
    elif manuscripts:
        names = ", ".join(m.relative_to(root).as_posix() for m in manuscripts)
        notes.append(f"{names} could each be the manuscript, so none was pinned")
    return found, capped, notes


def _named(names: list[str], cwd: pathlib.Path, root: pathlib.Path) -> list[pathlib.Path]:
    """The files a caller named, or `ArtifactRefusedError` for the first that cannot be pinned."""
    paths = []
    for name in names:
        path = (cwd / name).resolve()
        if not path.exists():
            raise ArtifactRefusedError(path, "does not exist")
        if not path.is_file():
            raise ArtifactRefusedError(path, "is not a file")
        if not path.is_relative_to(root):
            raise ArtifactRefusedError(path, f"is outside the project at {root}")
        paths.append(path)
    return list(dict.fromkeys(paths))


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "artifact"


def _pins(paths: list[pathlib.Path], root: pathlib.Path) -> list[dict]:
    """One artifact entry per file. The id is the file's stem, or its whole path where two
    files share a stem."""
    relative = [path.relative_to(root) for path in paths]
    stems = collections.Counter(_slug(r.stem) for r in relative)
    pins: list[dict] = []
    used: set[str] = set()
    for path, rel in zip(paths, relative, strict=True):
        identifier = _slug(rel.stem) if stems[_slug(rel.stem)] == 1 else _slug(rel.as_posix())
        while identifier in used:
            identifier += "-2"
        used.add(identifier)
        suffix = path.suffix.lower()
        pins.append(
            {
                "id": identifier,
                "path": rel.as_posix(),
                "media_type": _MEDIA_TYPE_OVERRIDES.get(suffix)
                or _MEDIA_TYPES.guess_type(path.name)[0]
                or "application/octet-stream",
                "digest": {"algorithm": "sha256", "value": Digest.of_file(path).value},
            }
        )
    return pins


def _walk(node: object) -> Iterator[tuple[str, str, str]]:
    """Every finite number reachable through mappings and lists, in document order, with its
    RFC 6901 pointer and its pattern: the pointer with each list index written `*`. Walked
    with a stack of its own, so no nesting depth exhausts Python's."""
    stack: list[tuple[str, str, object]] = [("", "", node)]
    while stack:
        pointer, pattern, node = stack.pop()
        if isinstance(node, dict):
            children = []
            for key, value in node.items():
                if isinstance(key, str):
                    token = key.replace("~", "~0").replace("/", "~1")
                    children.append((f"{pointer}/{token}", f"{pattern}/{token}", value))
            stack.extend(reversed(children))
        elif isinstance(node, list):
            stack.extend(
                reversed([(f"{pointer}/{i}", f"{pattern}/*", v) for i, v in enumerate(node)])
            )
        elif isinstance(node, Written):
            # A number with a fraction or an exponent arrives as the text the file wrote.
            if decimal.Decimal(node).is_finite():
                yield pointer, pattern, str(node)
        elif isinstance(node, (int, float)) and not isinstance(node, bool) and math.isfinite(node):
            yield pointer, pattern, str(node)


def _numbers(node: object) -> Iterator[tuple[str, str]]:
    """Every finite number reachable through mappings and lists, with its pointer."""
    for pointer, _, value in _walk(node):
        yield pointer, value


def _metric_examples(pins: list[dict], root: pathlib.Path) -> Iterator[tuple[dict, dict]]:
    """A candidate `metric` claim per pinned tree file: the first number the file holds."""
    for pin in pins:
        path = root / pin["path"]
        if path.suffix.lower() not in _TREE_SUFFIXES:
            continue
        try:
            first = next(_numbers(_load_tree(path)), None)
        except ArtifactUnreadableError:
            continue
        if first is None:
            continue
        pointer, value = first
        yield (
            pin,
            {
                "id": "example-number",
                "text": f"Example to edit: {pin['path']} holds {value} at {pointer or 'its root'}.",
                "evidence": [
                    {
                        "kind": "metric",
                        "artifact": pin["id"],
                        "name": pointer.rpartition("/")[2] or pin["id"],
                        "reported": value,
                        "pointer": pointer,
                    }
                ],
            },
        )


def _quote_examples(pins: list[dict], root: pathlib.Path) -> Iterator[tuple[dict, dict]]:
    """Candidate `quote` claims: lines of prose from the pinned text sources."""
    for pin in pins:
        path = root / pin["path"]
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            # Forty characters is where `citations` stops warning that a quotation is short,
            # and a line opening on markup is a heading, a table row or a macro.
            if 40 <= len(line) <= 200 and line[0].isalnum():
                yield (
                    pin,
                    {
                        "id": "example-quote",
                        "text": f"Example to edit: {pin['path']} contains this passage.",
                        "evidence": [{"kind": "quote", "artifact": pin["id"], "text": line}],
                    },
                )


def _first_verified(
    candidates: Iterator[tuple[dict, dict]], target: pathlib.Path, tries: int
) -> dict | None:
    """The first candidate claim whose every assertion verifies, or None.

    The check is the engine's own, so what is written is what `repro verify` will report. The
    trial manifest holds the one artifact the claim reads, which keeps a candidate to one file.
    """
    for pin, claim in itertools.islice(candidates, tries):
        trial = Manifest.model_validate({"artifacts": [pin], "claims": [claim], "path": target})
        decisions = verify(trial).decisions
        if decisions and all(d.outcome is Outcome.VERIFIED for d in decisions):
            return claim
    return None


def write(
    root: pathlib.Path, names: list[str], cwd: pathlib.Path, program: str = "repro"
) -> Starter:
    """Write a starter manifest at `root`, pinning `names` as given relative to `cwd`.

    Raises `ManifestExistsError` rather than overwrite one, and `ArtifactRefusedError` for a
    named file that is missing or outside the project. Nothing is written in either case.
    """
    target = root / DEFAULT_NAME
    if target.exists():
        raise ManifestExistsError(target)

    if names:
        paths, capped, notes = _named(names, cwd, root), False, []
    else:
        paths, capped, notes = discover(root)
    pins = _pins(paths, root)

    metric = _first_verified(_metric_examples(pins, root), target, len(pins))
    quote = _first_verified(_quote_examples(pins, root), target, MAX_QUOTE_TRIES)
    claims = [claim for claim in (metric, quote) if claim is not None]

    document: dict = {"schema_version": SCHEMA_VERSION, "project": root.name}
    provenance = of_tree(root, generated_by=f"{program} manifest init")
    if provenance.commit:
        document["provenance"] = provenance.model_dump()
    document["artifacts"] = pins
    if claims:
        document["claims"] = claims
    manifest = Manifest.model_validate({**document, "path": target})

    # Comments are written around the dumped document, because `safe_dump` carries none.
    # `claims` is the last key, so a commented entry sits where uncommenting it declares it.
    text = HEADER.format(project=root.name, program=program) + yaml.safe_dump(
        document, sort_keys=False, width=100
    )
    commented = (COMMENTED_METRIC if metric is None else "") + (
        COMMENTED_QUOTE if quote is None else ""
    )
    if commented:
        text += "\n# An example with nothing in this project to point at. Uncomment and edit:\n#\n"
        text += ("" if claims else "# claims:\n") + commented
    target.write_text(text, encoding="utf-8")

    return Starter(
        path=target,
        artifacts=manifest.artifacts,
        discovered=not names,
        capped=capped,
        notes=tuple(notes),
        written=tuple(claim["id"] for claim in claims),
        commented=tuple(
            name
            for name, claim in (("example-number", metric), ("example-quote", quote))
            if claim is None
        ),
    )


def _format(path: pathlib.Path) -> str:
    """The key of the format a discovered result file is in."""
    return next(key for key, _, suffixes in FORMATS if path.suffix.lower() in suffixes)


class _Held(BaseModel):
    """One number read from a result file: where, what, and the group of places it repeats
    over, a table's column or a pointer pattern with a list index in it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    locator: dict[str, str | int]
    stored: str
    group: str | None = None
    index_like: bool = False


class _Read(BaseModel):
    """The numbers read from one result file, and what was left out of them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    values: tuple[_Held, ...] = ()
    cut: bool = False
    index_like: tuple[str, ...] = ()
    """The index-like groups, as a report names them."""


def _finite(cell: object) -> bool:
    if not isinstance(cell, str):
        return False
    try:
        return decimal.Decimal(cell).is_finite()
    except (decimal.InvalidOperation, ValueError):
        return False


def _index_name(name: str) -> bool:
    """A name that is empty, or one of whose words names an index."""
    words = re.split(r"[^a-z0-9]+", name.strip().lower())
    return not name.strip() or name.startswith("Unnamed:") or any(w in INDEX_NAMES for w in words)


def _progression(values: list[str]) -> bool:
    """At least `INDEX_MIN_ROWS` values, each the one before plus the same nonzero amount."""
    if len(values) < INDEX_MIN_ROWS:
        return False
    numbers = [decimal.Decimal(v) for v in values]
    steps = {b - a for a, b in itertools.pairwise(numbers)}
    return len(steps) == 1 and steps != {0}


def _grouped(held: list[_Held], names: dict[str, tuple[str, str]]) -> _Read:
    """Each value marked index-like where its group is. `names` gives each group the name a
    report shows and the name `_index_name` reads: a pattern and its last key, or `column x`
    and `x`."""
    members: dict[str, list[str]] = {}
    for value in held:
        if value.group is not None:
            members.setdefault(value.group, []).append(value.stored)
    index = [
        group
        for group, values in members.items()
        if _index_name(names[group][1]) or _progression(values)
    ]
    marked = tuple(
        v.model_copy(update={"index_like": v.index_like or v.group in index}) for v in held
    )
    alone = [str(v.locator["pointer"]) for v in held if v.group is None and v.index_like]
    return _Read(values=marked, index_like=(*(names[group][0] for group in index), *alone))


def _read_values(path: pathlib.Path, cap: int) -> _Read:
    """At most `cap` finite numbers from one result file, each with the locator that reads it.

    A JSON or YAML file is read as the example `metric` claim reads it, and a delimited or
    columnar table by the table adapter, a row at a time, so a large delimited file is read no
    further than `cap` numbers. Other formats give nothing: a workbook or a database holds
    several tables, and an array no column names.
    """
    suffix = path.suffix.lower()
    held: list[_Held] = []
    names: dict[str, tuple[str, str]] = {}
    cut = False
    if suffix in _TREE_SUFFIXES:
        for pointer, pattern, value in _walk(_load_tree(path)):
            if len(held) == cap:
                cut = True
                break
            # A key repeated across list elements is a group, as a column is.
            group = pattern if "*" in pattern else None
            if group is not None:
                names[group] = (pattern, pattern.rpartition("/")[2])
            locator: dict[str, str | int] = {"kind": "tree", "pointer": pointer}
            # A key outside any list is read by its name alone; `_grouped` reads a group's.
            named = group is None and _index_name(pointer.rpartition("/")[2])
            held.append(_Held(locator=locator, stored=value, group=group, index_like=named))
    elif suffix in _DELIMITERS or suffix in COLUMNAR_SUFFIXES:
        header, rows = read_cells(path)
        names = {column: (f"column {column or '(no name)'}", column) for column in header}
        for number, row in enumerate(rows):
            numeric = [(c, str(row.get(c))) for c in header if _finite(row.get(c))]
            if len(held) + len(numeric) > cap:
                cut = True
                break
            held += [
                _Held(
                    locator={"kind": "table_position", "column": column, "row": number},
                    stored=cell,
                    group=column,
                )
                for column, cell in numeric
            ]
        rows.close()
    return _grouped(held, names).model_copy(update={"cut": cut})


def _shortened(pointer: str) -> str:
    if len(pointer) <= POINTER_SHOWN:
        return pointer
    half = (POINTER_SHOWN - 3) // 2
    return f"{pointer[:half]}...{pointer[-half:]}"


def address_said(locator: dict[str, str | int]) -> str:
    """A `Candidate` locator as a report prints it, a long pointer shortened in its middle."""
    if locator["kind"] == "tree":
        return _shortened(str(locator["pointer"])) or "/"
    column = str(locator["column"]) or "(no name)"
    return f"column {column}, row {locator['row']}"


def _exact(stored: str, printed: str, conversion: Conversion | None) -> bool:
    value = decimal.Decimal(stored)
    value = conversion.apply(value) if conversion is not None else value
    return value == decimal.Decimal(printed.rstrip("%").replace(",", ""))


def _collapsed(found: list[tuple[Candidate, str | None]]) -> list[Candidate]:
    """One guess per printed number, group of places and conversion, standing for the rest of
    the group in `also`: the first whose value equals the number exactly, or else the first.
    Then ordered: outside index-like places first, trees before tables, by manuscript order."""
    groups: dict[tuple, list[Candidate]] = {}
    order: list[tuple] = []
    for candidate, group in found:
        key = (
            (candidate.offset, candidate.path, group, candidate.conversion)
            if group is not None
            else (candidate.offset, candidate.path, id(candidate))
        )
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(candidate)
    kept = []
    for key in order:
        members = groups[key]
        first = next((c for c in members if _exact(c.stored, c.printed, c.conversion)), members[0])
        also = tuple(Also(locator=c.locator, stored=c.stored) for c in members if c is not first)
        kept.append(first.model_copy(update={"also": also}))
    return sorted(
        kept,
        key=lambda c: (c.index_like, c.locator["kind"] == "table_position", c.offset),
    )


def _scrubbed(note: str, root: pathlib.Path) -> str:
    """A note with the project's absolute path taken out, under every spelling of it."""
    for spelling in sorted({str(root), str(root.resolve())}, key=len, reverse=True):
        note = note.replace(f"{spelling}/", "").replace(spelling, ".")
    return note


def survey(root: pathlib.Path) -> Survey:
    """What `repro verify` could check at `root`, found as `write` finds it, writing nothing.

    The manuscript's numbers are those `claims.numbers` counts, read through a manifest held in
    memory that pins the manuscript and declares no claim. Each one that no rule sets aside is
    compared with every number `_read_values` reads from a discovered result file, by
    `claims.verify.agrees`, the comparison a numeric assertion makes, at the precision printed;
    a number printed with a percent sign is also compared as a percentage of the stored value.
    Every agreement is a `Candidate`. At most `MAX_VALUES_PER_FILE` numbers are read from one
    file and `MAX_COMPARISONS` comparisons made, and where either is reached a note says so. A
    file that cannot be read is a note, never an exception.
    """
    try:
        found, capped, notes = discover(root)
    except OSError as e:
        found, capped, notes = [], False, [f"discovery stopped: {e.filename}: {e.strerror}"]
    manuscripts = [path for path in found if path.suffix.lower() in TEXT_SUFFIXES]
    results = [path for path in found if path not in manuscripts]

    grouped: dict[str, list[str]] = {}
    for path in results:
        grouped.setdefault(_format(path), []).append(path.relative_to(root).as_posix())

    held: list[tuple[str, _Held]] = []
    read_from, cut, index_like = [], [], []
    for path in results:
        relative = path.relative_to(root).as_posix()
        try:
            read = _read_values(path, MAX_VALUES_PER_FILE)
        except (ArtifactUnreadableError, BackendUnavailableError) as e:
            notes.append(f"{relative} could not be read: {e.detail}")
            continue
        except OSError as e:
            notes.append(f"{relative} could not be read: {e.strerror or e}")
            continue
        if read.cut:
            cut.append(relative)
            notes.append(
                f"{relative} holds more than {MAX_VALUES_PER_FILE} numbers; the first "
                f"{len(read.values)} were compared"
            )
        index_like += [f"{relative} {name}" for name in read.index_like]
        if read.values:
            read_from.append(relative)
        held += [(relative, value) for value in read.values]

    manuscript = manuscripts[0] if manuscripts else None
    printed = []
    if manuscript is not None:
        relative = manuscript.relative_to(root).as_posix()
        try:
            pins = _pins([manuscript], root)
            in_memory = Manifest.model_validate({"artifacts": pins, "path": root / DEFAULT_NAME})
            report = printed_numbers(in_memory, only=(pins[0]["id"],))
        except ArtifactUnreadableError as e:
            notes.append(f"{relative} could not be read: {e.detail}")
        except ArtifactMissingError:
            notes.append(f"{relative} could not be read: it is not on disk")
        except OSError as e:
            notes.append(f"{relative} could not be read: {e.strerror or e}")
        else:
            printed = [
                number
                for number in report.numbers
                if number.standing is Standing.UNBOUND
                and number.form is NumberForm.DECIMAL
                and number.value is not None
                and telling(decimal.Decimal(number.value).as_tuple())
            ]

    candidates = []
    compared = comparisons = 0
    for number in printed:
        conversions = (None, Conversion.PERCENT) if number.text.endswith("%") else (None,)
        if comparisons + len(held) * len(conversions) > MAX_COMPARISONS:
            break
        comparisons += len(held) * len(conversions)
        compared += 1
        reported = decimal.Decimal(number.value or "")
        for relative, value in held:
            stored = decimal.Decimal(value.stored)
            agreeing = [c for c in conversions if agrees(stored, reported, c)]
            if agreeing:
                candidate = Candidate(
                    printed=number.text,
                    offset=number.offset,
                    line=number.line,
                    context=number.context,
                    path=relative,
                    locator=value.locator,
                    stored=value.stored,
                    conversion=agreeing[0],
                    index_like=value.index_like,
                )
                candidates.append((candidate, value.group))
    if compared < len(printed):
        notes.append(
            f"comparisons stop at {MAX_COMPARISONS}: {len(printed) - compared} of the "
            f"{len(printed)} numbers the manuscript prints were not compared"
        )

    return Survey(
        results={key: tuple(grouped[key]) for key, _, _ in FORMATS if key in grouped},
        capped=capped,
        manuscript=manuscript.relative_to(root).as_posix() if manuscript is not None else None,
        notes=tuple(_scrubbed(note, root) for note in notes),
        read_from=tuple(read_from),
        values=len(held),
        cut=tuple(cut),
        index_like=tuple(index_like),
        compared=compared,
        not_compared=len(printed) - compared,
        candidates=tuple(_collapsed(candidates)),
    )
