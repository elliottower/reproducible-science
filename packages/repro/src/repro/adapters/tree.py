"""JSON and restricted YAML, addressed by RFC 6901 pointer."""

from __future__ import annotations

import json
import pathlib

import yaml

from repro.adapters.base import Found, Resolution, _no, _ok
from repro.exceptions import ArtifactUnreadableError
from repro.models import (
    TreeLocator,
)

# ------------------------------------------------------------------------------------ trees

_TREE_SUFFIXES = {".json": "json", ".yaml": "yaml", ".yml": "yaml"}
_MISSING = object()


def resolve_pointer(document: object, pointer: str) -> object:
    """RFC 6901 JSON Pointer resolution. Returns `_MISSING` when the pointer does not resolve.

    `~1` is a literal `/` and `~0` a literal `~`, unescaped in that order, so a key containing
    a slash is addressable and a key containing a period is unremarkable.
    """
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise ValueError(f"JSON Pointer must start with '/': {pointer!r}")
    node = document
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict):
            if token not in node:
                return _MISSING
            node = node[token]
        elif isinstance(node, list):
            # RFC 6901 array indices are digits with no leading zeros, so "01" addresses
            # nothing and is not silently read as 1.
            if not token.isdigit() or (len(token) > 1 and token[0] == "0"):
                return _MISSING
            index = int(token)
            if index >= len(node):
                return _MISSING
            node = node[index]
        else:
            return _MISSING
    return node


def _no_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict:
    """`json.loads` keeps the last of a duplicated key, exactly as PyYAML does.

    The YAML path has rejected this from the start; JSON did not, so one artifact could hold
    two values for one quantity and resolve to whichever came last. That is the finding this
    repository's own regression corpus records against someone else's paper.
    """
    seen: dict[str, object] = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError(f"duplicate key {key!r}")
        seen[key] = value
    return seen


class _StrictYaml(yaml.SafeLoader):
    """SafeLoader that refuses duplicate mapping keys.

    PyYAML keeps the last of a duplicated key, so a file with two `accuracy:` entries resolves
    to one of them with nothing said. An artifact that cannot be read one way only is not one
    a pointer can address.
    """


def _no_duplicate_keys(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate key {key!r}", key_node.start_mark
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_StrictYaml.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicate_keys)


def _load_tree(path: pathlib.Path) -> object:
    fmt = _TREE_SUFFIXES.get(path.suffix.lower())
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as e:
        raise ArtifactUnreadableError(path, str(e)) from e
    if fmt == "json":
        try:
            return json.loads(text, object_pairs_hook=_no_duplicate_json_keys)
        except json.JSONDecodeError as e:
            raise ArtifactUnreadableError(path, f"not valid JSON: {e}") from e
        except ValueError as e:  # raised by the hook below
            raise ArtifactUnreadableError(path, str(e)) from e
    try:
        return yaml.load(text, Loader=_StrictYaml)
    except yaml.YAMLError as e:
        raise ArtifactUnreadableError(path, f"not valid YAML: {e}") from e


def _resolve_tree(locator: TreeLocator, path: pathlib.Path) -> Found:
    if path.suffix.lower() not in _TREE_SUFFIXES:
        return _no(
            Resolution.FORMAT_UNSUPPORTED,
            f"a tree locator addresses JSON or YAML; {path.name} is "
            f"{path.suffix or 'extensionless'}",
        )
    node = resolve_pointer(_load_tree(path), locator.pointer)
    if node is _MISSING:
        return _no(Resolution.ABSENT, f"{locator.pointer} does not resolve in {path.name}")
    if isinstance(node, (dict, list)):
        return _no(
            Resolution.NOT_SCALAR, f"{locator.pointer} holds a {type(node).__name__}, not a value"
        )
    if node is None:
        return _no(Resolution.ABSENT, f"{locator.pointer} holds null")
    return _ok(str(node), type(node).__name__, locator.pointer)
