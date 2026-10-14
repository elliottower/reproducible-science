"""What a reader of another tool's files could not fill, and how much of it has been filled since.

A reader converts another reproducibility tool's files into a draft manifest. It writes every
field the other format states, and nothing it would have to guess: which sentence of a paper a
result file supports, or which address in the file holds a number the paper prints. Each such
gap is an open item, written to a file beside the draft, `open-items.json`.

Whoever fills an item, a person or an agent, writes an assertion into the draft and marks it
`basis: inferred`. `claims verify` then checks it as any other. `tally` reads the two files and
the check, and counts each claim one way:

    reader        no item was opened for it: the reader bound it from what the source states
    bound         every item is filled, and every assertion filling one matched
    not_matching  every item is filled, and an assertion filling one did not match
    open          an item is not filled
    outside       no item names it, and it holds an inferred assertion or none at all

The first is what the reader bound; the next three are what was left to inference. An
inferred assertion that matched is a proposal that held. Nothing here counts it as verified.

An item may carry candidates: assertions a deterministic search of the files found for it,
which the reader lists and never writes into the draft, however few there are. A value found
somewhere in a file is not a value fetched from a stated address. An item is `unique` where
exactly one candidate passes the reader's guards, and that candidate is listed first; where
none does, or several do, `reason` says which. The count says how many items had a unique
candidate, several, one that fails the guards, or none.
"""

from __future__ import annotations

import collections
import enum
import json
import pathlib
from typing import Any

import yaml
from provenance_core import atomic_write
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from claims.exceptions import ReproError
from claims.manifest import load
from claims.models import Basis, Decision, Digest, Manifest, Outcome
from claims.verify import verify

#: The version every open-items file carries.
OPEN_ITEMS_VERSION = "reproducible.science/open-items/0.1-experimental"

#: The two files a reader writes, in the directory it is given.
DRAFT_NAME = "repro.draft.yaml"
ITEMS_NAME = "open-items.json"

_SHA256_HEX = r"^[a-f0-9]{64}$"


class Need(enum.StrEnum):
    """What an item asks for, by the kinds of assertion that answer it."""

    VALUE = "value"
    """A stored value the claim reports: a `metric`, `table`, `value`, `aggregate` or
    `correspondence`."""
    PASSAGE = "passage"
    """The passage of the manuscript that makes the claim: a `quote`."""


#: The evidence kinds that fill each need.
FILLS: dict[Need, frozenset[str]] = {
    Need.VALUE: frozenset({"metric", "table", "value", "aggregate", "correspondence"}),
    Need.PASSAGE: frozenset({"quote"}),
}


class OpenItemsError(ReproError):
    """An open-items file, or the draft it names, could not be read or written."""


class Source(BaseModel):
    """The file a reader read, as it was read."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reader: str
    """The command that read it."""
    reader_version: str
    format: str
    """The other tool's format, as that tool names it."""
    path: str
    """As the reader was given it."""
    digest: str = Field(pattern=_SHA256_HEX)
    """sha256 of the bytes read."""
    pins: dict[str, str] = {}
    """Other files the reading depended on, by name, each with the sha256 it was read at."""
    url: str = ""
    """Where the bytes were fetched from, where they were fetched."""


class OpenItem(BaseModel):
    """One thing the source does not state, for one claim of the draft."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    claim: str
    """The id of the claim in the draft it is for."""
    need: Need
    asks: str
    """What is missing, in words."""
    context: dict[str, Any] = {}
    """What the source says that bears on it, in the source's words."""
    candidates: tuple[dict[str, Any], ...] = ()
    """Assertions a search of the files found for it, never written into the draft."""
    unique: bool = False
    """Exactly one candidate passes the reader's guards, and it is the first listed. A lead
    for whoever fills the item, never a binding."""
    reason: str = ""
    """Why no candidate is unique, where the search found any."""


class OpenItems(BaseModel):
    """Everything a reader left open in one draft."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = OPEN_ITEMS_VERSION
    manifest: str
    """The draft's file name, in the directory this file is in. A name only: an open-items
    file never points a reader at a file outside its own directory."""
    manifest_digest: str = Field(pattern=_SHA256_HEX)
    """sha256 of the draft as the reader wrote it."""
    source: Source
    items: tuple[OpenItem, ...] = ()

    @field_validator("manifest")
    @classmethod
    def _a_name_in_this_directory(cls, value: str) -> str:
        if not value or value in (".", "..") or "/" in value or "\\" in value:
            raise ValueError(f"{value!r} is not a file name in this directory")
        return value


def write_draft(
    directory: pathlib.Path, document: dict, source: Source, items: tuple[OpenItem, ...]
) -> pathlib.Path:
    """Write a reader's draft and its open items into `directory`, refusing to overwrite either.

    Returns the path of the open-items file, which names the draft and the digest of the bytes
    written.
    """
    draft, listed = directory / DRAFT_NAME, directory / ITEMS_NAME
    for target in (draft, listed):
        if target.exists():
            raise OpenItemsError(f"{target} exists, and a reader never overwrites a file")
    text = yaml.safe_dump(document, sort_keys=False, width=100, allow_unicode=True)
    # Validated before anything is written, so a reader that builds a manifest this package
    # cannot load fails here and leaves nothing behind.
    try:
        manifest = Manifest.model_validate({**yaml.safe_load(text), "path": draft})
    except ValidationError as e:
        raise OpenItemsError(f"the draft does not load as a manifest: {e}") from e
    declared = {claim.id for claim in manifest.claims}
    if stray := sorted({item.claim for item in items} - declared):
        raise OpenItemsError(f"items name claims the draft does not declare: {', '.join(stray)}")
    written = OpenItems(
        manifest=DRAFT_NAME, manifest_digest=Digest.of_text(text).value, source=source, items=items
    )
    directory.mkdir(parents=True, exist_ok=True)
    atomic_write(draft, text)
    atomic_write(listed, written.model_dump_json(indent=2) + "\n")
    return listed


def read(path: pathlib.Path) -> OpenItems:
    try:
        return OpenItems.model_validate_json(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise OpenItemsError(f"{path} could not be read: {e}") from e
    except ValidationError as e:
        raise OpenItemsError(f"{path} is not an open-items file: {e}") from e


# ------------------------------------------------------------------------------------ tally


class ClaimState(enum.StrEnum):
    READER = "reader"
    BOUND = "bound"
    NOT_MATCHING = "not_matching"
    OPEN = "open"
    OUTSIDE = "outside"


class ItemFill(BaseModel):
    """One item, and the assertions of the claim that fill it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    need: Need
    filled: bool
    by: tuple[Basis, ...] = ()
    """The basis of each assertion that fills it."""
    outcomes: tuple[Outcome, ...] = ()
    """The outcome of each assertion that fills it, in the same order."""
    candidates: int = 0
    unique: bool = False


class ClaimTally(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    claim: str
    state: ClaimState
    items: tuple[ItemFill, ...] = ()


class Tally(BaseModel):
    """How a draft's claims split between what its source stated and what was left open."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    open_items: str
    manifest: str
    manifest_changed: bool
    """Whether the draft is no longer the bytes the reader wrote."""
    source: Source
    claims: dict[ClaimState, int]
    """Each state, with 0 where no claim is in it. They add up to `total`."""
    total: int
    left_open_by_reader: int
    """Claims with at least one item: what the reader could not bind alone."""
    items: dict[str, int]
    assertions: dict[Basis, dict[str, int]]
    """Every assertion of the draft by basis and outcome, an inferred match as `matched`."""
    per_claim: tuple[ClaimTally, ...]


def _fill(item: OpenItem, evidence: tuple, decisions: tuple[Decision, ...]) -> ItemFill:
    filling = [
        (found, decision)
        for found, decision in zip(evidence, decisions, strict=True)
        if found.kind in FILLS[item.need]
    ]
    return ItemFill(
        id=item.id,
        need=item.need,
        filled=bool(filling),
        by=tuple(found.counted for found, _ in filling),
        outcomes=tuple(decision.outcome for _, decision in filling),
        candidates=len(item.candidates),
        unique=item.unique,
    )


def _state(claim_items: tuple[ItemFill, ...], evidence: tuple) -> ClaimState:
    if not claim_items:
        if evidence and not any(found.counted is Basis.INFERRED for found in evidence):
            return ClaimState.READER
        return ClaimState.OUTSIDE
    if not all(fill.filled for fill in claim_items):
        return ClaimState.OPEN
    if all(outcome is Outcome.VERIFIED for fill in claim_items for outcome in fill.outcomes):
        return ClaimState.BOUND
    return ClaimState.NOT_MATCHING


def tally(path: pathlib.Path) -> Tally:
    """Count, for one open-items file, how its draft's claims split. Runs `verify` over the
    draft, which executes nothing and writes nothing."""
    open_items = read(path)
    draft = path.parent / open_items.manifest
    manifest = load(draft)
    report = verify(manifest)

    by_claim: dict[str, list[OpenItem]] = collections.defaultdict(list)
    for item in open_items.items:
        by_claim[item.claim].append(item)
    unknown = sorted(set(by_claim) - {claim.id for claim in manifest.claims})
    if unknown:
        raise OpenItemsError(
            f"{path} has items for claims {', '.join(unknown)}, which {draft.name} no longer "
            "declares; an item is closed by filling it, never by deleting its claim"
        )

    per_claim = []
    for claim, assessment in zip(manifest.claims, report.claims, strict=True):
        fills = tuple(
            _fill(item, claim.evidence, assessment.decisions) for item in by_claim[claim.id]
        )
        per_claim.append(
            ClaimTally(claim=claim.id, state=_state(fills, claim.evidence), items=fills)
        )

    states = collections.Counter(entry.state for entry in per_claim)
    fills = [fill for entry in per_claim for fill in entry.items]
    assertions: dict[Basis, dict[str, int]] = {basis: {} for basis in Basis}
    for decision in report.decisions:
        row = assertions[decision.basis]
        row[decision.said] = row.get(decision.said, 0) + 1
    return Tally(
        open_items=path.as_posix(),
        manifest=draft.as_posix(),
        manifest_changed=Digest.of_file(draft).value != open_items.manifest_digest,
        source=open_items.source,
        claims={state: states[state] for state in ClaimState},
        total=len(per_claim),
        left_open_by_reader=sum(1 for entry in per_claim if entry.items),
        items={
            "total": len(fills),
            "open": sum(not fill.filled for fill in fills),
            "filled": sum(fill.filled for fill in fills),
            "filled_and_passing": sum(
                fill.filled and all(o is Outcome.VERIFIED for o in fill.outcomes) for fill in fills
            ),
            "filled_by_inferred": sum(fill.filled and Basis.INFERRED in fill.by for fill in fills),
            "filled_by_declared_only": sum(
                fill.filled and Basis.INFERRED not in fill.by for fill in fills
            ),
            "with_unique_candidate": sum(fill.unique for fill in fills),
            "with_several_candidates": sum(
                not fill.unique and fill.candidates > 1 for fill in fills
            ),
            "with_one_not_passing": sum(not fill.unique and fill.candidates == 1 for fill in fills),
            "with_no_candidate": sum(fill.candidates == 0 for fill in fills),
        },
        assertions=assertions,
        per_claim=tuple(per_claim),
    )


def tally_json(found: Tally) -> str:
    return json.dumps(found.model_dump(mode="json"), indent=2)
