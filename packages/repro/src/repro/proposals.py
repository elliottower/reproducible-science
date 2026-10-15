"""What `repro mcp` does to a project, without the protocol.

    project_of     the project a path belongs to: the nearest folder above it with a marker
    inside         a path inside one project, refusing one that leaves it
    packet         one open item, compact: the claim, the printed value, the sentence and its
                   line, each candidate's file, address, labels and stored value
    propose        insert one inferred assertion that fills an open item, then check it
    add_artifact   insert one inferred artifact, pinned by its sha256
    mark_reviewed  record that a person accepted inferred assertions or artifacts

Each write inserts or replaces one line of flow YAML in the draft and changes no other byte.
Every refusal is a `Refused`, which names the rule and says why, and writes nothing.
"""

from __future__ import annotations

import datetime
import json
import mimetypes
import os
import pathlib
from typing import Any

import yaml
from claims.core.artifacts import ArtifactRef, review_digest
from claims.exceptions import ReproError
from claims.manifest import load
from claims.models import Basis, Digest, Evidence, Manifest
from claims.open_items import (
    ATTEMPT_LIMIT,
    DRAFT_NAME,
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
from provenance_core import atomic_write_bytes, try_run
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

#: What marks a directory as a project: a manifest or a reader's draft, a results ledger, a
#: record of frozen plans, a folder of pinned quotations, or the plan itself. The repro mod for
#: Claude Code reads the same signs (`MARKERS` in `mod/hooks/register.ts`) but for `paper/`,
#: which marks too many folders to let a write tool settle on one.
PROJECT_MARKERS = ("repro.yaml", "repro.draft.yaml", ".results", ".prereg", "claims", "PREREG.md")

#: How many candidates one packet lists, and how much of a sentence and of a stored value.
MAX_CANDIDATES = 10
MAX_SENTENCE = 300
MAX_STORED = 80

#: The longest name, `reported` value, text field and assertion an agent may give.
MAX_NAME = 200
MAX_VALUE = 100
MAX_TEXT = 2000
MAX_ASSERTION = 8000

#: The largest file `add_artifact` pins.
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024

#: What an agent writes, and the only basis this module writes.
INFERRED = Basis.INFERRED.value

_EVIDENCE: TypeAdapter[Any] = TypeAdapter(Evidence)


class Refused(ReproError):
    """A tool call the server will not carry out. Nothing was written."""

    def __init__(self, rule: str, detail: str) -> None:
        self.rule = rule
        self.detail = detail
        super().__init__(f"refused ({rule}): {detail}")


# ------------------------------------------------------------------------------------ paths


def is_project(directory: pathlib.Path, without: str = "") -> bool:
    markers = (name for name in PROJECT_MARKERS if name != without)
    return directory.is_dir() and any((directory / name).exists() for name in markers)


def _nearest(path: pathlib.Path) -> pathlib.Path | None:
    """The nearest folder at or above `path` as written that holds a marker. A symlinked
    folder is never one: a link belongs to the folder it sits in."""
    folders = [d for d in (path, *path.parents) if not d.is_symlink()]
    # A reader's draft folder inside a project is part of that project; a draft folder is a
    # project of its own only where nothing encloses it.
    held = next((d for d in folders if is_project(d, without=DRAFT_NAME)), None)
    return held or next((d for d in folders if is_project(d)), None)


def project_of(path: pathlib.Path) -> pathlib.Path:
    """The project `path` belongs to: the nearest folder at or above where it is written that
    holds a marker. A symlink belongs where it sits, never where it points, and a path whose
    target lies outside that project is refused, as is a path under no project."""
    written = pathlib.Path(os.path.abspath(path))
    project = _nearest(written)
    if project is None:
        raise Refused(
            "no_project",
            f"{path} is under no project: no {', '.join(PROJECT_MARKERS)} at or above it",
        )
    project = project.resolve()
    if not written.resolve().is_relative_to(project):
        raise Refused("outside_root", f"{path} resolves outside its project {project}")
    return project


def inside(root: pathlib.Path, given: str | pathlib.Path) -> pathlib.Path:
    """`given`, resolved against `root` where relative, with every symlink followed. Refused
    where the result is not `root` or below it."""
    candidate = pathlib.Path(given).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise Refused("outside_root", f"{given} resolves to {resolved}, outside {root}")
    return resolved


def load_inside(root: pathlib.Path, given: str | pathlib.Path) -> Manifest:
    """The manifest at `given`, refused where it or an artifact it declares is outside `root`."""
    manifest = load(inside(root, given))
    for artifact in manifest.artifacts:
        try:
            inside(root, manifest.resolve(artifact))
        except Refused as e:
            raise Refused("outside_root", f"artifact {artifact.id!r}: {e.detail}") from e
    return manifest


def _draft(root: pathlib.Path, path: pathlib.Path, items: OpenItems) -> pathlib.Path:
    return inside(root, path.parent / items.manifest)


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
    attempts: int
    total: int
    remaining: int
    """Items in the file not yet filled, this one included where it is open."""
    next_item: str | None


def stated_values(item: OpenItem) -> frozenset[str]:
    """Every value the source states for the item's claim, as written: what each candidate
    reports, the value a report prints, the values a task gives. Empty where none is stated."""
    found = {str(c["reported"]) for c in item.candidates if c.get("reported") is not None}
    if item.context.get("value") is not None:
        found.add(str(item.context["value"]))
    found.update(str(value) for value in item.context.get("values", ()) or ())
    return frozenset(found)


def _address(locator: dict[str, Any]) -> tuple[str, tuple[str, ...]]:
    """The address as a line, and the labels it carries."""
    kind = locator.get("kind")
    if kind == "tree":
        pointer = str(locator.get("pointer", ""))
        keys = [p.replace("~1", "/").replace("~0", "~") for p in pointer.split("/") if p]
        return pointer or "/", tuple(keys)
    column = str(locator.get("column", ""))
    if kind == "table_position":
        return f"column {column}, row {locator.get('row')}", (column, f"row {locator.get('row')}")
    filters = tuple(f"{key}={value}" for key, value in (locator.get("where") or {}).items())
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


def _sentence(context: dict[str, Any]) -> tuple[str, int | None]:
    text = next((str(context[k]) for k in ("text", "question", "comment") if context.get(k)), "")
    text = " ".join(text.split())
    line = context.get("line")
    return (text if len(text) <= MAX_SENTENCE else f"{text[:MAX_SENTENCE]}..."), (
        line if isinstance(line, int) else None
    )


def packet(root: pathlib.Path, open_items: str, item_id: str | None, after: str | None) -> Packet:
    """One item of the open-items file: `item_id` where named, otherwise the first open item
    after `after` in the file's order. Refused where the named item is not in the file or no
    open item is left."""
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
    tried = sum(1 for a in read_attempts(path).attempts if a.item == chosen.id)
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
        attempts=tried,
        total=len(ids),
        remaining=sum(not done for done in filled.values()),
        next_item=following,
    )


# ------------------------------------------------------------------------- the draft's text


def capped(field: str, value: str | None, cap: int) -> None:
    """Refuse a value longer than `cap` characters: a field an agent fills is a name, a
    number or a passage, never a file."""
    if value is not None and len(value) > cap:
        raise Refused("too_long", f"{field} is {len(value):,} characters; the cap is {cap:,}")


def _strings(value: Any, where: str) -> list[tuple[str, str]]:
    if isinstance(value, str):
        return [(where, value)]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in _strings(v, f"{where}.{k}")]
    if isinstance(value, list):
        return [s for i, v in enumerate(value) for s in _strings(v, f"{where}[{i}]")]
    return []


def _capped_assertion(assertion: dict[str, Any]) -> None:
    capped("the assertion", json.dumps(assertion, default=str), MAX_ASSERTION)
    for field, cap in (("reported", MAX_VALUE), ("name", MAX_NAME), ("artifact", MAX_NAME)):
        value = assertion.get(field)
        capped(field, value if isinstance(value, str) else None, cap)
    for field, value in _strings(assertion, "assertion"):
        capped(field, value, MAX_TEXT)


def _read(draft: pathlib.Path) -> str:
    """The draft's text with its own line endings: no newline is translated."""
    return draft.read_bytes().decode("utf-8")


def _line_after(text: str, node: yaml.Node) -> int:
    """Where the line after the end of `node` starts: after any comment that ends its line. A
    block collection's end mark is the token after it, so its last scalar's is taken."""
    while isinstance(node, yaml.CollectionNode) and not node.flow_style and node.value:
        last = node.value[-1]
        node = last[1] if isinstance(last, tuple) else last
    end = node.end_mark.index
    if end > 0 and text[end - 1] == "\n":
        return end
    newline = text.find("\n", end)
    return len(text) if newline < 0 else newline + 1


def _append_item(text: str, mapping: Any, key: str, line: str, what: str) -> tuple[int, str]:
    """Where to insert `line`, one line of flow YAML, as the last item of the list `mapping`
    holds under `key`, and the text to insert there. A list not there yet is started."""
    nl = "\r\n" if "\r\n" in text else "\n"
    if not isinstance(mapping, yaml.MappingNode) or mapping.flow_style or not mapping.value:
        raise Refused("draft_layout", f"{what} is not a block mapping in the draft")
    listed = next((v for k, v in mapping.value if k.value == key), None)
    if listed is None:
        indent = " " * mapping.value[0][0].start_mark.column
        at, block = _line_after(text, mapping), f"{indent}{key}:{nl}{indent}- {line}{nl}"
    elif isinstance(listed, yaml.SequenceNode) and listed.flow_style:
        return listed.end_mark.index - 1, (f", {line}" if listed.value else line)
    elif isinstance(listed, yaml.SequenceNode) and listed.value:
        first = listed.value[0].start_mark.index
        start = text.rfind("\n", 0, first) + 1
        at, block = _line_after(text, listed), f"{' ' * text[start:first].rfind('-')}- {line}{nl}"
    else:
        raise Refused("draft_layout", f"the {key} of {what} is not a list")
    if at == len(text) and text and not text.endswith("\n"):
        block = nl + block
    return at, block


def _claim_node(text: str, claim_id: str) -> Any:
    root = yaml.compose(text)
    claims = next(
        (v for k, v in getattr(root, "value", ()) if getattr(k, "value", None) == "claims"), None
    )
    return next(
        (
            c
            for c in getattr(claims, "value", ())
            if isinstance(c, yaml.MappingNode)
            and any(k.value == "id" and v.value == claim_id for k, v in c.value)
        ),
        None,
    )


def _flow_span(text: str, owner: Any, key: str, index: int, what: str) -> tuple[int, int]:
    """The span of the `index`th item of the list `owner` holds under `key`, where it is one
    flow mapping, as this module writes one. Refused for anything written otherwise."""
    listed = next((v for k, v in getattr(owner, "value", ()) if k.value == key), None)
    node = listed.value[index] if listed is not None else None
    if not (isinstance(node, yaml.MappingNode) and node.flow_style):
        raise Refused("draft_layout", f"{what} is not one line of flow YAML; edit it by hand")
    return node.start_mark.index, node.end_mark.index


def _written(
    draft: pathlib.Path, before: Manifest, new_text: str, key: str, claim_id: str | None, index: int
) -> Manifest:
    """The draft as `new_text` reads, refused unless it reads as `before` but for the one item
    at `index` of the claim's evidence, or of the artifacts."""
    try:
        after = Manifest.model_validate({**yaml.safe_load(new_text), "path": draft})
    except (ValidationError, yaml.YAMLError) as e:
        detail = e.errors()[0]["msg"] if isinstance(e, ValidationError) else str(e)
        raise Refused("invalid", detail) from e
    was, now = before.model_dump(mode="json"), after.model_dump(mode="json")
    for dump in (was, now):
        listed = next((c for c in dump["claims"] if c["id"] == claim_id), dump)[key]
        del listed[index : index + 1]
    if was != now:
        raise Refused("draft_layout", f"writing {draft.name} would change what else it declares")
    return after


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
    replaced: bool = False
    """Whether it took the place of this agent's last proposal for the item, which had not
    matched."""
    warning: str = ""
    """Set past `ATTEMPT_LIMIT` attempts at one item."""


def _retry_index(
    item: OpenItem, claim: Any, decisions: tuple, attempts: tuple[Attempt, ...]
) -> int | None:
    """Where the one assertion filling `item` sits, where it may be replaced: it is inferred,
    unreviewed and did not match, and it is the last proposal recorded for the item."""
    filling = [i for i, e in enumerate(claim.evidence) if e.kind in FILLS[item.need]]
    if len(filling) != 1:
        return None
    index = filling[0]
    held = claim.evidence[index]
    if held.counted is not Basis.INFERRED or decisions[index].said == "matched":
        return None
    mine = [attempt for attempt in attempts if attempt.item == item.id]
    try:
        return index if mine and _EVIDENCE.validate_python(mine[-1].assertion) == held else None
    except ValidationError:
        return None


def propose(
    root: pathlib.Path,
    open_items: str,
    claim_id: str,
    assertion: dict[str, Any],
    item_id: str | None = None,
    basis: str | None = None,
) -> Proposal:
    """Insert `assertion`, marked `basis: inferred`, into the claim in the draft an open-items
    file names, where it fills one of that claim's open items; then check it, and record the
    attempt. An item filled only by this agent's last proposal, which did not match, takes the
    new one in its place. A matched, declared or reviewed assertion is never replaced.

    Refused, with nothing written: a basis other than inferred, or `reviewed`; a claim the
    file lists no item for, or the draft does not hold; a draft outside the root; a kind that
    fills no open item; a `reported` that is missing or other than the value the source
    states; an artifact the draft does not declare; and a field over its cap."""
    for field, value in (("claim", claim_id), ("item", item_id)):
        capped(field, value, MAX_NAME)
    _capped_assertion(assertion)
    stated = assertion.get("basis")
    if (basis is not None and basis != INFERRED) or (stated is not None and stated != INFERRED):
        raise Refused("basis", f"this server writes basis: {INFERRED} and nothing else")
    if "reviewed" in assertion:
        raise Refused("reviewed", "a review is recorded with mark_reviewed, after a person accepts")

    path = inside(root, open_items)
    items = read_items(path)
    draft = _draft(root, path, items)
    listed = [i for i in items.items if i.claim == claim_id and item_id in (None, i.id)]
    if not listed:
        raise Refused("claim_not_in_open_items", f"{path.name} lists no such item for {claim_id!r}")
    before = load_inside(root, draft)
    claim = next((c for c in before.claims if c.id == claim_id), None)
    if claim is None:
        raise Refused("claim_not_in_draft", f"{draft.name} holds no claim {claim_id!r}")

    kind = assertion.get("kind")
    attempts = read_attempts(path).attempts
    position = [c.id for c in before.claims].index(claim_id)
    decisions = verify(before).claims[position].decisions if claim.evidence else ()
    fillable = [
        (i, None if not _fills(i, before) else _retry_index(i, claim, decisions, attempts))
        for i in listed
        if kind in FILLS[i.need]
    ]
    fillable = [(i, at) for i, at in fillable if not _fills(i, before) or at is not None]
    if not fillable:
        raise Refused(
            "fills_no_open_item",
            f"a {kind!r} assertion fills no open item of {claim_id!r}; only an inferred "
            "proposal of yours that did not match is replaced",
        )
    item, replacing = fillable[0]
    if item.need is Need.VALUE and kind != "correspondence" and not assertion.get("reported"):
        raise Refused("missing", "the assertion has no `reported`: the value the source states")
    allowed = stated_values(item)
    if item.need is Need.VALUE and allowed and str(assertion.get("reported")) not in allowed:
        raise Refused(
            "reported_changed",
            f"reported {assertion.get('reported')!r} is not the value the source states "
            f"({', '.join(sorted(allowed))})",
        )

    text = _read(draft)
    written = {**assertion, "basis": INFERRED}
    if replacing is None:
        index = len(claim.evidence)
        at, block = _insertion(text, claim_id, json.dumps(written))
        new_text = text[:at] + block + text[at:]
    else:
        index = replacing
        node = _claim_node(text, claim_id)
        start, end = _flow_span(text, node, "evidence", index, "the proposal to replace")
        new_text = text[:start] + json.dumps(written) + text[end:]
    after = _written(draft, before, new_text, "evidence", claim_id, index)
    added = after.claims[position].evidence[index]
    if undeclared := set(added.artifacts) - {a.id for a in after.artifacts}:
        raise Refused("artifact_undeclared", f"{draft.name} declares no {', '.join(undeclared)}")

    atomic_write_bytes(draft, new_text.encode("utf-8"))
    decision = verify(load(draft)).claims[position].decisions[index]
    attempt = sum(1 for a in attempts if a.item == item.id) + 1
    append_attempt(
        path,
        {
            "item": item.id,
            "claim": claim_id,
            "attempt": attempt,
            "assertion": written,
            "outcome": decision.said,
        },
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
        warning=(
            f"item {item.id} {decision.said} on attempt {attempt}: check the binding is the "
            "claim's own value, not a search"
            if attempt > ATTEMPT_LIMIT
            else ""
        ),
    )


def _insertion(text: str, claim_id: str, line: str) -> tuple[int, str]:
    node = _claim_node(text, claim_id)
    if node is None:
        raise Refused("draft_layout", f"the claim {claim_id!r} is not a block mapping in the draft")
    return _append_item(text, node, "evidence", line, f"the claim {claim_id!r}")


# ----------------------------------------------------------------------------- add_artifact


class Added(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    draft: str
    artifact: dict[str, Any]


def add_artifact(
    root: pathlib.Path,
    open_items: str,
    path: str,
    media_type: str | None = None,
    artifact_id: str | None = None,
) -> Added:
    """Declare a file in the draft an open-items file names, pinned by its sha256 and marked
    `basis: inferred`, so every assertion that reads it counts as inferred until a person
    accepts it. Refused: a path outside the project, a directory or nothing, a Git LFS pointer,
    a file over `MAX_ARTIFACT_BYTES`, and a file or id the draft already declares."""
    for field, value in (("path", path), ("id", artifact_id), ("media_type", media_type)):
        capped(field, value, MAX_NAME if field != "path" else MAX_TEXT)
    items_path = inside(root, open_items)
    draft = _draft(root, items_path, read_items(items_path))
    file = inside(root, path)
    if not file.is_file():
        raise Refused("not_a_file", f"{path} is {'a directory' if file.is_dir() else 'not there'}")
    if file.stat().st_size > MAX_ARTIFACT_BYTES:
        raise Refused("too_large", f"{path} is over {MAX_ARTIFACT_BYTES:,} bytes")
    if is_lfs_pointer(file):
        raise Refused("lfs_pointer", f"{path} is a Git LFS pointer: its content is not here")
    before = load_inside(root, draft)
    name = artifact_id or file.relative_to(root).as_posix()
    for declared in before.artifacts:
        if declared.id == name or before.resolve(declared).resolve() == file:
            raise Refused("already_declared", f"{draft.name} declares {path} as {declared.id!r}")

    artifact = {
        "id": name,
        "path": pathlib.Path(os.path.relpath(file, draft.parent)).as_posix(),
        "digest": {"algorithm": "sha256", "value": Digest.of_file(file).value},
        "media_type": media_type
        or mimetypes.guess_type(file.name)[0]
        or "application/octet-stream",
        "basis": INFERRED,
    }
    text = _read(draft)
    at, block = _append_item(text, yaml.compose(text), "artifacts", json.dumps(artifact), "it")
    new_text = text[:at] + block + text[at:]
    _written(draft, before, new_text, "artifacts", None, len(before.artifacts))
    atomic_write_bytes(draft, new_text.encode("utf-8"))
    return Added(draft=draft.relative_to(root).as_posix(), artifact=artifact)


# ---------------------------------------------------------------------------- mark_reviewed


class Reviewed(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    draft: str
    reviewed: dict[str, Any]
    """What was written beside each: who, when, how and the digest the review is of."""
    assertions: tuple[str, ...]
    """Each item whose assertion was accepted."""
    artifacts: tuple[str, ...]


def reviewer(root: pathlib.Path) -> str:
    """Who reviews, as git names them in this project: `user.name`, with the email where set."""
    name = (try_run("config", "user.name", cwd=root) or "").strip()
    if not name:
        raise Refused("no_reviewer", "git config user.name is not set, so a review has no name")
    email = (try_run("config", "user.email", cwd=root) or "").strip()
    return f"{name} <{email}>" if email else name


def mark_reviewed(
    root: pathlib.Path,
    open_items: str,
    item_ids: list[str],
    artifact_ids: list[str],
    how: str,
) -> Reviewed:
    """Record that a person accepted the inferred assertion filling each item and each
    inferred artifact: `reviewed` with who, when, how and the digest of what was accepted. A
    review counts only while that digest is the item's, so a changed binding lapses. Refused:
    an item the file does not list, one not filled by an inferred assertion that matched, an
    artifact that is not inferred, and a project where git names no user."""
    for value in (*item_ids, *artifact_ids):
        capped("an id", value, MAX_NAME)
    capped("how", how, MAX_TEXT)
    if not item_ids and not artifact_ids:
        raise Refused("nothing_named", "name the items or artifacts the person approved")
    path = inside(root, open_items)
    items = {i.id: i for i in read_items(path).items}
    draft = _draft(root, path, read_items(path))
    stamp = {
        "who": reviewer(root),
        "when": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        "how": how,
    }
    text, manifest = _read(draft), load_inside(root, draft)
    decisions = verify(manifest)
    edits: list[tuple[int, int, str]] = []
    for item_id in item_ids:
        item = items.get(item_id)
        if item is None:
            raise Refused("item_not_in_open_items", f"{path.name} lists no item {item_id!r}")
        position = [c.id for c in manifest.claims].index(item.claim)
        claim = manifest.claims[position]
        index = next(
            (
                i
                for i, e in enumerate(claim.evidence)
                if e.kind in FILLS[item.need] and e.counted is Basis.INFERRED
            ),
            None,
        )
        if index is None or decisions.claims[position].decisions[index].said != "matched":
            raise Refused("not_matched", f"{item_id} is not filled by an inferred match")
        edits.append(_review_edit(text, _claim_node(text, item.claim), "evidence", index, stamp))
    for artifact_id in artifact_ids:
        index = next((i for i, a in enumerate(manifest.artifacts) if a.id == artifact_id), None)
        if index is None or manifest.artifacts[index].counted is not Basis.INFERRED:
            raise Refused(
                "not_inferred", f"{draft.name} holds no inferred artifact {artifact_id!r}"
            )
        edits.append(_review_edit(text, yaml.compose(text), "artifacts", index, stamp))
    for start, end, line in sorted(edits, reverse=True):
        text = text[:start] + line + text[end:]
    try:
        Manifest.model_validate({**yaml.safe_load(text), "path": draft})
    except (ValidationError, yaml.YAMLError) as e:
        raise Refused("invalid", str(e)) from e
    atomic_write_bytes(draft, text.encode("utf-8"))
    return Reviewed(
        draft=draft.relative_to(root).as_posix(),
        reviewed=stamp,
        assertions=tuple(item_ids),
        artifacts=tuple(artifact_ids),
    )


def _review_edit(
    text: str, owner: Any, key: str, index: int, stamp: dict[str, str]
) -> tuple[int, int, str]:
    """The one line that replaces the `index`th item under `key`: as written, with `reviewed`."""
    start, end = _flow_span(text, owner, key, index, "the item to review")
    held = yaml.safe_load(text[start:end])
    model = (
        _EVIDENCE.validate_python(held) if key == "evidence" else ArtifactRef.model_validate(held)
    )
    digest = review_digest(model)
    return start, end, json.dumps({**held, "reviewed": {**stamp, "digest": digest}})
