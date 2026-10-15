"""Add one `set_aside` entry to the text of `repro.yaml`, or remove one `repro bot` added,
changing no other byte.

The file is never loaded and dumped again: that would drop its comments, reorder its keys and
change its quoting. The entry is written as YAML and put after the last entry of the list,
indented as that list's entries are, or under a new `set_aside:` key at the end of the file.
The result is read back and compared with what was meant, so an edit that would change
anything else is refused rather than written.
"""

from __future__ import annotations

import datetime
import re

import yaml

from repro.exceptions import ReproError
from repro.models import Review, SetAside

KEY = "set_aside"
BOM = "\ufeff"
#: How the reason of an entry `repro bot` wrote begins, so it removes only its own.
PREFIX = "pull request #"


class ManifestShapeError(ReproError):
    """The manifest's text is not a shape an entry can be added to or removed from in place."""

    def __init__(self, detail: str) -> None:
        super().__init__(f"repro.yaml: {detail}; nothing was changed.")


def entry(
    artifact: str,
    text: str,
    pull_request: int,
    said: str,
    reason: str,
    login: str,
    at: datetime.datetime,
) -> SetAside:
    """The entry an answer of 3 or 4 writes: the passage, why, who and when."""
    why = f"{PREFIX}{pull_request}, {said}" + (f": {reason}" if reason else "")
    return SetAside(artifact=artifact, text=text, reason=why, reviewed=Review(who=login, when=at))


def _loader() -> type:
    return getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def _compose(source: str) -> yaml.Node | None:
    try:
        return yaml.compose(source, Loader=_loader())
    except yaml.YAMLError as failed:
        raise ManifestShapeError(
            f"the file does not parse as YAML ({getattr(failed, 'problem', None) or failed})"
        ) from None


def _load(source: str) -> dict:
    try:
        loaded = yaml.load(source, Loader=_loader())
    except yaml.YAMLError as failed:
        raise ManifestShapeError(
            f"the file does not parse as YAML ({getattr(failed, 'problem', None) or failed})"
        ) from None
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ManifestShapeError("the file is not a mapping")
    return loaded


def _top(source: str) -> yaml.MappingNode:
    if _DOCUMENT_END.search(source) or _LATER_DOCUMENT.search(source):
        # Text appended after `...`, or into a second document, is not in the manifest.
        raise ManifestShapeError("the file holds a YAML document marker after its start")
    root = _compose(source)
    if not isinstance(root, yaml.MappingNode):
        raise ManifestShapeError("the file is not a mapping")
    return root


_DOCUMENT_END = re.compile(r"^\.\.\.(?:[ \t#]|$)", re.M)
_LATER_DOCUMENT = re.compile(r"(?<=.)\n---(?:[ \t#]|$)", re.S)


def _key(root: yaml.MappingNode) -> tuple[yaml.Node, yaml.Node] | None:
    return next(((key, value) for key, value in root.value if key.value == KEY), None)


def _leaf(node: yaml.Node) -> yaml.Node:
    """The last scalar of a node, whose end is where the node's text ends. A mapping's or a
    list's own end mark is the next token's start, past any blank lines and comments."""
    while isinstance(node, yaml.MappingNode | yaml.SequenceNode) and node.value:
        last = node.value[-1]
        node = last[1] if isinstance(last, tuple) else last
    return node


def _line_start(source: str, index: int) -> int:
    return source.rfind("\n", 0, index) + 1


def _line_after(source: str, index: int) -> int:
    """The index after the line break ending the line `index` is on, or the end of the text."""
    found = source.find("\n", index)
    return len(source) if found < 0 else found + 1


def _end(source: str, node: yaml.Node) -> int:
    """Where the text of a node ends: after the line its last scalar ends on. A block scalar,
    `|` or `>`, ends at the start of the line after it, which is already that place."""
    index = _leaf(node).end_mark.index
    return index if index > 0 and source[index - 1] == "\n" else _line_after(source, index)


def _block(made: SetAside, prefix: str, newline: str) -> str:
    dumped = yaml.safe_dump(
        [made.model_dump(mode="json")], sort_keys=False, allow_unicode=True, width=10**9
    )
    return "".join(f"{prefix}{line}{newline}" for line in dumped.splitlines())


def _entries(source: str) -> list:
    return list(_load(source).get(KEY) or [])


def _rest(source: str) -> dict:
    loaded = dict(_load(source))
    loaded.pop(KEY, None)
    return loaded


def _as_written(source: str, result: str, newline: str) -> str:
    """The result ending as the source ends: with a line break where it had one, and without
    where it had none."""
    if source and not source.endswith("\n") and result.endswith(newline):
        return result[: -len(newline)]
    return result


def holds(source: str, artifact: str, text: str) -> bool:
    """Whether the manifest sets the passage aside already."""
    return any(
        isinstance(item, dict) and item.get("artifact") == artifact and item.get("text") == text
        for item in _entries(source.removeprefix(BOM))
    )


def added(source: str, made: SetAside) -> str:
    """The manifest's text with `made` as the last `set_aside` entry."""
    bom = BOM if source.startswith(BOM) else ""
    body = source.removeprefix(BOM)
    return bom + _added(body, made)


def _added(source: str, made: SetAside) -> str:
    newline = "\r\n" if "\r\n" in source else "\n"
    found = _key(_top(source))
    if found is None:
        head = source if not source or source.endswith("\n") else source + newline
        result = f"{head}{KEY}:{newline}{_block(made, '', newline)}"
    else:
        key, node = found
        if isinstance(node, yaml.SequenceNode) and node.value and not node.flow_style:
            first = node.value[0]
            start = _line_start(source, first.start_mark.index)
            line = source[start : first.start_mark.index]
            prefix = line[: len(line) - len(line.lstrip())]
            at = _end(source, node.value[-1])
            head = source[:at] if source[:at].endswith("\n") else source[:at] + newline
            result = head + _block(made, prefix, newline) + source[at:]
        elif (isinstance(node, yaml.ScalarNode) and node.tag.endswith(":null")) or (
            isinstance(node, yaml.SequenceNode) and not node.value
        ):
            start = _line_start(source, key.start_mark.index)
            at = _line_after(source, key.end_mark.index)
            line = source[start:at]
            if node.start_mark.line == key.start_mark.line and node.end_mark.index > (
                node.start_mark.index
            ):
                # `set_aside: []` or `set_aside: null`, with anything after it on the line
                # kept: the value goes, and a comment stays.
                ends = line.rstrip("\r\n")
                kept = ends[node.end_mark.index - start :]
                line = ends[: node.start_mark.index - start].rstrip() + kept + line[len(ends) :]
            if not line.endswith("\n"):
                line += newline
            result = source[:start] + line + _block(made, "", newline) + source[at:]
        else:
            raise ManifestShapeError(f"`{KEY}` is not a list written one entry per line")
    result = _as_written(source, result, newline)
    if _entries(result)[-1:] != [made.model_dump(mode="json")] or _rest(result) != _rest(source):
        raise ManifestShapeError("the entry could not be added without changing anything else")
    return result


def _ours(item: object, artifact: str, text: str) -> bool:
    return (
        isinstance(item, dict)
        and item.get("artifact") == artifact
        and item.get("text") == text
        and isinstance(item.get("reviewed"), dict)
        and str(item.get("reason", "")).startswith(PREFIX)
    )


def removed(source: str, artifact: str, text: str) -> str | None:
    """The manifest's text without the entry `repro bot` wrote for the passage, or None where
    it holds no such entry. An entry someone else wrote is never removed."""
    bom = BOM if source.startswith(BOM) else ""
    result = _removed(source.removeprefix(BOM), artifact, text)
    return None if result is None else bom + result


def _removed(source: str, artifact: str, text: str) -> str | None:
    entries = _entries(source)
    index = next((i for i, item in enumerate(entries) if _ours(item, artifact, text)), None)
    if index is None:
        return None
    found = _key(_top(source))
    if found is None or not isinstance(found[1], yaml.SequenceNode) or found[1].flow_style:
        raise ManifestShapeError(f"`{KEY}` is not a list written one entry per line")
    key, node = found
    item = node.value[index]
    if len(node.value) == 1:
        start = _line_start(source, key.start_mark.index)
    else:
        start = _line_start(source, item.start_mark.index)
    if index + 1 < len(node.value):
        end = _line_start(source, node.value[index + 1].start_mark.index)
    else:
        end = _end(source, item)
    newline = "\r\n" if "\r\n" in source else "\n"
    result = _as_written(source, source[:start] + source[end:], newline)
    kept = entries[:index] + entries[index + 1 :]
    if _entries(result) != kept or _rest(result) != _rest(source):
        raise ManifestShapeError("the entry could not be removed without changing anything else")
    return result


__all__ = ["PREFIX", "ManifestShapeError", "added", "entry", "holds", "removed"]
