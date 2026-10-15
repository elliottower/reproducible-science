#!/usr/bin/env python3
"""Run one of this plugin's edit hooks against a Codex file edit.

Codex edits files through `apply_patch`, not through `Edit`, `Write` and `MultiEdit`. Its hook
input names no `file_path`: `tool_input.command` carries the whole patch, which may touch
several files, and a patch run as a shell command arrives as a `Bash` call whose command holds
it. The four edit hooks read `tool_input.file_path` with `old_string` and `new_string`, or
`content`, so given a Codex payload they find no file and say nothing.

This script translates and nothing else. It reads the patch, and for each file it touches it
runs the named hook once, unchanged, on the payload Claude Code would have sent for an edit to
that file: `content` for a file the patch adds, `old_string` and `new_string` from the patch's
removed and added lines for one it updates. Paths are made absolute against the session's
`cwd`, as Codex writes them relative. Before the edit every path is checked, a move's source
and destination both, and a deletion too, since deleting a frozen file changes it. After the
edit the file is read where it now is, and a deleted file is not read.

The outputs are merged into one. A refusal from any file refuses the patch, with every reason
given. Context and warnings are joined in the order the files appear.

Only a patch is seen. A file moved or deleted by a shell command such as `mv` or `rm` reaches
no hook here, because nothing in the command names it as a patch does.

Design constraints:

1. Never break the session. A payload or a patch that cannot be read allows the edit.
2. Refuse what the hook refuses, and keep every refusal already found when a later file fails.
3. Fail closed on a frozen file. Before an edit, where the hook could not be run on a path,
   timed out, or answered with something that is not a hook's answer, the edit is refused if
   that path may be a frozen preregistration: a file named `PREREG.md` in any case, or one in
   a directory holding `.prereg/`, as named or with its symlinks resolved. Where even that
   cannot be decided, the edit is refused.
4. Say nothing when there is nothing to say: no patch, or no hook that spoke.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent

#: The hooks this adapter runs, by the event each runs on. Each is the script Claude Code runs,
#: read from beside this one.
HOOKS = {
    "PreToolUse": {"frozen_file_before_edit.py"},
    "PostToolUse": {"frozen_plan_changed.py", "unverified_quotations.py", "unbound_numbers.py"},
}

#: What makes a path one that may be frozen, as `frozen_file_before_edit.py` reads it.
PLAN = "PREREG.md"
RECORDS = ".prereg"

BEGIN = "*** Begin Patch"
END = "*** End Patch"
ADD = "*** Add File: "
DELETE = "*** Delete File: "
UPDATE = "*** Update File: "
MOVE = "*** Move to: "

#: A hook runs on every edit and must stay cheap; a hook that hangs is cut off here.
TIMEOUT_SECONDS = 30


def changes(patch: str) -> list[dict]:
    """Each file the patch touches, in order: its operation, paths, and removed and added text."""
    start = patch.find(BEGIN)
    if start < 0:
        return []
    found: list[dict] = []
    current: dict | None = None
    for raw in patch[start:].splitlines()[1:]:
        line = raw.strip()
        if line.startswith(END):
            break
        for marker, op in ((ADD, "add"), (DELETE, "delete"), (UPDATE, "update")):
            if line.startswith(marker):
                current = {"op": op, "path": line[len(marker) :].strip(), "moved_to": None}
                current["removed"], current["added"] = [], []
                found.append(current)
                break
        else:
            if current is None:
                continue
            if line.startswith(MOVE):
                current["moved_to"] = line[len(MOVE) :].strip()
            elif raw.startswith("+"):
                current["added"].append(raw[1:])
            elif raw.startswith("-"):
                current["removed"].append(raw[1:])
    return found


def located(path_text: str, cwd: str) -> str:
    path = pathlib.Path(path_text).expanduser()
    if not path.is_absolute():
        path = (pathlib.Path(cwd) if cwd else pathlib.Path.cwd()) / path
    return str(path)


def payloads(change: dict, event: str, cwd: str) -> list[dict]:
    """The payloads Claude Code would have sent for this change, one per path to look at."""
    removed = "\n".join(change["removed"])
    added = "\n".join(change["added"])
    if change["op"] == "add":
        tool_name, tool_input = "Write", {"content": added}
    else:
        tool_name, tool_input = "Edit", {"old_string": removed, "new_string": added}

    if event == "PreToolUse":
        paths = [change["path"], change["moved_to"]]
    elif change["op"] == "delete":
        paths = []
    else:
        paths = [change["moved_to"] or change["path"]]

    return [
        {
            "hook_event_name": event,
            "cwd": cwd,
            "tool_name": tool_name,
            "tool_input": {"file_path": located(path, cwd), **tool_input},
        }
        for path in paths
        if path
    ]


def run(hook: str, payload: dict) -> dict | None:
    """The hook's answer, `{}` for silence, or None where it gave no answer a hook gives."""
    try:
        done = subprocess.run(
            [sys.executable, str(HERE / hook)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    if not done.stdout.strip():
        return {}
    try:
        out = json.loads(done.stdout)
    except ValueError:
        return None
    return out if isinstance(out, dict) else None


def may_be_frozen(path_text: str) -> bool:
    """Whether `path_text` could be a frozen preregistration, deciding yes when unsure."""
    try:
        path = pathlib.Path(path_text)
        for target in {path, path.resolve()}:
            if target.name.lower() == PLAN.lower() or (target.parent / RECORDS).exists():
                return True
        return False
    except Exception:
        return True


def refused_unchecked(event: str, path_text: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": event,
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"{path_text} may be a frozen preregistration and could not be checked, so the "
                f"edit is refused. Run `prereg check` to see whether it is frozen, and ask the "
                f"user before changing it."
            ),
        }
    }


def guarded(hook: str, payload: dict, event: str) -> dict:
    """The hook's answer for one file, failing closed before an edit to a possibly frozen one."""
    out = run(hook, payload)
    if out is not None:
        return out
    path_text = payload["tool_input"]["file_path"]
    if event == "PreToolUse" and may_be_frozen(path_text):
        return refused_unchecked(event, path_text)
    return {}


def merged(event: str, outputs: list[dict]) -> dict:
    specific = [out.get("hookSpecificOutput") or {} for out in outputs]
    refusals = [
        s.get("permissionDecisionReason", "")
        for s in specific
        if s.get("permissionDecision") == "deny"
    ]
    if refusals:
        return {
            "hookSpecificOutput": {
                "hookEventName": event,
                "permissionDecision": "deny",
                "permissionDecisionReason": "\n\n".join(refusals),
            }
        }
    result: dict = {}
    context = [s["additionalContext"] for s in specific if s.get("additionalContext")]
    if context:
        result["hookSpecificOutput"] = {
            "hookEventName": event,
            "additionalContext": "\n\n".join(context),
        }
    warnings = [out["systemMessage"] for out in outputs if out.get("systemMessage")]
    if warnings:
        result["systemMessage"] = "\n\n".join(warnings)
    return result


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        return 0
    hook = argv[1]
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    event = payload.get("hook_event_name")
    if hook not in HOOKS.get(event, ()):
        return 0

    command = (payload.get("tool_input") or {}).get("command")
    if not isinstance(command, str):
        return 0
    cwd = payload.get("cwd") or ""

    try:
        translated = [each for change in changes(command) for each in payloads(change, event, cwd)]
    except Exception:
        # Constraint 1: a patch this cannot read is passed, as Codex's own parser will judge it.
        return 0

    outputs = []
    for each in translated:
        try:
            outputs.append(guarded(hook, each, event))
        except Exception:
            # Constraint 3, for a failure `guarded` did not foresee.
            if event == "PreToolUse":
                outputs.append(refused_unchecked(event, each["tool_input"]["file_path"]))
    result = merged(event, outputs)
    if result:
        json.dump(result, sys.stdout)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except Exception:
        # Constraint 1.
        sys.exit(0)
