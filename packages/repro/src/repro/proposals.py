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

import dataclasses
import datetime
import json
import mimetypes
import os
import pathlib
import uuid
from typing import Any

import yaml
from claims.exceptions import ReproError
from claims.manifest import load
from claims.models import Basis, Digest, Evidence, Manifest
from claims.open_items import (
    AGENT_RECORD,
    ATTEMPT_LIMIT,
    FILLS,
    Attempt,
    Need,
    OpenItem,
    OpenItems,
    append_attempt,
    read_attempts,
)
from claims.open_items import read as read_items
from claims.sources import is_lfs_pointer
from claims.verify import verify
from provenance_core import atomic_write, chain, try_run
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

#: How many candidates one packet lists. The count of the rest is given.
MAX_CANDIDATES = 10

#: How much of the sentence an item quotes one packet carries.
MAX_SENTENCE = 300

#: How much of a stored value one packet carries: a cell, never a file.
MAX_STORED = 80

#: What marks a directory as a project, for `repro mcp`'s `set_project` and its search above the
#: working directory: a manifest or a reader's draft, a results ledger, a record of frozen plans,
#: a folder of pinned quotations, or the plan itself. The repro mod for Claude Code reads the
#: same signs (`MARKERS` in `mod/hooks/register.ts`) but for `paper/`, which marks too many
#: folders to let a write tool settle on one.
PROJECT_MARKERS = ("repro.yaml", "repro.draft.yaml", ".results", ".prereg", "claims", "PREREG.md")

#: The longest name an agent may give: a claim, an item, an artifact or a quotation's id.
MAX_NAME = 200

#: The longest value an agent may give as `reported`.
MAX_VALUE = 100

#: The longest passage or other text field an agent may give.
MAX_TEXT = 2000

#: The longest assertion, written as JSON.
MAX_ASSERTION = 8000

#: Reads one assertion as a manifest does.
_EVIDENCE: TypeAdapter[Any] = TypeAdapter(Evidence)

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
    attempt: int
    """Which attempt at this item it was, as the record of attempts counts them."""
    replaced: bool = False
    """Whether it took the place of this agent's earlier proposal for the item, which had not
    matched."""
    warning: str = ""
    """Set past `ATTEMPT_LIMIT` attempts at one item."""


def _same(proposed: dict[str, Any], held: Any) -> bool:
    """Whether a logged proposal is the assertion the draft holds, compared as the manifest
    reads both."""
    try:
        return _EVIDENCE.validate_python(proposed) == held
    except ValidationError:
        return False


def _retry_index(
    item: OpenItem, claim: Any, decisions: tuple, attempts: tuple[Attempt, ...]
) -> int | None:
    """Where the one assertion filling `item` sits, where it may be replaced: it is inferred
    and nobody reviewed it, it did not match, and it is the last proposal recorded for the
    item. None for anything else, a declared or matched assertion above all."""
    filling = [i for i, e in enumerate(claim.evidence) if e.kind in FILLS[item.need]]
    if len(filling) != 1:
        return None
    index = filling[0]
    held = claim.evidence[index]
    if held.counted is not Basis.INFERRED or decisions[index].said == "matched":
        return None
    mine = [attempt for attempt in attempts if attempt.item == item.id]
    return index if mine and _same(mine[-1].assertion, held) else None


def _assertion_span(text: str, claim_id: str, index: int) -> tuple[int, int]:
    """Where in the draft's text the claim's `index`th assertion is written: the span of one
    flow mapping, which is how `propose` writes one."""
    root = yaml.compose(text)
    claims = next(v for k, v in root.value if getattr(k, "value", None) == "claims")
    entry = next(
        c for c in claims.value if any(k.value == "id" and v.value == claim_id for k, v in c.value)
    )
    evidence = next(v for k, v in entry.value if k.value == "evidence")
    node = evidence.value[index]
    if not (isinstance(node, yaml.MappingNode) and node.flow_style):
        raise Refused("draft_layout", f"the assertion to replace in {claim_id!r} was rewritten")
    return node.start_mark.index, node.end_mark.index


def _without(dump: dict, claim_id: str, index: int) -> dict:
    for entry in dump["claims"]:
        if entry["id"] == claim_id:
            entry["evidence"] = entry["evidence"][:index] + entry["evidence"][index + 1 :]
    return dump


def capped(field: str, value: str | None, cap: int) -> None:
    """Refuse a value longer than `cap` characters: a field an agent fills is a name, a
    number or a passage, never a file."""
    if value is not None and len(value) > cap:
        raise Refused("too_long", f"{field} is {len(value):,} characters; the cap is {cap:,}")


def _capped_assertion(assertion: dict[str, Any]) -> None:
    capped("the assertion", json.dumps(assertion, default=str), MAX_ASSERTION)
    capped("reported", _text(assertion.get("reported")), MAX_VALUE)
    for field in ("name", "artifact"):
        capped(field, _text(assertion.get(field)), MAX_NAME)
    for field, value in _strings(assertion, "assertion"):
        capped(field, value, MAX_TEXT)


def _strings(value: Any, where: str) -> list[tuple[str, str]]:
    """Every string anywhere in `value`, with where it sits."""
    if isinstance(value, str):
        return [(where, value)]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in _strings(v, f"{where}.{k}")]
    if isinstance(value, list):
        return [s for i, v in enumerate(value) for s in _strings(v, f"{where}[{i}]")]
    return []


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _last_leaf(node: yaml.Node) -> yaml.Node:
    """The last scalar or flow collection under a node, whose end mark is where its text ends.
    A block collection's own end mark is the position of the token after it, which can be
    lines further on."""
    while isinstance(node, yaml.CollectionNode) and not node.flow_style and node.value:
        last = node.value[-1]
        node = last[1] if isinstance(last, tuple) else last
    return node


def _line_after(text: str, node: yaml.Node) -> int:
    """Where the line after the end of `node` starts: after any comment that ends its line."""
    end = _last_leaf(node).end_mark.index
    if end > 0 and text[end - 1] == "\n":
        return end
    newline = text.find("\n", end)
    return len(text) if newline < 0 else newline + 1


def _append_item(text: str, mapping: yaml.Node, key: str, line: str, what: str) -> tuple[int, str]:
    """Where to insert `line`, one line of flow YAML, as the last item of the list `mapping`
    holds under `key`, and the text to insert there, so every other byte stays as it is. A
    list that is not there yet is started under the mapping's last key."""
    if not isinstance(mapping, yaml.MappingNode) or mapping.flow_style or not mapping.value:
        raise Refused("draft_layout", f"{what} is not a block mapping in the draft")
    listed = next((v for k, v in mapping.value if k.value == key), None)
    if listed is None:
        indent = " " * mapping.value[0][0].start_mark.column
        at = _line_after(text, mapping)
        block = f"{indent}{key}:\n{indent}- {line}\n"
    elif isinstance(listed, yaml.SequenceNode) and listed.flow_style:
        return listed.end_mark.index - 1, (f", {line}" if listed.value else line)
    elif isinstance(listed, yaml.SequenceNode) and listed.value:
        first = listed.value[0].start_mark
        start = text.rfind("\n", 0, first.index) + 1
        indent = " " * text[start : first.index].rfind("-")
        at = _line_after(text, listed)
        block = f"{indent}- {line}\n"
    else:
        raise Refused("draft_layout", f"the {key} of {what} is not a list")
    if at == len(text) and text and not text.endswith("\n"):
        block = "\n" + block
    return at, block


def _insertion(text: str, claim_id: str, line: str) -> tuple[int, str]:
    """Where in the draft's text the assertion `line` goes, as the claim's last."""
    root = yaml.compose(text)
    claims = next(
        (v for k, v in getattr(root, "value", ()) if getattr(k, "value", None) == "claims"), None
    )
    entry = next(
        (
            c
            for c in getattr(claims, "value", ())
            if isinstance(c, yaml.MappingNode)
            and any(k.value == "id" and v.value == claim_id for k, v in c.value)
        ),
        None,
    )
    if entry is None:
        raise Refused("draft_layout", f"the claim {claim_id!r} is not a block mapping in the draft")
    return _append_item(text, entry, "evidence", line, f"the claim {claim_id!r}")


def propose(
    root: pathlib.Path,
    open_items: str,
    claim_id: str,
    assertion: dict[str, Any],
    session: Session,
    item_id: str | None = None,
    basis: str | None = None,
) -> Proposal:
    """Append `assertion`, marked `basis: inferred`, to the claim in the draft an open-items
    file names, where it fills one of that claim's open items; then check it.

    Refused, with nothing written: a basis other than inferred, or `reviewed`; a claim the
    file lists no item for; a draft outside the root; an assertion of a kind that fills none
    of the claim's open items, or only items already filled; a `reported` that is missing or
    other than the value the source states; an artifact the draft does not declare; a claim
    the draft does not hold; and a field over its cap. The write appends and edits nothing: no assertion
    the draft holds can be changed through it, and an item a declared assertion fills is
    filled. The assertion is inserted into the draft's text as one line of flow YAML, so its
    comments and the layout of everything else are kept byte for byte.
    """
    for field, value in (("claim", claim_id), ("item", item_id)):
        capped(field, value, MAX_NAME)
    _capped_assertion(assertion)
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
    if claim_id not in {c.id for c in before.claims}:
        raise Refused(
            "claim_not_in_draft",
            f"{path.name} lists items for {claim_id!r}, and {draft.name} holds no such claim",
        )
    kind = assertion.get("kind")
    claim = next(c for c in before.claims if c.id == claim_id)
    attempts = read_attempts(path).attempts
    position = [c.id for c in before.claims].index(claim_id)
    decisions = verify(before).claims[position].decisions if claim.evidence else ()
    fillable = [
        (i, None if not _fills(i, before) else _retry_index(i, claim, decisions, attempts))
        for i in open_for_claim
        if kind in FILLS[i.need]
    ]
    fillable = [(i, at) for i, at in fillable if not _fills(i, before) or at is not None]
    if not fillable:
        raise Refused(
            "fills_no_open_item",
            f"a {kind!r} assertion fills no open item of {claim_id!r}: "
            + ", ".join(
                f"{i.id} needs {i.need.value}{' and is filled' if _fills(i, before) else ''}"
                for i in open_for_claim
            )
            + "; only an inferred proposal of yours that did not match is replaced",
        )
    item, replacing = fillable[0]

    if item.need is Need.VALUE and kind != "correspondence" and not assertion.get("reported"):
        raise Refused("missing", "the assertion has no `reported`: the value the source states")
    allowed = stated_values(item)
    if item.need is Need.VALUE and allowed and str(assertion.get("reported")) not in allowed:
        raise Refused(
            "reported_changed",
            f"reported {assertion.get('reported')!r} is not the value the source states "
            f"({', '.join(sorted(allowed))}); `reported` is never changed to make a check pass",
        )

    text = draft.read_text(encoding="utf-8")
    written = {**assertion, "basis": INFERRED}
    if replacing is None:
        index = len(claim.evidence)
        at, block = _insertion(text, claim_id, json.dumps(written))
        new_text = text[:at] + block + text[at:]
    else:
        index = replacing
        start, end = _assertion_span(text, claim_id, index)
        new_text = text[:start] + json.dumps(written) + text[end:]
    try:
        after = Manifest.model_validate({**yaml.safe_load(new_text), "path": draft})
    except (ValidationError, yaml.YAMLError) as e:
        detail = e.errors()[0]["msg"] if isinstance(e, ValidationError) else str(e)
        raise Refused("invalid_assertion", detail) from e

    # The draft reads as it did, but for the one assertion added or replaced.
    was = _without(before.model_dump(mode="json"), claim_id, index)
    if was != _without(after.model_dump(mode="json"), claim_id, index):
        raise Refused("draft_layout", f"inserting into {draft.name} would change what it declares")
    added = next(c for c in after.claims if c.id == claim_id).evidence[index]
    if undeclared := set(added.artifacts) - {a.id for a in after.artifacts}:
        raise Refused(
            "artifact_undeclared",
            f"the assertion reads {', '.join(sorted(undeclared))}, which {draft.name} does not "
            "declare",
        )

    atomic_write(draft, new_text)
    report = verify(load(draft))
    decision = report.claims[position].decisions[index]
    attempt = sum(1 for a in attempts if a.item == item.id) + 1
    append_attempt(
        root,
        path,
        {
            "session": session.id,
            "item": item.id,
            "claim": claim_id,
            "attempt": attempt,
            "assertion": written,
            "outcome": decision.said,
        },
    )
    warning = (
        f"item {item.id} {decision.said} on attempt {attempt}: check the binding is the "
        "claim's own value, not a search"
        if attempt > ATTEMPT_LIMIT
        else ""
    )
    return Proposal(
        draft=draft.relative_to(root).as_posix(),
        claim=claim_id,
        item=item.id,
        assertion=written,
        outcome=decision.said,
        said=f"{decision.said}, inferred: not verified",
        detail=decision.detail,
        extracted=decision.extracted,
        attempt=attempt,
        replaced=replacing is not None,
        warning=warning,
    )


# ----------------------------------------------------------------------------- the session


@dataclasses.dataclass
class Session:
    """One run of the server: when it started, and the commit each project stood at when the
    server first saw it. Neither moves: a commit made, or a file changed, after that is
    something an agent could have done, and `add_artifact` takes none of it."""

    id: str = dataclasses.field(default_factory=lambda: uuid.uuid4().hex)
    started: datetime.datetime = dataclasses.field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC)
    )
    commits: dict[pathlib.Path, str | None] = dataclasses.field(default_factory=dict)

    def commit(self, root: pathlib.Path) -> str | None:
        """The commit `root` stood at when this session first saw it, or None outside git."""
        if root not in self.commits:
            head = try_run("rev-parse", "--verify", "HEAD", cwd=root)
            self.commits[root] = head.strip() if head else None
        return self.commits[root]

    def log(self, root: pathlib.Path, event: dict[str, Any]) -> None:
        """Append one event of this session to the agent record of the project at `root`."""
        record = root / AGENT_RECORD
        record.parent.mkdir(exist_ok=True)
        chain.append_event(record, {**event, "session": self.id})


# ---------------------------------------------------------------------------- add_artifact

#: The largest file `add_artifact` pins.
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024

#: Why a file the session could have made is refused.
NOT_YOURS = "committed or changed during this session; a human must add it"
UNRECORDED = "commit it or record it with results run first, then start a new session"


class Added(BaseModel):
    """What `add_artifact` wrote into the draft."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    draft: str
    artifact: dict[str, Any]
    by: str
    """What vouches for the bytes: the commit the session started at, or a run in the ledger."""


def _blob(root: pathlib.Path, revision: str, relative: str) -> str | None:
    found = try_run("rev-parse", "--verify", "--quiet", f"{revision}:./{relative}", cwd=root)
    return found.strip() if found else None


def _recorded_run(root: pathlib.Path, relative: str, digest: str, before: datetime.datetime):
    """The run in the project's results ledger that recorded these bytes at this path before
    `before`, or None. The ledger is read, never written."""
    ledger = root / ".results" / "ledger.jsonl"
    if not ledger.is_file():
        return None
    try:
        events = chain.read_ledger(ledger)
    except chain.ChainError:
        return None
    for event in events:
        if event.get("event") != "run":
            continue
        try:
            when = datetime.datetime.fromisoformat(str(event.get("timestamp")))
        except ValueError:
            continue
        if when.tzinfo is None or when >= before:
            continue
        for output in event.get("outputs", ()):
            if output.get("path") == relative and output.get("sha256") == digest:
                return event.get("run_id")
    return None


def _vouched(root: pathlib.Path, file: pathlib.Path, digest: str, session: Session) -> str:
    """What says these bytes were not made in this session: the commit the session started
    at holds them, or the ledger recorded them as a run's output before it started. Refused
    otherwise."""
    relative = file.relative_to(root).as_posix()
    commit = session.commit(root)
    if commit is not None:
        then = _blob(root, commit, relative)
        if then is not None:
            now = try_run("hash-object", "--", relative, cwd=root)
            if now is not None and now.strip() == then:
                return f"commit {commit[:12]}, where this session started"
    if (run := _recorded_run(root, relative, digest, session.started)) is not None:
        return f"run {run} in the results ledger, recorded before this session started"
    if commit is not None and (then := _blob(root, commit, relative)) is not None:
        raise Refused("not_vouched", f"{relative} differs from commit {commit[:12]}: {NOT_YOURS}")
    if _blob(root, "HEAD", relative) is not None:
        raise Refused("not_vouched", f"{relative} was {NOT_YOURS}")
    raise Refused(
        "not_vouched",
        f"{relative} is in no commit this session started at and no run the ledger recorded: "
        f"{UNRECORDED}",
    )


def add_artifact(
    root: pathlib.Path,
    open_items: str,
    path: str,
    session: Session,
    media_type: str | None = None,
    artifact_id: str | None = None,
) -> Added:
    """Declare a file in the draft an open-items file names, pinned by its sha256 and marked
    `basis: inferred`, so every assertion that reads it is counted as inferred until an author
    accepts it. Inserted as one line, as `propose` inserts an assertion.

    Refused: a path outside the root; a directory, or nothing; a Git LFS pointer; a file over
    `MAX_ARTIFACT_BYTES`; a file or an id the draft already declares; and a file whose bytes
    neither the commit the session started at holds nor a run the results ledger recorded
    before the session started."""
    capped("path", path, MAX_TEXT)
    capped("id", artifact_id, MAX_NAME)
    capped("media_type", media_type, MAX_NAME)
    items_path = inside(root, open_items)
    items = read_items(items_path)
    draft = _draft(root, items_path, items)
    file = inside(root, path)
    if not file.exists():
        raise Refused("not_a_file", f"nothing is at {path}")
    if not file.is_file():
        raise Refused("not_a_file", f"{path} is a directory, not a file")
    if file.stat().st_size > MAX_ARTIFACT_BYTES:
        raise Refused(
            "too_large",
            f"{path} is {file.stat().st_size:,} bytes; the cap is {MAX_ARTIFACT_BYTES:,}",
        )
    if is_lfs_pointer(file):
        raise Refused("lfs_pointer", f"{path} is a Git LFS pointer: its content is not here")

    before = load_inside(root, draft)
    name = artifact_id or file.relative_to(root).as_posix()
    for declared in before.artifacts:
        if declared.id == name or before.resolve(declared).resolve() == file:
            raise Refused(
                "already_declared", f"{draft.name} declares {path} already, as {declared.id!r}"
            )
    digest = Digest.of_file(file).value
    by = _vouched(root, file, digest, session)

    artifact = {
        "id": name,
        "path": pathlib.Path(os.path.relpath(file, draft.parent)).as_posix(),
        "digest": {"algorithm": "sha256", "value": digest},
        "media_type": media_type
        or mimetypes.guess_type(file.name)[0]
        or "application/octet-stream",
        "basis": INFERRED,
    }
    text = draft.read_text(encoding="utf-8")
    at, block = _append_item(
        text, yaml.compose(text), "artifacts", json.dumps(artifact), draft.name
    )
    new_text = text[:at] + block + text[at:]
    try:
        after = Manifest.model_validate({**yaml.safe_load(new_text), "path": draft})
    except (ValidationError, yaml.YAMLError) as e:
        detail = e.errors()[0]["msg"] if isinstance(e, ValidationError) else str(e)
        raise Refused("invalid_artifact", detail) from e
    was, now = before.model_dump(mode="json"), after.model_dump(mode="json")
    now["artifacts"] = now["artifacts"][:-1]
    if was != now:
        raise Refused("draft_layout", f"inserting into {draft.name} would change what it declares")
    atomic_write(draft, new_text)
    session.log(
        root,
        {
            "event": "add_artifact",
            "draft": draft.relative_to(root).as_posix(),
            "artifact": name,
            "sha256": digest,
            "by": by,
        },
    )
    return Added(draft=draft.relative_to(root).as_posix(), artifact=artifact, by=by)
