"""The shapes on disk, validated once at the edge.

Every YAML file this package reads becomes a model here before any other module touches it.
The alternative -- passing the raw `dict` around and reaching into it with `r["source"]["local"]`
-- moves the failure from the file that is malformed to a line deep in a comprehension, and
reports it as a `KeyError` naming a key rather than a path naming a file.

Two conventions the corpus already contains, absorbed here rather than at each call site:

    a quotation      spelled `exact` in claims files, `text` in records
    a claims block   spelled `claims` in most papers, `evidence` in some

Reading only one spelling makes a command find nothing and report it, which is
indistinguishable from a paper that has no quotations yet.

Unknown fields are kept, not rejected. Records carry per-project metadata this package has no
opinion about, and 365 claims files predate these models; validation exists to catch a missing
required field, not to refuse a file for carrying an extra one.
"""

from __future__ import annotations

import pathlib
from typing import Annotated, Any, Literal

import yaml
from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
)

from citations.exceptions import ClaimFileError

Verbatim = Annotated[str, StringConstraints(strip_whitespace=False)]
"""A string kept exactly as written, against `_Base`'s `str_strip_whitespace`.

For the fields where surrounding whitespace is the content. A `TextQuoteSelector` prefix is
the text *immediately* before the passage, so its trailing space is what separates the last
word of the prefix from the first word of the quotation. Stripped, the two weld into a word
occurring nowhere, the anchor matches nothing, and every anchored quotation reports itself
ambiguous -- the feature failing silently in exactly the case it was added for.
"""


class _Base(BaseModel):
    """Shared configuration: keep unknown fields, allow construction by field name."""

    model_config = ConfigDict(extra="allow", populate_by_name=True, str_strip_whitespace=True)


class Quote(_Base):
    """One passage taken from a source, and where it was taken from."""

    text: str = Field(validation_alias=AliasChoices("exact", "text"))
    """The passage as quoted. Checked verbatim against the extracted source text."""

    prefix: Verbatim = ""
    """Text immediately preceding the passage in the source, used only to disambiguate.

    Together with `suffix` this is the W3C Web Annotation `TextQuoteSelector`. A passage that
    occurs once needs neither; a passage occurring more than once is not identified by its own
    words, and the two neighbours are what single out which occurrence the record means. Not
    matched on its own and never required -- a quotation that resolves uniquely is checked
    exactly as before.
    """

    suffix: Verbatim = ""
    """Text immediately following the passage in the source. See `prefix`."""

    section: str | None = None
    """The section it was taken from, as the source names it. Not verified."""

    page: int | None = None
    """The page it was taken from, when the source is paginated. Verified when present."""


class ClaimSource(_Base):
    """The artifact a paper's quotations were taken from, and how to reach it."""

    citation: str | None = None
    """The citation key this source corresponds to."""

    local: str | None = None
    """Path to the pinned copy, relative to the parent of the claims directory."""

    sha256: str | None = None
    """Hash of the pinned copy at the time the quotations were taken."""

    url: str | None = None
    """Where the copy was fetched from."""

    extract_cmd: str | None = None
    """The command that produced the extracted text the quotations resolve against."""

    note: str | None = None
    """Anything a reader needs in order to interpret the quotations."""

    @property
    def is_pinned(self) -> bool:
        """Whether this source carries a hash that `verify` can check the artifact against.

        An empty string is how the corpus spells "no pin", so it is not a pin.
        """
        return bool(self.sha256 and self.sha256.strip())


class Interpretation(_Base):
    """What someone takes the quotations to mean, and who that someone is.

    A quotation and a characterization of it are different objects with different truth
    conditions, and this package can only measure the first. `verify` resolves the strings in
    `Claim.quotes` against the pinned bytes; nothing reads `Claim.statement`, so a file whose
    quotation is exact and whose statement overreaches passes every check.

    The failure is not hypothetical. A record can pin a phrase that appears verbatim in a
    table cell describing a risk, and state that the phrase conditions an obligation stated
    somewhere else in the same table. The quotation resolves. The statement is wrong. What
    separates them is that the statement belongs to a reader -- often not the source's author
    -- and the file did not say so.

    Hence `whose`, which is required. A characterization with no owner is the shape the error
    takes: it reads as though the source made the claim, and the question of who is doing the
    reading never gets asked. Naming the party is usually enough to expose the problem,
    because the honest answer is frequently a different document by a different party.
    """

    says: str = ""
    """The characterization, in whoever's words it belongs to."""

    whose: str
    """Whose reading this is: a citation key, or `ours` for the citing paper's own.

    Required. This is the field the model exists for.
    """

    status: Literal["source", "ours", "third-party", "contested"] = "source"
    """How the reading stands. `contested` says a reading is on the record and disputed, which
    is a thing a claims file should be able to hold rather than resolve."""

    contest: str | None = None
    """What is wrong with the reading, where `status` is `contested`. Recorded, never checked."""


class Claim(_Base):
    """One statement a paper makes, and the quotations offered in support of it."""

    statement: str = ""
    """The claim in the paper's own words.

    Kept for every file written before `interpretation` existed. Where both are present,
    `interpretation.says` is the characterization and this is ignored.
    """

    interpretation: Interpretation | None = None
    """Who reads the quotations how. Absent on older files; never verified when present."""

    verified: bool = False
    """Whether the author marked the *quotations* as checked. Not computed by this package.

    It has never meant that the statement follows from them, and `interpretation` is where a
    file now says so in its own structure rather than in a convention nobody can read.
    """

    quotes: list[Quote] = Field(default_factory=list)
    """The passages cited in support. May be empty; an unsupported claim is a fact about
    the file, not an error in it."""

    notes: str | None = None
    """Why this claim matters, or what qualifies it."""

    hint: str | None = None
    """Where an upstream index said the support sits -- a line range, a paragraph number.

    Recorded and never verified. The index it addresses is not the artifact that is pinned: a
    remote parse of a PDF can be re-run and renumber every line, so a range taken from one is
    somewhere to start reading and not an address a result may be computed from. What is
    verified is `quotes`, matched against the pinned bytes. `Quote.page` is the locator that
    is checked, and a line number must never be written into it -- doing so would turn a hint
    into a verified address, and the page it names would be a page nobody looked at."""


class ClaimFile(_Base):
    """One `claims/*.yaml`: a pinned source and the claims drawn from it."""

    source: ClaimSource = Field(default_factory=ClaimSource)
    """The artifact the quotations were taken from."""

    claims: dict[str, Claim] = Field(
        default_factory=dict, validation_alias=AliasChoices("claims", "evidence")
    )
    """Claims by identifier. Both spellings of the block are accepted on the way in."""

    path: pathlib.Path | None = Field(default=None, exclude=True)
    """Where this file was read from. Set by the loader, never present in the YAML."""

    @property
    def name(self) -> str:
        """The file's stem, used to label a quotation in a report."""
        return self.path.stem if self.path else ""

    def artifact(self) -> pathlib.Path | None:
        """The pinned copy on disk, or None when the file names no source.

        Resolved against the parent of the claims directory, which is the convention the
        corpus uses. An absolute `local` resolves to itself.
        """
        if not self.path or not self.source.local:
            return None
        return (self.path.parent.parent / self.source.local).resolve()


class CitedBy(_Base):
    """How one paper cites a record."""

    key: str | None = None
    """The citation key that paper uses for this work."""


class Record(_Base):
    """One `records/*.yaml`: a work, its identifiers, and who cites it."""

    slug: str
    """Filename stem and primary identifier. Required -- a record without one cannot be
    reported against."""

    title: str = ""
    authors: list[str] = Field(default_factory=list)
    year: str = ""
    """Kept as a string: the corpus stores it quoted, and no arithmetic is done on it."""

    venue: str = ""
    doi: str = ""
    arxiv: str = ""
    url: str = ""
    et_al: bool = False

    sha256: str = ""
    """Hash of the local copy, when one has been pinned."""

    local: str = ""
    """Path to the local copy, relative to the library root."""

    cited_by: dict[str, CitedBy] = Field(default_factory=dict)
    """Papers citing this work, by project name."""

    preferred_key: str = ""
    """The citation key a new bibliography should use for this work.

    `cited_by` records what each paper actually writes, and those diverge honestly: a key is
    part of a paper's own source, and renaming one means editing every `\\cite` in it. So the
    divergence is kept and this names which of them to copy forward. It is a recommendation
    and nothing enforces it.

    `slug` cannot serve: it is an identifier derived from the DOI or arXiv id, and
    `arxiv-2301-04709` is not something anyone types into a citation. Set it in
    `enrichment.yaml`, keyed by slug, like every other fact resolved after the bibliographies
    were written."""

    quotes: list[Quote] = Field(default_factory=list)
    """Passages taken from this work, when the record itself carries them."""

    @field_validator("year", mode="before")
    @classmethod
    def _year_to_str(cls, v: Any) -> str:
        """YAML gives `year: 2008` as an int and `year: '2008'` as a string. Both are years."""
        return "" if v is None else str(v)

    @property
    def is_pinned(self) -> bool:
        return bool(self.sha256 and self.sha256.strip())


def _load_yaml(path: pathlib.Path) -> dict[str, Any]:
    """Parse one YAML file into a mapping, naming the file when it is not one."""
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:
        raise ClaimFileError(path, f"not valid YAML: {e}") from e
    except OSError as e:
        raise ClaimFileError(path, f"could not be read: {e}") from e
    if not isinstance(raw, dict):
        raise ClaimFileError(
            path, f"expected a mapping at the top level, found {type(raw).__name__}"
        )
    return raw


def load_claim_file(path: pathlib.Path) -> ClaimFile:
    """Read one claims file, or raise `ClaimFileError` naming it and the field at fault."""
    raw = _load_yaml(path)
    try:
        model = ClaimFile.model_validate(raw)
    except ValidationError as e:
        raise ClaimFileError(path, _first_problem(e)) from e
    model.path = path
    return model


def load_record(path: pathlib.Path) -> Record:
    """Read one record, or raise `ClaimFileError` naming it and the field at fault."""
    raw = _load_yaml(path)
    raw.setdefault("slug", path.stem)
    try:
        return Record.model_validate(raw)
    except ValidationError as e:
        raise ClaimFileError(path, _first_problem(e)) from e


def _first_problem(e: ValidationError) -> str:
    """One line a reader can act on, rather than pydantic's full multi-error block."""
    first = e.errors()[0]
    where = ".".join(str(p) for p in first["loc"]) or "(top level)"
    return f"{where}: {first['msg']}"


__all__ = [
    "CitedBy",
    "Claim",
    "ClaimFile",
    "ClaimSource",
    "Quote",
    "Record",
    "load_claim_file",
    "load_record",
]
