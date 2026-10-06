"""Writing a first manifest for a project that has none.

`repro manifest init` pins files by content and writes a `repro.yaml` that verifies as written,
so the first thing an author edits is a working file rather than an empty one. The files are
the ones named, or, with none named, the ones `discover` finds, which is a guess and is
reported as one.

The example claims are real where that is cheap: a number read out of a pinned JSON or YAML
file, and a line read out of a pinned text source. Each is run through the engine before it is
written and kept only if every assertion verifies. An example that cannot be made real is
written as a YAML comment, so a starter never declares a claim that fails on its first run.

Nothing here prints. `repro.cli` renders the `Starter` this returns.
"""

from __future__ import annotations

import collections
import itertools
import math
import mimetypes
import pathlib
import re
from collections.abc import Iterator

import yaml
from provenance_core.gitref import try_run
from pydantic import BaseModel, ConfigDict

from repro.adapters.array import _ARRAY_SUFFIXES
from repro.adapters.columnar import COLUMNAR_SUFFIXES
from repro.adapters.sheet import WORKBOOK_SUFFIXES
from repro.adapters.sqlite import _SQLITE_SUFFIXES
from repro.adapters.table import _DELIMITERS
from repro.adapters.tree import _TREE_SUFFIXES, _load_tree
from repro.exceptions import ArtifactRefusedError, ArtifactUnreadableError, ManifestExistsError
from repro.manifest import DEFAULT_NAME
from repro.models import SCHEMA_VERSION, ArtifactRef, Digest, Manifest, Outcome
from repro.provenance import of_tree
from repro.verify import verify

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

_NOT_SEARCHED = {"node_modules", "__pycache__", "venv", "env", "site-packages"}

#: The standard library's own table, never the host's `mime.types`, so one file gets one media
#: type on every machine. `media_type` is recorded and not verified.
_MEDIA_TYPES = mimetypes.MimeTypes()
_MEDIA_TYPE_OVERRIDES = {".yaml": "application/yaml", ".yml": "application/yaml"}

HEADER = """\
# The evidence manifest for {project}, read by `repro verify`.
#
# `artifacts` pins files by sha256. An edited file is reported as a broken pin until the
# digest recorded here is replaced with the output of `shasum -a 256 <path>`.
#
# `claims` says what the manuscript states and where a pinned artifact holds it. To add a
# claim, copy an entry under `claims`, give it a new id, and point its evidence at the id of
# an artifact. A `metric` reads a number at an RFC 6901 JSON Pointer in a JSON or YAML file;
# `reported` is the number as the manuscript prints it, in quotes. A `quote` finds a passage
# in a text source. Claims whose id begins `example-` were written by `repro manifest init` to
# show the shape, and are there to be edited or removed.
#
# Check it:
#
#     repro verify
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
            entries = list(itertools.islice(parent.iterdir(), MAX_ENTRIES + 1))
            if len(entries) > MAX_ENTRIES:
                notes.append(f"{parent.name}/ holds more than {MAX_ENTRIES} entries")
                continue
            for entry in sorted(entries):
                if entry.name.startswith(".") or entry.is_symlink():
                    continue
                if entry.is_dir():
                    if entry.name not in _NOT_SEARCHED:
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


def _numbers(node: object, pointer: str = "") -> Iterator[tuple[str, str]]:
    """Every finite number reachable through mappings, in document order, with its pointer."""
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(key, str):
                token = key.replace("~", "~0").replace("/", "~1")
                yield from _numbers(value, f"{pointer}/{token}")
    elif isinstance(node, (int, float)) and not isinstance(node, bool) and math.isfinite(node):
        yield pointer, str(node)


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


def write(root: pathlib.Path, names: list[str], cwd: pathlib.Path) -> Starter:
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
    provenance = of_tree(root, generated_by="repro manifest init")
    if provenance.commit:
        document["provenance"] = provenance.model_dump()
    document["artifacts"] = pins
    if claims:
        document["claims"] = claims
    manifest = Manifest.model_validate({**document, "path": target})

    # Comments are written around the dumped document, because `safe_dump` carries none.
    # `claims` is the last key, so a commented entry sits where uncommenting it declares it.
    text = HEADER.format(project=root.name) + yaml.safe_dump(document, sort_keys=False, width=100)
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
