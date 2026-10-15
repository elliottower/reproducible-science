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

import yaml

from repro.exceptions import ReproError
from repro.models import Review, SetAside

KEY = "set_aside"
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


def _top(source: str) -> yaml.MappingNode:
    root = yaml.compose(source, Loader=_loader())
    if not isinstance(root, yaml.MappingNode):
        raise ManifestShapeError("the file is not a mapping")
    return root


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


def _block(made: SetAside, prefix: str, newline: str) -> str:
    dumped = yaml.safe_dump(
        [made.model_dump(mode="json")], sort_keys=False, allow_unicode=True, width=10**9
    )
    return "".join(f"{prefix}{line}{newline}" for line in dumped.splitlines())


def _entries(source: str) -> list:
    loaded = yaml.load(source, Loader=_loader()) or {}
    return list(loaded.get(KEY) or [])


def _rest(source: str) -> dict:
    loaded = dict(yaml.load(source, Loader=_loader()) or {})
    loaded.pop(KEY, None)
    return loaded


def holds(source: str, artifact: str, text: str) -> bool:
    """Whether the manifest sets the passage aside already."""
    return any(
        isinstance(item, dict) and item.get("artifact") == artifact and item.get("text") == text
        for item in _entries(source)
    )


def added(source: str, made: SetAside) -> str:
    """The manifest's text with `made` as the last `set_aside` entry."""
    newline = "\r\n" if "\r\n" in source else "\n"
    root = _top(source)
    found = _key(root)
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
            at = _line_after(source, _leaf(node.value[-1]).end_mark.index)
            head = source[:at] if source[:at].endswith("\n") else source[:at] + newline
            result = head + _block(made, prefix, newline) + source[at:]
        elif (isinstance(node, yaml.ScalarNode) and node.tag.endswith(":null")) or (
            isinstance(node, yaml.SequenceNode) and not node.value
        ):
            start = _line_start(source, key.start_mark.index)
            # An empty value's marks can be the next token's, lines below; `[]` ends at `]`.
            last = key.end_mark.index if isinstance(node, yaml.ScalarNode) else node.end_mark.index
            end = _line_after(source, last - (0 if isinstance(node, yaml.ScalarNode) else 1))
            tail = source[end:]
            result = source[:start] + f"{KEY}:{newline}" + _block(made, "", newline) + tail
        else:
            raise ManifestShapeError(f"`{KEY}` is not a list written one entry per line")
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
    entries = _entries(source)
    index = next((i for i, item in enumerate(entries) if _ours(item, artifact, text)), None)
    if index is None:
        return None
    key, node = _key(_top(source)) or (None, None)
    if not isinstance(node, yaml.SequenceNode) or node.flow_style:
        raise ManifestShapeError(f"`{KEY}` is not a list written one entry per line")
    item = node.value[index]
    if len(node.value) == 1:
        start = _line_start(source, key.start_mark.index)
    else:
        start = _line_start(source, item.start_mark.index)
    if index + 1 < len(node.value):
        end = _line_start(source, node.value[index + 1].start_mark.index)
    else:
        end = _line_after(source, _leaf(item).end_mark.index)
    result = source[:start] + source[end:]
    kept = entries[:index] + entries[index + 1 :]
    if _entries(result) != kept or _rest(result) != _rest(source):
        raise ManifestShapeError("the entry could not be removed without changing anything else")
    return result


__all__ = ["PREFIX", "ManifestShapeError", "added", "entry", "holds", "removed"]
