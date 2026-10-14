"""What the MCP server lets an agent read of an open-items file, and the one edit it makes.

`repro mcp` hands an agent the items a reader of another tool's files left open, one at a
time, and takes back one proposed assertion per call. This module is that logic without the
protocol, so it can be called and tested without an MCP client:

    inside        resolve a path given by the agent, refusing one that leaves the project root
    load_inside   load a manifest whose every artifact resolves inside the root
    packet        one open item, compact: the claim, the printed value, the sentence and its
                  line, each candidate's file, address, labels and stored value
    propose       append one inferred assertion that fills one open item, then check it

Every refusal is a `Refused`, which names the rule and says why. A refusal writes nothing.
"""

from __future__ import annotations

import pathlib
from typing import Any

import yaml
from claims.exceptions import ReproError
from claims.manifest import load
from claims.models import Basis, Manifest
from claims.open_items import FILLS, Need, OpenItem, OpenItems
from claims.open_items import read as read_items
from claims.verify import verify
from provenance_core import atomic_write
from pydantic import BaseModel, ConfigDict, ValidationError

#: How many candidates one packet lists. The count of the rest is given.
MAX_CANDIDATES = 10

#: How much of the sentence an item quotes one packet carries.
MAX_SENTENCE = 300

#: How much of a stored value one packet carries: a cell, never a file.
MAX_STORED = 80

#: What an agent's assertion is marked, and the only basis `propose` writes.
INFERRED = Basis.INFERRED.value


class Refused(ReproError):
    """A tool call the server will not carry out. Nothing was written."""

    def __init__(self, rule: str, detail: str) -> None:
        self.rule = rule
        self.detail = detail
        super().__init__(f"refused ({rule}): {detail}")


# ------------------------------------------------------------------------------------ paths


def inside(root: pathlib.Path, given: str | pathlib.Path) -> pathlib.Path:
    """`given`, resolved against `root` where relative, with every symlink followed. Refused
    where the result is not `root` or below it, which is how a symlink out is caught."""
    candidate = pathlib.Path(given).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise Refused(
            "outside_root", f"{given} resolves to {resolved}, outside the project root {root}"
        )
    return resolved


def load_inside(root: pathlib.Path, given: str | pathlib.Path) -> Manifest:
    """The manifest at `given`, refused where it or any artifact it declares resolves outside
    `root`: a read-only tool reads the files a manifest names, so those are paths too."""
    manifest = load(inside(root, given))
    for artifact in manifest.artifacts:
        try:
            inside(root, manifest.resolve(artifact))
        except Refused as e:
            raise Refused(
                "outside_root", f"artifact {artifact.id!r} of {manifest.path}: {e.detail}"
            ) from e
    return manifest


# ---------------------------------------------------------------------------------- packets


class Candidate(BaseModel):
    """One address a reader's search found a value at: never the file, only the cell."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact: str
    file: str
    address: str
    labels: tuple[str, ...]
    """The names the address carries: the keys of a pointer, a column and its row filter."""
    stored: str | None
    """The value at the address as the file holds it, or None where none was read."""
    conversion: str | None = None
    assertion: dict[str, Any]
    """The inferred assertion `propose_binding` would take for this candidate, as listed."""


class Packet(BaseModel):
    """One open item, small enough to act on without reading the project."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    item: str
    claim: str
    need: Need
    asks: str
    printed: tuple[str, ...]
    """The value the source states or prints for the claim, as it writes it. Empty where it
    states none, as a CODECHECK configuration does not."""
    sentence: str
    """The manuscript sentence, the task's question, or the output's comment, cut short."""
    line: int | None
    candidates: tuple[Candidate, ...]
    candidates_total: int
    unique: bool
    reason: str
    filled: bool
    total: int
    """Items in the file."""
    remaining: int
    """Items in the file not yet filled, this one included where it is open."""
    next_item: str | None
    """The next open item after this one in the file's order, or None."""


def stated_values(item: OpenItem) -> frozenset[str]:
    """Every value the source states for the item's claim, as written: what each candidate
    reports, the value a report prints, the values a task gives. Empty where none is stated."""
    found = {str(c["reported"]) for c in item.candidates if c.get("reported") is not None}
    if item.context.get("value") is not None:
        found.add(str(item.context["value"]))
    found.update(str(value) for value in item.context.get("values", ()) or ())
    return frozenset(found)


def _pointer_keys(pointer: str) -> list[str]:
    return [p.replace("~1", "/").replace("~0", "~") for p in pointer.split("/") if p]


def _address(locator: dict[str, Any]) -> tuple[str, tuple[str, ...]]:
    """The address as a line, and the labels it carries."""
    kind = locator.get("kind")
    if kind == "tree":
        pointer = str(locator.get("pointer", ""))
        return pointer or "/", tuple(_pointer_keys(pointer))
    column = str(locator.get("column", ""))
    if kind == "table_position":
        return f"column {column}, row {locator.get('row')}", (column, f"row {locator.get('row')}")
    where = locator.get("where") or {}
    filters = tuple(f"{key}={value}" for key, value in where.items())
    sheet = (f"sheet {locator['sheet']}",) if locator.get("sheet") else ()
    if column:
        said = f"column {column}" + (f" where {', '.join(filters)}" if filters else "")
        return said, (*sheet, column, *filters)
    rest = tuple(f"{k}={v}" for k, v in locator.items() if k != "kind")
    return f"{kind} {', '.join(rest)}", rest


def _stored(manifest: Manifest, assertion: dict[str, Any]) -> str | None:
    """The value at a candidate's address, read the way `verify` reads it, and only that."""
    try:
        probe = Manifest.model_validate(
            {
                "artifacts": manifest.artifacts,
                "claims": [{"id": "candidate", "text": "candidate", "evidence": [assertion]}],
                "path": manifest.path,
            }
        )
    except ValidationError:
        return None
    extracted = verify(probe).decisions[0].extracted
    if extracted is None:
        return None
    return extracted if len(extracted) <= MAX_STORED else f"{extracted[:MAX_STORED]}..."


def _fills(item: OpenItem, manifest: Manifest) -> bool:
    """Whether the claim holds an assertion of a kind that fills the item, as `tally` counts."""
    claim = next((c for c in manifest.claims if c.id == item.claim), None)
    return claim is not None and any(e.kind in FILLS[item.need] for e in claim.evidence)


def _draft(root: pathlib.Path, path: pathlib.Path, items: OpenItems) -> pathlib.Path:
    return inside(root, path.parent / items.manifest)


def _sentence(context: dict[str, Any]) -> tuple[str, int | None]:
    text = next(
        (str(context[key]) for key in ("text", "question", "comment") if context.get(key)), ""
    )
    line = context.get("line")
    text = " ".join(text.split())
    return (text if len(text) <= MAX_SENTENCE else f"{text[:MAX_SENTENCE]}..."), (
        line if isinstance(line, int) else None
    )


def packet(root: pathlib.Path, open_items: str, item_id: str | None, after: str | None) -> Packet:
    """One item of the open-items file: `item_id` where named, otherwise the first open item
    after `after` in the file's order (from the start where `after` is None). Refused where
    the named item is not in the file or no open item is left."""
    path = inside(root, open_items)
    items = read_items(path)
    manifest = load_inside(root, _draft(root, path, items))
    filled = {item.id: _fills(item, manifest) for item in items.items}
    ids = [item.id for item in items.items]
    for named in (item_id, after):
        if named is not None and named not in filled:
            raise Refused("item_not_in_open_items", f"{path.name} lists no item {named!r}")

    if item_id is not None:
        chosen = items.items[ids.index(item_id)]
    else:
        start = ids.index(after) + 1 if after is not None else 0
        chosen = next((i for i in items.items[start:] if not filled[i.id]), None)
        if chosen is None:
            raise Refused("no_open_item", f"no open item after {after or 'the start'}")
    position = ids.index(chosen.id)
    following = next((i.id for i in items.items[position + 1 :] if not filled[i.id]), None)

    paths = {a.id: a.path.as_posix() for a in manifest.artifacts}
    candidates = []
    for listed in chosen.candidates[:MAX_CANDIDATES]:
        address, labels = _address(dict(listed.get("locator") or {}))
        artifact = str(listed.get("artifact", ""))
        candidates.append(
            Candidate(
                artifact=artifact,
                file=paths.get(artifact, artifact),
                address=address,
                labels=labels,
                stored=_stored(manifest, listed),
                conversion=listed.get("conversion"),
                assertion=listed,
            )
        )
    sentence, line = _sentence(chosen.context)
    printed = chosen.context.get("printed")
    return Packet(
        item=chosen.id,
        claim=chosen.claim,
        need=chosen.need,
        asks=chosen.asks,
        printed=(str(printed),) if printed is not None else tuple(sorted(stated_values(chosen))),
        sentence=sentence,
        line=line,
        candidates=tuple(candidates),
        candidates_total=len(chosen.candidates),
        unique=chosen.unique,
        reason=chosen.reason,
        filled=filled[chosen.id],
        total=len(ids),
        remaining=sum(not done for done in filled.values()),
        next_item=following,
    )


# ---------------------------------------------------------------------------------- propose


class Proposal(BaseModel):
    """What `propose` wrote, and what the check found. Never a verification."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    draft: str
    claim: str
    item: str
    assertion: dict[str, Any]
    outcome: str
    """The check's word for the assertion: `matched` for a match, never `verified`."""
    said: str
    """The outcome as it is to be reported: `matched, inferred: not verified` for a match."""
    detail: str
    extracted: str | None
    counted_as_verified: bool = False


def propose(
    root: pathlib.Path,
    open_items: str,
    claim_id: str,
    assertion: dict[str, Any],
    item_id: str | None = None,
    basis: str | None = None,
) -> Proposal:
    """Append `assertion`, marked `basis: inferred`, to the claim in the draft an open-items
    file names, where it fills one of that claim's open items; then check it.

    Refused, with nothing written: a basis other than inferred, or `reviewed`; a claim the
    file lists no item for; a draft outside the root; an assertion of a kind that fills none
    of the claim's open items, or only items already filled; a `reported` other than the
    value the source states; an artifact the draft does not declare; and a draft holding
    comments, which a rewrite would drop. The write appends and edits nothing: no assertion
    the draft holds can be changed through it, and an item a declared assertion fills is
    filled.
    """
    stated = assertion.get("basis")
    if (basis is not None and basis != INFERRED) or (stated is not None and stated != INFERRED):
        raise Refused(
            "basis",
            f"this server writes basis: {INFERRED} and nothing else; declaring an assertion, "
            "or accepting one, is the author's",
        )
    if "reviewed" in assertion:
        raise Refused(
            "reviewed", "`reviewed` records an author's acceptance and is never written here"
        )

    path = inside(root, open_items)
    items = read_items(path)
    draft = _draft(root, path, items)
    open_for_claim = [item for item in items.items if item.claim == claim_id]
    if not open_for_claim:
        raise Refused(
            "claim_not_in_open_items", f"{path.name} lists no item for the claim {claim_id!r}"
        )
    if item_id is not None:
        open_for_claim = [item for item in open_for_claim if item.id == item_id]
        if not open_for_claim:
            raise Refused(
                "item_not_in_open_items", f"{path.name} lists no item {item_id!r} for {claim_id!r}"
            )

    before = load_inside(root, draft)
    kind = assertion.get("kind")
    fillable = [i for i in open_for_claim if kind in FILLS[i.need] and not _fills(i, before)]
    if not fillable:
        raise Refused(
            "fills_no_open_item",
            f"a {kind!r} assertion fills no open item of {claim_id!r}: "
            + ", ".join(
                f"{i.id} needs {i.need.value}{' and is filled' if _fills(i, before) else ''}"
                for i in open_for_claim
            ),
        )
    item = fillable[0]

    allowed = stated_values(item)
    if item.need is Need.VALUE and allowed and str(assertion.get("reported")) not in allowed:
        raise Refused(
            "reported_changed",
            f"reported {assertion.get('reported')!r} is not the value the source states "
            f"({', '.join(sorted(allowed))}); `reported` is never changed to make a check pass",
        )

    claim = next(c for c in before.claims if c.id == claim_id)
    text = draft.read_text(encoding="utf-8")
    if any(line.lstrip().startswith("#") for line in text.splitlines()):
        raise Refused("draft_has_comments", f"{draft.name} holds comments a rewrite would drop")
    document = yaml.safe_load(text)
    written = {**assertion, "basis": INFERRED}
    entry = next(c for c in document["claims"] if c.get("id") == claim_id)
    entry.setdefault("evidence", []).append(written)
    new_text = yaml.safe_dump(document, sort_keys=False, width=100, allow_unicode=True)
    try:
        after = Manifest.model_validate({**yaml.safe_load(new_text), "path": draft})
    except ValidationError as e:
        raise Refused("invalid_assertion", str(e.errors()[0]["msg"])) from e

    index = len(claim.evidence)
    added = next(c for c in after.claims if c.id == claim_id).evidence[index]
    if undeclared := set(added.artifacts) - {a.id for a in after.artifacts}:
        raise Refused(
            "artifact_undeclared",
            f"the assertion reads {', '.join(sorted(undeclared))}, which {draft.name} does not "
            "declare",
        )

    atomic_write(draft, new_text)
    checked = load(draft)
    report = verify(checked)
    position = [c.id for c in checked.claims].index(claim_id)
    decision = report.claims[position].decisions[index]
    return Proposal(
        draft=draft.relative_to(root).as_posix(),
        claim=claim_id,
        item=item.id,
        assertion=written,
        outcome=decision.said,
        said=f"{decision.said}, inferred: not verified",
        detail=decision.detail,
        extracted=decision.extracted,
    )
