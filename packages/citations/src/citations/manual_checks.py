"""Manual checks: an optional record that a person compared a quotation with the page.

The automatic check is the one that decides: a quotation resolves in its pinned source or it
does not. A manual check is provenance beside it. It changes no outcome and no exit code, warns
nobody, and `citations verify` prints nothing about it unless `--show-manual` asks; `--json`
records it under `manual_checks`.

The list for `claims/smith2019.yaml` is `claims/smith2019.manual.txt`, a plain file beside it:

    # compared against the printed page
    orthogonal-cores    3f9a1c2b4d5e  p.4   # Table 2, second column
    main-result/2       77ab01c4e9d2

One quotation per line: its id, its fingerprint, and optionally the page as `p.N`; `#` starts a
note. `citations manual-check` writes the line. The id is the claim's id where the claim has one
quotation, or `<claim id>/<n>` for its n-th, counting from 1; where a claim's id is itself
another quotation's `<claim id>/<n>`, that id names the other quotation, and the claim's is
`<claim id>/1`.

The fingerprint is of what the person compared: the quotation's text, the source's `sha256`,
the reader the source declares (`extract_cmd`, or its built-in extractor), and the reading
itself, which is the `derived_sha256` the claims file records or, where it records none, the
digest of the text verify extracted. Where any of them changed after the line was written, the
manual check is recorded as stale, with the fingerprint the quotation has now. The extractor's
version string is not in it: the same text read by two builds of one program is the same
reading, and a fingerprint that moved with the build would go stale on every machine.

Ids are compared in Unicode NFC, on the list and in the claims file alike.

A line that does not parse, a quotation listed twice, an id naming no quotation, a list
beside no claims file, and a list that cannot be read, is not a regular file or is larger than
`MAX_BYTES` are recorded, and change nothing else. The file's SHA-256 is recorded,
with one digest over every list read. The suffix is `.txt`, not `.yaml`, so `verify` never
reads the list as a claims file.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import stat
import unicodedata

from pydantic import BaseModel, Field

from citations.models import ClaimFile, ClaimSource

#: The list beside `claims/<stem>.yaml` is `claims/<stem>.manual.txt`.
SUFFIX = ".manual.txt"

#: Hex characters of a fingerprint: enough to tell an edit from none, short enough to copy.
FINGERPRINT_CHARS = 12

#: The largest list read. One line names one quotation and runs to about 40 bytes, plus its note,
#: so 1 MiB holds some 10,000 manual checks: more than any claims file has quotations, each
#: compared with the page by a person. A list past it was not written that way, and reading it
#: whole would cost a run's memory for no record anyone made by hand.
MAX_BYTES = 1 << 20

#: Opened without blocking, so a FIFO or a terminal where a list should be is found at `fstat` and
#: recorded, rather than waiting for a writer that never comes. Neither flag exists everywhere.
_OPEN_FLAGS = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)

_FINGERPRINT = re.compile(rf"[0-9a-fA-F]{{{FINGERPRINT_CHARS}}}")
_PAGE = re.compile(r"p\.?(\d+)")


class Entry(BaseModel):
    """One line of a list: a quotation an author compared against the page."""

    id: str
    line: int
    """Where in the file, counting from 1, so a problem can name it."""
    fingerprint: str = ""
    """What the quotation was when it was listed. Empty where the line gives none."""
    page: int | None = None
    note: str = ""

    def written(self) -> str:
        """The line as the list holds it."""
        words = [self.id, self.fingerprint] + ([f"p.{self.page}"] if self.page is not None else [])
        return "  ".join(w for w in words if w) + (f"  # {self.note}" if self.note else "")


class Listed(BaseModel):
    """One list, read from the file beside a claims file."""

    claims_file: str
    path: str
    sha256: str
    """Of the file's bytes, so the report records which list it was read against."""
    entries: list[Entry] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)
    """Lines that did not parse or name a quotation listed already, each with its line number.
    Recorded and skipped."""


class Covered(BaseModel):
    """A quotation a manual check covers, with the outcome verify computed for it."""

    claim: str
    """`<claims file>:<claim id>`, as every other part of the report names a quotation."""
    id: str
    quote: str
    state: str
    """The computed outcome, unchanged by the manual check."""
    page: int | None = None
    note: str = ""


class Stale(BaseModel):
    """A listed quotation whose text, source digest or reading changed after it was listed."""

    claim: str
    id: str
    listed: str
    """The fingerprint on the list; empty where the line gave none."""
    now: str
    """The fingerprint the quotation has now: what to write once it is checked again."""


class Unverifiable(BaseModel):
    """A listed quotation whose source was not read here and whose claims file records no
    `derived_sha256`, so there is no reading to compare the listed fingerprint with. Not stale:
    on a machine holding the source the same line may be current."""

    claim: str
    id: str
    listed: str


class Unknown(BaseModel):
    """An id on a list that names no quotation in its claims file."""

    path: str
    id: str


class ManualChecks(BaseModel):
    """Every list a run read, and what each covers."""

    sha256: str
    """Over every list read, by name and digest, so one value says which lists a run used."""
    passages: int = 0
    """Every quotation the run checked, listed or not."""
    lists: list[Listed] = Field(default_factory=list)
    covered: list[Covered] = Field(default_factory=list)
    stale: list[Stale] = Field(default_factory=list)
    unverifiable: list[Unverifiable] = Field(default_factory=list)
    unknown: list[Unknown] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)
    """Every list's `problems`, and every line naming a quotation another line names."""
    orphans: list[str] = Field(default_factory=list)
    """Lists with no claims file beside them that verify read: a claims file renamed or
    removed, or one that did not parse. What they list is checked against nothing."""

    @property
    def outcomes(self) -> dict[str, int]:
        """How many covered quotations had each computed outcome."""
        out: dict[str, int] = {}
        for c in self.covered:
            out[c.state] = out.get(c.state, 0) + 1
        return out


def nfc(id: str) -> str:
    """An id in Unicode NFC, so `café` typed composed and `café` saved decomposed are one id."""
    return unicodedata.normalize("NFC", id)


def list_path(claims_file: pathlib.Path) -> pathlib.Path:
    return claims_file.with_name(claims_file.stem + SUFFIX)


def fingerprint(text: str, sha256: str | None, reader: str | None, reading: str) -> str:
    """Of a quotation and the reading it was judged against: its text, the source's `sha256`,
    the reader the source declares, and the digest of the text that reader produced."""
    said = json.dumps([text, sha256 or "", reader or "", reading], ensure_ascii=False)
    return hashlib.sha256(said.encode("utf-8")).hexdigest()[:FINGERPRINT_CHARS]


def reading(source: ClaimSource, extraction_digest: str) -> str:
    """The digest of the reading: the `derived_sha256` the claims file records, or where it
    records none, that of the text verify extracted. Empty where neither exists."""
    return source.derived_sha256 or extraction_digest


def now(text: str, source: ClaimSource, extraction_digest: str) -> str:
    """The fingerprint a quotation has now, or empty where there is no reading to name."""
    read = reading(source, extraction_digest)
    return fingerprint(text, source.sha256, source.reader, read) if read else ""


def read(path: pathlib.Path, claims_file: str) -> Listed:
    """A list: one quotation id per line, then its fingerprint and `p.N` in either order.

    A line that does not parse, and a second line for one id, is recorded in `problems` with
    its line number and skipped. A list that cannot be read (no permission, any `OSError`), is
    not a regular file (a directory, a FIFO, a device) or is larger than `MAX_BYTES` is recorded
    there with no entries and an empty `sha256`. Nothing in a list stops a run.
    """
    listed = Listed(claims_file=claims_file, path=str(path), sha256="")
    try:
        fd = os.open(path, _OPEN_FLAGS)
    except OSError as e:
        listed.problems.append(f"{path}: not read ({e.strerror or e})")
        return listed
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        listed.problems.append(f"{path}: not read, not a regular file")
        return listed
    try:
        with os.fdopen(fd, "rb") as f:
            raw = f.read(MAX_BYTES + 1)
    except OSError as e:
        listed.problems.append(f"{path}: not read ({e.strerror or e})")
        return listed
    if len(raw) > MAX_BYTES:
        listed.problems.append(
            f"{path}: not read, larger than {MAX_BYTES:,} bytes; a list of manual checks has "
            "one line per quotation a person compared with the page"
        )
        return listed
    listed.sha256 = hashlib.sha256(raw).hexdigest()
    try:
        # `utf-8-sig`, so a byte-order mark an editor wrote is not read into the first id.
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        listed.problems.append(f"{path}: not UTF-8 (byte {e.start}); save the list as UTF-8")
        return listed
    seen: dict[str, int] = {}
    for n, line in enumerate(text.splitlines(), start=1):
        try:
            entry = _entry(line, n)
        except ValueError as e:
            listed.problems.append(f"{path}:{n}: {e}")
            continue
        if entry is None:
            continue
        if entry.id in seen:
            listed.problems.append(
                f"{path}:{n}: `{entry.id}` is listed already, on line {seen[entry.id]}"
            )
            continue
        seen[entry.id] = n
        listed.entries.append(entry)
    return listed


def _entry(line: str, n: int) -> Entry | None:
    """One line's entry, None for a blank or comment line, or ValueError saying what is wrong."""
    body, _, note = line.partition("#")
    words = body.split()
    if not words:
        return None
    entry = Entry(id=nfc(words[0]), line=n, note=note.strip())
    for word in words[1:]:
        if _FINGERPRINT.fullmatch(word) and not entry.fingerprint:
            if word != word.lower():
                raise ValueError(
                    f"fingerprints are lowercase, as verify records them; read {word!r}"
                )
            entry.fingerprint = word
        elif (page := _PAGE.fullmatch(word)) and entry.page is None:
            entry.page = int(page[1])
        else:
            raise ValueError(
                f"a quotation id, then its {FINGERPRINT_CHARS}-character fingerprint and `p.N`, "
                f"with any note after a `#`; read {line.strip()!r}"
            )
    return entry


def line(id: str, fingerprint: str, page: int | None, note: str) -> str:
    """The line for one manual check, or ValueError where `read` would not read it back as the
    same id, fingerprint, page and note: an id with a space or a `#`, a note holding a character
    `str.splitlines` breaks a line at, a page below 1."""
    if page is not None and page < 1:
        raise ValueError(f"a page is 1 or more; read {page}")
    entry = Entry(id=nfc(id), line=1, fingerprint=fingerprint, page=page, note=note.strip())
    written = entry.written()
    try:
        back = _entry(written, 1) if len(written.splitlines()) == 1 else None
    except ValueError:
        back = None
    if back != entry:
        raise ValueError(
            f"the line {written!r} would not read back as written; an id holds no space or `#`, "
            "and a note no line or page break"
        )
    return written


def quotation_ids(cf: ClaimFile) -> dict[tuple[str, int], list[str]]:
    """The ids that name each quotation, keyed by claim id and position from 0: `<claim>/<n>`
    always, and the claim id alone where the claim has one quotation and the id is not already
    another quotation's `<claim>/<n>`, so no id names two quotations. Each id is in NFC, as
    `read` reads a list's."""
    quoted = {
        cid: [i for i, q in enumerate(claim.quotes) if q.text] for cid, claim in cf.claims.items()
    }
    positional = {nfc(f"{cid}/{i + 1}") for cid, at in quoted.items() for i in at}
    out: dict[tuple[str, int], list[str]] = {}
    for cid, at in quoted.items():
        alone = len(at) == 1 and nfc(cid) not in positional
        for i in at:
            out[(cid, i)] = [nfc(f"{cid}/{i + 1}")] + ([nfc(cid)] if alone else [])
    return out


class Matched(BaseModel):
    """A list read against its claims file."""

    found: dict[tuple[str, int], Entry] = Field(default_factory=dict)
    """Each listed quotation's entry, keyed as `quotation_ids` keys it."""
    unknown: list[Entry] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)
    """Lines naming a quotation an earlier line names under its other id, which are skipped."""


def match(listed: Listed, cf: ClaimFile) -> Matched:
    """Which quotation each entry names. The first line naming a quotation is the one read."""
    by_id = {name: key for key, names in quotation_ids(cf).items() for name in names}
    out = Matched()
    for entry in listed.entries:
        key = by_id.get(entry.id)
        if key is None:
            out.unknown.append(entry)
        elif key in out.found:
            was = out.found[key]
            out.problems.append(
                f"{listed.path}:{entry.line}: `{entry.id}` names the quotation line {was.line} "
                f"lists as `{was.id}`"
            )
        else:
            out.found[key] = entry
    return out


def orphans(root: pathlib.Path, files: list[ClaimFile]) -> list[str]:
    """The lists in `root` beside no claims file in `files`."""
    beside = {list_path(cf.path) for cf in files if cf.path is not None}
    return [str(p) for p in sorted(root.glob("*" + SUFFIX)) if p not in beside]


def digest(lists: list[Listed]) -> str:
    """One SHA-256 over every list, by claims file and file digest, in a fixed order."""
    lines = sorted(f"{x.sha256}  {x.claims_file}\n" for x in lists)
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()
