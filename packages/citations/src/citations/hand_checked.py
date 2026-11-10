"""Which quotations an author compared against the rendered page, and whether that still holds.

An extractor reads pinned bytes identically every time, so a passage it misread when the
quotation was pinned is misread the same way on every run, and no digest can show it. Only a
person who has looked at the page can say the reading is right. This module records that a
person did, and nothing more: a quotation on the list keeps its computed outcome, and the hand
check is reported beside it, never instead of it.

The list for `claims/smith2019.yaml` is `claims/smith2019.checked.txt`, a plain file beside it:

    # compared against the printed page
    orthogonal-cores    3f9a1c2b4d5e  p.4   # Table 2, second column
    main-result/2       77ab01c4e9d2

One quotation per line: its id, the fingerprint `citations verify` gives it, and optionally the
page as `p.N`; `#` starts a note. The id is the claim's id where the claim has one quotation, or
`<claim id>/<n>` for its n-th, counting from 1. The fingerprint is of the quotation's text, the
source's `sha256` and its `derived_sha256` as the claims file records them, so editing any of
the three after the passage was listed leaves the hand check covering nothing, and verify says
so and prints the fingerprint the quotation has now. A line with no fingerprint covers nothing
either, and is reported the same way: that is how an author learns the fingerprint to write.
An id that names no quotation is reported, never ignored.

The file's SHA-256 is recorded, and the report gives one digest over every list it read, so a
run's reliance on them is on record. The suffix is `.txt`, not `.yaml`, so `verify` never reads
the list as a claims file.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re

from pydantic import BaseModel, Field

from citations.exceptions import CitationsError
from citations.models import ClaimFile

#: The list beside `claims/<stem>.yaml` is `claims/<stem>.checked.txt`.
SUFFIX = ".checked.txt"

#: Hex characters of a fingerprint: enough to tell an edit from none, short enough to copy.
FINGERPRINT_CHARS = 12

_FINGERPRINT = re.compile(rf"[0-9a-f]{{{FINGERPRINT_CHARS}}}")
_PAGE = re.compile(r"p\.?(\d+)")


class Entry(BaseModel):
    """One line of a list: a quotation an author compared against the page."""

    id: str
    fingerprint: str = ""
    """What the quotation was when it was listed. Empty where the line gives none."""
    page: int | None = None
    note: str = ""


class Listed(BaseModel):
    """One list, read from the file beside a claims file."""

    claims_file: str
    path: str
    sha256: str
    """Of the file's bytes, so the report records which list it was read against."""
    entries: list[Entry] = Field(default_factory=list)


class Covered(BaseModel):
    """A quotation the hand check covers, with the outcome verify computed for it."""

    claim: str
    """`<claims file>:<claim id>`, as every other part of the report names a quotation."""
    id: str
    quote: str
    state: str
    """The computed outcome, unchanged by the hand check."""
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


class Unknown(BaseModel):
    """An id on a list that names no quotation in its claims file."""

    path: str
    id: str


class HandChecks(BaseModel):
    """Every list a run read, and what each covers."""

    sha256: str
    """Over every list read, by name and digest, so one value says which lists a run used."""
    passages: int = 0
    """Every quotation the run checked, listed or not."""
    lists: list[Listed] = Field(default_factory=list)
    covered: list[Covered] = Field(default_factory=list)
    stale: list[Stale] = Field(default_factory=list)
    unknown: list[Unknown] = Field(default_factory=list)

    @property
    def outcomes(self) -> dict[str, int]:
        """How many covered quotations had each computed outcome."""
        out: dict[str, int] = {}
        for c in self.covered:
            out[c.state] = out.get(c.state, 0) + 1
        return out


def list_path(claims_file: pathlib.Path) -> pathlib.Path:
    return claims_file.with_name(claims_file.stem + SUFFIX)


def fingerprint(text: str, sha256: str | None, derived_sha256: str | None) -> str:
    """Of a quotation as the claims file records it: its text and its source's two digests."""
    said = json.dumps([text, sha256 or "", derived_sha256 or ""], ensure_ascii=False)
    return hashlib.sha256(said.encode("utf-8")).hexdigest()[:FINGERPRINT_CHARS]


def read(path: pathlib.Path, claims_file: str) -> Listed:
    """A list: one quotation id per line, then its fingerprint and `p.N` in either order.

    A word that is neither is refused rather than dropped, naming the line, as `citations
    audit` refuses a second key on one line: a mistyped page silently read as nothing would
    leave the record saying less than its author wrote.
    """
    raw = path.read_bytes()
    try:
        # `utf-8-sig`, so a byte-order mark an editor wrote is not read into the first id.
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise CitationsError(
            f"{path}: not UTF-8 (byte {e.start}); save the checked list as UTF-8"
        ) from e
    entries: list[Entry] = []
    seen: set[str] = set()
    for n, line in enumerate(text.splitlines(), start=1):
        body, _, note = line.partition("#")
        words = body.split()
        if not words:
            continue
        entry = Entry(id=words[0], note=note.strip())
        for word in words[1:]:
            if _FINGERPRINT.fullmatch(word) and not entry.fingerprint:
                entry.fingerprint = word
            elif (page := _PAGE.fullmatch(word)) and entry.page is None:
                entry.page = int(page[1])
            else:
                raise CitationsError(
                    f"{path}:{n}: a quotation id, then its {FINGERPRINT_CHARS}-character "
                    f"fingerprint and `p.N`, with any note after a `#`; read {line.strip()!r}"
                )
        if entry.id not in seen:
            seen.add(entry.id)
            entries.append(entry)
    return Listed(
        claims_file=claims_file,
        path=str(path),
        sha256=hashlib.sha256(raw).hexdigest(),
        entries=entries,
    )


def quotation_ids(cf: ClaimFile) -> dict[tuple[str, int], list[str]]:
    """The ids that name each quotation, keyed by claim id and position from 0: `<claim>/<n>`
    always, and the claim id alone where the claim has one quotation."""
    out: dict[tuple[str, int], list[str]] = {}
    for cid, claim in cf.claims.items():
        quoted = [i for i, q in enumerate(claim.quotes) if q.text]
        for i in quoted:
            out[(cid, i)] = [f"{cid}/{i + 1}"] + ([cid] if len(quoted) == 1 else [])
    return out


def digest(lists: list[Listed]) -> str:
    """One SHA-256 over every list, by claims file and file digest, in a fixed order."""
    lines = sorted(f"{x.sha256}  {x.claims_file}\n" for x in lists)
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()
