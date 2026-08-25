#!/usr/bin/env python3
"""Append-only log of every file an agent read during a session.

Runs as a Claude Code PostToolUse hook. Receives the tool call on stdin as JSON and
writes one line of JSONL per access. The model does not produce this record and cannot
edit it, which is the point: an agent's account of what it read is a claim, and this is
an observation.

Design constraints, in order of priority:

1. Never break the session. Any failure exits 0 silently. A logger that can halt the
   work it observes will be turned off, and a logger that is off records nothing.
2. Never block. Blocking belongs in PreToolUse (see `guard.py`); this only witnesses.
3. Append only. The log is evidence, so it is never rewritten in place.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import shlex
import sys
import time

#: Where the log lands. Overridable so a study can keep its own log beside its data.
LOG_PATH = pathlib.Path(
    os.environ.get("EXPOSURE_LOG", pathlib.Path.home() / ".claude" / "exposure.jsonl")
)

#: Rotate past this size, keeping one previous generation, so the log is bounded at
#: twice this figure. At ~275 bytes per record a heavy day writes ~270 KB, so 32 MB is
#: roughly four months of continuous heavy use before the first rotation.
#:
#: Rotation rather than truncation: an evidence log that silently drops its oldest
#: records is worse than one that grows, and a log that can fill a disk will be deleted
#: by whoever it inconveniences.
MAX_BYTES = int(os.environ.get("EXPOSURE_LOG_MAX_BYTES", 32 * 1024 * 1024))

#: Marker that opts a directory tree in. The hook is installed globally but records
#: nothing unless the working directory, or one of its ancestors, contains this file.
#:
#: Opt-in by marker rather than by launch directory, because Claude Code resolves project
#: settings from where it was started, not from what is being edited — so a repo-scoped
#: hook silently fails to fire for anyone who works from a single root. Opt-in by marker
#: is also the conservative default: a global logger that records every path an agent
#: touches would capture client names, cohort identifiers, and embargoed data locations
#: from unrelated work.
MARKER = ".exposure"


def in_scope(path: str) -> bool:
    """Is this path inside an opted-in tree, via a marker beside it or above it?

    Scope follows the path that was touched, not the session's working directory. An
    agent rooted anywhere can read a study's outcome file by absolute path, and gating on
    cwd would miss exactly that -- which is the case the marker exists to catch.
    """
    try:
        target = pathlib.Path(path).expanduser().resolve()
    except Exception:
        return False
    start = target if target.is_dir() else target.parent
    for directory in (start, *start.parents):
        if (directory / MARKER).exists():
            return True
    return False


#: Tools whose input names a path directly.
PATH_TOOLS = {"Read", "Edit", "Write", "NotebookEdit", "Grep", "Glob"}

#: Bash tokens that read a file. A command's first path-shaped argument after one of
#: these is recorded. Deliberately conservative: over-recording a path that was not read
#: is harmless, and silently missing one is not, so anything ambiguous is recorded.
READING_COMMANDS = {
    "cat",
    "head",
    "tail",
    "less",
    "more",
    "grep",
    "rg",
    "egrep",
    "fgrep",
    "awk",
    "sed",
    "sort",
    "uniq",
    "wc",
    "cut",
    "diff",
    "jq",
    "python3",
    "python",
    "open",
    "cp",
    "pdftotext",
    "unzip",
    "tar",
}

#: A token is path-shaped if it contains a separator, starts at home, or is a filename
#: with a real stem and extension. The stem requirement rejects tool arguments that only
#: look like dotfiles -- `jq .accuracy` names a filter, not a file.
PATHISH = re.compile(r"/|^~|^[^.\s][^/\s]*\.[A-Za-z0-9]+$")


def paths_from_bash(command: str) -> list[str]:
    """Best-effort extraction of paths a shell command reads.

    This is a heuristic and is documented as one. A command can read a file this misses
    (a path built at runtime, a heredoc, a glob expanded by the shell). The log therefore
    establishes that a path WAS read, never that one was not.
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        return []
    found, armed = [], False
    for token in tokens:
        base = token.rsplit("/", 1)[-1]
        if base in READING_COMMANDS:
            armed = True
            continue
        if token.startswith("-"):
            continue
        if armed and PATHISH.search(token):
            found.append(token)
    return found


def paths_from(tool_name: str, tool_input: dict) -> list[str]:
    if tool_name in PATH_TOOLS:
        for key in ("file_path", "path", "notebook_path", "pattern"):
            value = tool_input.get(key)
            if isinstance(value, str) and value:
                return [value]
        return []
    if tool_name == "Bash":
        command = tool_input.get("command")
        return paths_from_bash(command) if isinstance(command, str) else []
    return []


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except Exception:
        return 0

    tool_name = event.get("tool_name") or ""
    tool_input = event.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return 0

    paths = [p for p in paths_from(tool_name, tool_input) if in_scope(p)]
    if not paths:
        return 0

    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "session": event.get("session_id") or "",
        "cwd": event.get("cwd") or "",
        "tool": tool_name,
        "paths": [str(pathlib.Path(p).expanduser()) for p in paths],
    }

    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        if LOG_PATH.exists() and LOG_PATH.stat().st_size >= MAX_BYTES:
            LOG_PATH.replace(LOG_PATH.with_suffix(LOG_PATH.suffix + ".1"))
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
