"""A ClawBio skill's output folder, read into a draft manifest and its open items.

A ClawBio skill writes its results into one folder: `report.md`, the report a person reads,
`tables/` and `figures/`, and `reproducibility/`, which holds `commands.sh` (a script that
replays the run), `environment.yml` and `checksums.sha256`. The checksums file lists, one per
line, `<sha256>  <label>` for the outputs the skill chose to record, each label the path from
the folder or, where the skill gave no anchor, the file's name alone. It states which bytes the
run wrote. It does not state which number of the report was read from which cell of which
table. So the reader writes what the folder states and opens an item for each number:

- every file `checksums.sha256` lists becomes an artifact pinned to the digest ClawBio
  recorded, never to one computed now, so a file whose bytes moved since the run verifies as a
  broken pin. A label that leaves the folder, or a bare name with no file of that name at the
  top of the folder, is passed over with the reason;
- a file under `tables/` that the checksums do not list is passed over: ClawBio recorded no
  digest for it, and a file an earlier run left in the same folder looks the same;
- `report.md` becomes an artifact, pinned to the digest the checksums record for it where they
  list it, and to the sha256 of the bytes read otherwise. That digest, and those of
  `commands.sh` and `environment.yml`, are pinned in the open items' source;
- every number `report.md` prints outside code is read under the rule `claims numbers` reads a
  manuscript with (`claims.numbers.printed`). Each quantity becomes a claim whose text is its
  line as printed, with a `quote` of that line in `report.md` marked `basis: inferred`, and one
  item asking for the address of the value in a pinned table. The quote is the reader's
  proposal that the line is the claim: a draft whose claims hold only such quotes fails
  `strict` and `publication` until an author or an agent binds each value. A number the rule
  sets aside, such as a date, a year or a name, a time of day such as `14:22`, and a number
  inside a fenced block or an inline code span, is passed over with the reason;
- each item lists as candidates the addresses in the pinned JSON, YAML and delimited tables at
  which a check of the printed number would match, at the printed precision and, for a number
  printed with a percent sign, also as a fraction shown as a percentage. They are never written
  into the draft: a value found somewhere in a file is not a value fetched from a stated
  address.

`commands.sh` is not declared as a regeneration. A regeneration is one argv writing one
declared output from declared inputs; the script is a shell program whose paths are shell
variables, which writes the whole folder and reads inputs outside it.

Nothing in the folder is run, and a file is read only by a parser that evaluates nothing:
JSON, YAML with the safe loader, and delimited text.
"""

from __future__ import annotations

import csv
import decimal
import hashlib
import io
import json
import mimetypes
import os
import pathlib
import re

import yaml
from citations.exceptions import SourceUnreadableError
from citations.verify import extract_uncached

from claims import __version__
from claims.exceptions import ReproError
from claims.models import SCHEMA_VERSION, Conversion, Digest, ValueEvidence
from claims.numbers import printed
from claims.open_items import DRAFT_NAME, Need, OpenItem, Source, write_draft
from claims.sources import (
    PassedOver,
    RefusedYamlError,
    Written,
    inside,
    is_lfs_pointer,
    load_yaml,
    named,
)
from claims.sources.corebench import MAX_EXPONENT, Refused, _numbers
from claims.verify import compare_decimal

READER = "claims from-clawbio"
FORMAT = "ClawBio reproducibility bundle"

REPORT = "report.md"
BUNDLE = "reproducibility"
CHECKSUMS = f"{BUNDLE}/checksums.sha256"
#: Files of the bundle that are pinned in the source and declared as nothing.
PINNED_IN_SOURCE = (f"{BUNDLE}/commands.sh", f"{BUNDLE}/environment.yml")
TABLES = "tables"

TREE = frozenset({".json", ".yaml", ".yml"})
DELIMITED = frozenset({".csv", ".tsv", ".psv"})

#: A file larger than this is pinned and not searched for candidates.
MAX_SEARCHED_BYTES = 5_000_000
#: At most this many candidates are listed for one item; the count says how many there were.
MAX_CANDIDATES = 20

#: `<sha256>  <label>`, or `<sha256> *<label>` as `sha256sum --binary` writes it.
_LINE = re.compile(r"(?P<digest>[0-9a-fA-F]{64}) [ *](?P<label>.+)")
_FENCE = re.compile(r"\s*(```|~~~)")
_INLINE_CODE = re.compile(r"`[^`]*`")
#: A time of day, `14:22` or `09:05:33`, as a report's header stamps when it was generated.
_CLOCK = re.compile(r"(?<![\d:.])(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d(?:\.\d+)?)?(?![\d:])")


class ClawbioError(ReproError):
    """A ClawBio output folder could not be read as one."""


def _checksums(text: str) -> tuple[list[tuple[str, str]], list[PassedOver]]:
    """Each `(label, sha256)` the checksums file lists, and the lines that are not one."""
    listed, passed, seen = [], [], set()
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        found = _LINE.fullmatch(line.rstrip("\r"))
        if found is None:
            passed.append(PassedOver(file=CHECKSUMS, reason=f"line {number} is not a sha256 line"))
            continue
        label = found["label"]
        if label in seen:
            passed.append(PassedOver(file=label, reason="listed twice in checksums.sha256"))
            continue
        seen.add(label)
        listed.append((label, found["digest"].lower()))
    return listed, passed


def _escapes(label: str) -> bool:
    parts = pathlib.PurePosixPath(label).parts
    return label.startswith("/") or "\\" in label or ".." in parts


def _artifact(label: str, path: pathlib.Path, directory: pathlib.Path, digest: str | None) -> dict:
    relative = os.path.relpath(path.absolute(), directory.absolute())
    artifact: dict = {"id": label, "path": pathlib.Path(relative).as_posix()}
    if digest is not None:
        artifact["digest"] = {"algorithm": "sha256", "value": digest}
    artifact["media_type"] = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return artifact


def _pointer(keys: list[str | int]) -> str:
    return "".join("/" + str(key).replace("~", "~0").replace("/", "~1") for key in keys)


def _leaves(node: object, keys: list[str | int]):
    """Every number in a parsed tree, with its RFC 6901 pointer."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _leaves(value, [*keys, str(key)])
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _leaves(value, [*keys, index])
    elif isinstance(node, decimal.Decimal) or (
        isinstance(node, int | float) and not isinstance(node, bool)
    ):
        yield _pointer(keys), _in_range(decimal.Decimal(str(node)), _pointer(keys) or "/")


def _in_range(number: decimal.Decimal, where: str) -> decimal.Decimal:
    """The number, or `Refused` where its power of ten is past `MAX_EXPONENT`: comparing
    `1e999999999` at a printed precision takes minutes."""
    if number.is_finite() and abs(number.adjusted()) > MAX_EXPONENT:
        raise Refused(f"a number out of range at {where}")
    return number


def _stored(path: pathlib.Path) -> list[tuple[dict, decimal.Decimal]]:
    """Each number in a JSON, YAML or delimited file, with the locator that addresses it.

    Read with the CORE-Bench reader's bounded JSON and the readers' YAML loader: a number past
    `MAX_EXPONENT`, a YAML alias, a key given twice and nesting past `MAX_DEPTH` raise `Refused`
    or `RefusedYamlError`. A file that does not parse is searched for nothing."""
    suffix = path.suffix.lower()
    try:
        text = path.read_text(encoding="utf-8")
        if suffix == ".json":
            tree = _numbers(text)
        elif suffix in TREE:
            tree = load_yaml(text)
        else:
            delimiter = {".tsv": "\t", ".psv": "|"}.get(suffix, ",")
            found = []
            for row_number, row in enumerate(
                csv.DictReader(io.StringIO(text), delimiter=delimiter)
            ):
                for column, cell in row.items():
                    if column is None or cell is None:
                        continue
                    try:
                        number = decimal.Decimal(cell.strip())
                    except decimal.InvalidOperation:
                        continue
                    if number.is_finite():
                        locator = {"kind": "table_position", "column": column, "row": row_number}
                        found.append((locator, _in_range(number, f"row {row_number}, {column}")))
            return found
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        yaml.YAMLError,
        csv.Error,
    ):
        return []
    return [
        ({"kind": "tree", "pointer": pointer}, number)
        for pointer, number in _leaves(tree, [])
        if number.is_finite()
    ]


def _candidates(claim_id: str, value: str, percent: bool, searched: dict[str, list]) -> list[dict]:
    """Every address at which a check of the printed value would match, as an inferred
    assertion: as printed, and for a percentage also from a stored fraction."""
    conversions = (None, Conversion.PERCENT) if percent else (None,)
    found = []
    for artifact, numbers in searched.items():
        for locator, number in numbers:
            for conversion in conversions:
                evidence = ValueEvidence(
                    artifact=artifact,
                    name=claim_id,
                    reported=value,
                    locator=locator,
                    conversion=conversion,
                    basis="inferred",
                )
                if compare_decimal(number, evidence):
                    found.append(evidence.model_dump(mode="json"))
    return found


def _code_masked(lines: list[str]) -> tuple[list[str], set[int]]:
    """The report's lines with each inline code span blanked, and the lines inside a fenced
    block, from 1. A code span prints an identifier or a command, and no result."""
    masked, fenced, inside_fence = [], set(), False
    for number, line in enumerate(lines, start=1):
        if _FENCE.match(line):
            fenced.add(number)
            inside_fence = not inside_fence
            masked.append("")
        elif inside_fence:
            fenced.add(number)
            masked.append("")
        else:
            masked.append(_INLINE_CODE.sub(lambda m: " " * len(m.group()), line))
    return masked, fenced


def _project(lines: list[str], folder: pathlib.Path) -> str:
    heading = next((line[2:].strip() for line in lines if line.startswith("# ")), "")
    return heading or folder.resolve().name


def from_clawbio(folder: pathlib.Path, directory: pathlib.Path) -> Written:
    """Write the draft and the open items one skill's output folder gives into `directory`."""
    checksums, report = folder / CHECKSUMS, folder / REPORT
    if not folder.is_dir():
        raise ClawbioError(f"{folder} is not a folder")
    try:
        listed_raw = checksums.read_bytes()
    except OSError as e:
        raise ClawbioError(
            f"{checksums} could not be read: {e}; a ClawBio output folder holds {CHECKSUMS}"
        ) from e
    if not report.is_file() or not inside(folder, report):
        raise ClawbioError(f"{report} is not a file in the folder")
    try:
        listed, passed = _checksums(listed_raw.decode("utf-8"))
        text = extract_uncached(report)
    except UnicodeDecodeError as e:
        raise ClawbioError(f"{checksums} is not text: {e}") from e
    except SourceUnreadableError as e:
        raise ClawbioError(f"{report} could not be read: {e.detail}") from e

    artifacts: list[dict] = []
    not_checked: list[PassedOver] = []
    searched: dict[str, list] = {}
    recorded = dict(listed)
    for label, digest in listed:
        path = folder / label
        if _escapes(label):
            passed.append(PassedOver(file=label, reason="names a path outside the folder"))
            continue
        if "/" not in label and not path.exists():
            passed.append(
                PassedOver(
                    file=label,
                    reason="a bare file name with no file of that name at the top of the "
                    "folder, and a label written without an anchor does not say where it lies",
                )
            )
            continue
        if path.exists() and not inside(folder, path):
            not_checked.append(PassedOver(file=label, reason="a link out of the folder"))
            continue
        if is_lfs_pointer(path):
            not_checked.append(PassedOver(file=label, reason="a Git LFS pointer, not the file"))
            artifacts.append(_artifact(label, path, directory, None))
            continue
        artifacts.append(_artifact(label, path, directory, digest))
        suffix = path.suffix.lower()
        if suffix not in TREE | DELIMITED or not path.is_file():
            continue
        if Digest.of_file(path).value != digest:
            not_checked.append(
                PassedOver(
                    file=label,
                    reason="its bytes are not those checksums.sha256 records, so no candidate "
                    "is read from it",
                )
            )
        elif path.stat().st_size <= MAX_SEARCHED_BYTES:
            try:
                searched[label] = _stored(path)
            except (Refused, RefusedYamlError) as e:
                not_checked.append(
                    PassedOver(file=label, reason=f"refused: {e}, so no candidate is read from it")
                )

    tables = folder / TABLES
    for path in sorted(p for p in tables.rglob("*") if p.is_file()) if tables.is_dir() else []:
        label = path.relative_to(folder).as_posix()
        if label not in recorded:
            passed.append(
                PassedOver(
                    file=label,
                    reason="not in checksums.sha256, so the run recorded no digest for it, and "
                    "a file an earlier run left in the folder looks the same",
                )
            )

    report_digest = Digest.of_file(report).value
    if REPORT not in {artifact["id"] for artifact in artifacts}:
        artifacts.append(_artifact(REPORT, report, directory, report_digest))
    pins = {REPORT: report_digest}
    for name in PINNED_IN_SOURCE:
        if (folder / name).is_file() and inside(folder, folder / name):
            pins[name] = Digest.of_file(folder / name).value

    lines = text.split("\n")
    masked, fenced = _code_masked(lines)
    claims, items = [], []
    for number, (line, readable) in enumerate(zip(lines, masked, strict=True), start=1):
        where = f"{REPORT}, line {number}"
        if number in fenced:
            if printed(line):
                passed.append(
                    PassedOver(
                        file=REPORT,
                        reason=f"line {number}: inside a fenced code block, which prints a "
                        "command and not a result",
                    )
                )
            continue
        in_code = len(printed(line)) - len(printed(readable))
        if in_code > 0:
            passed.append(
                PassedOver(
                    file=REPORT,
                    reason=f"line {number}: {in_code} number(s) inside inline code, which "
                    "prints an identifier or a command and not a result",
                )
            )
        clocks = len(_CLOCK.findall(readable))
        if clocks:
            readable = _CLOCK.sub(lambda m: " " * len(m.group()), readable)
            passed.append(
                PassedOver(
                    file=REPORT,
                    reason=f"line {number}: {clocks} time(s) of day, which say when the report "
                    "was written and are no result",
                )
            )
        quantities = 0
        for found in printed(readable):
            if found.rule is not None or found.value is None:
                rule = found.rule.value if found.rule else "no value"
                passed.append(
                    PassedOver(
                        file=REPORT,
                        reason=f"line {number}: {found.text} is set aside by the rule {rule}",
                    )
                )
                continue
            quantities += 1
            claim_id = f"line-{number}-{quantities}"
            claims.append(
                {
                    "id": claim_id,
                    "text": line.strip(),
                    "where": where,
                    # The reader proposes the line as the claim's passage; nobody has accepted
                    # it, and a draft that matched it alone would pass as verified.
                    "evidence": [
                        {
                            "kind": "quote",
                            "artifact": REPORT,
                            "text": line.strip(),
                            "basis": "inferred",
                        }
                    ],
                }
            )
            percent = found.text.endswith("%")
            candidates = _candidates(claim_id, found.value, percent, searched)
            items.append(
                OpenItem(
                    id=f"{claim_id}/value",
                    claim=claim_id,
                    need=Need.VALUE,
                    asks=f"the address in a pinned table of the value {REPORT} prints as "
                    f"{found.text} on line {number}",
                    context={
                        "printed": found.text,
                        "value": found.value,
                        "percent": percent,
                        "position": quantities,
                        "line": number,
                        "text": line,
                        "candidates_found": len(candidates),
                    },
                    candidates=tuple(candidates[:MAX_CANDIDATES]),
                    # No candidate is called unique: a report line names no key or column to
                    # check a match's labels against, so one match may be chance.
                    reason="no address in the pinned tables matches"
                    if not candidates
                    else "a report line names no label to check a match against, so no "
                    "candidate is called unique",
                )
            )

    draft = {
        "schema_version": SCHEMA_VERSION,
        "project": _project(lines, folder),
        "provenance": {"generated_by": READER},
        "artifacts": artifacts,
        "claims": claims,
    }
    source = Source(
        reader=READER,
        reader_version=__version__,
        format=FORMAT,
        path=named(checksums),
        digest=hashlib.sha256(listed_raw).hexdigest(),
        pins=pins,
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
        not_checked=tuple(not_checked),
    )
