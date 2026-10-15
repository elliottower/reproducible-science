#!/usr/bin/env python3
"""Refuse an edit to a frozen preregistration, before it happens.

Runs as a Claude Code PreToolUse hook on `Edit`, `Write` and `MultiEdit`. A file is frozen by
the rule the mod uses (`mod/hooks/register.ts`), in two cases. A file of any name with a freeze
record beside it in `.prereg/<name>.json`, which a plan or an amendment frozen whole has, is
frozen: the record existing is enough, whatever it holds. A file named `PREREG.md` carrying a
`**Plan sha256:**` line is a plan frozen in place by an earlier version; the line is found with
the pattern `frozen_plan_changed.py` reads it with. An amendment still in draft has neither and
is edited freely, as is an unfrozen plan and every file that is not a preregistration.

The decision is made from where the target is and not from where this process runs, as the mod
makes it: a leading `~/` is the home directory, an absolute path is kept, and a relative path
is read against the `cwd` of the hook's input, the session's working directory. A plan of any
size is read. The two reasons are the mod's, word for word, and a test holds them equal.

A file is matched by what it is, not by what the edit calls it. The target is checked as named
and again with every symlink resolved, so `link.md` pointing at a frozen `PREREG.md` is the
frozen plan, and an editor that writes through the link is refused. Where the file exists it
is also compared with `os.path.samefile` against `PREREG.md` and against every file with a
freeze record in its directory, so `prereg.md` on a case-insensitive disk, and a hard link, are
the files they open.

This is the one hook in the set that denies a tool call. A frozen file never changes by one
byte, so there is no edit to it worth letting through and reporting afterward: a note goes in
the log with `prereg log`, and a change to the plan goes in an amendment with `prereg amend`,
which is a file of its own. `frozen_plan_changed.py` still runs after an edit and reports a
frozen file changed by a route this hook does not see.

Design constraints, in order:

1. Never break the session. Every failure exits 0 in silence, which allows the edit, except a
   failure to load the detector, which refuses an edit to any file that could be frozen.
2. Deny only what is frozen. A plan that cannot be read and a payload that is not one both
   allow the edit; the check after it reports what this one missed. A freeze record that does
   not parse is still a freeze record, and the edit is refused.
3. Say nothing when there is nothing to refuse.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

#: Where a freeze of the whole file records it, beside the file.
RECORDS = ".prereg"

try:
    # One detector for both hooks. A script runs with its own directory first on the path, so
    # the sibling is importable wherever the plugin is installed.
    from frozen_plan_changed import RECORDED
except Exception:
    # Without the detector this hook cannot tell a frozen plan from a draft. It refuses an edit
    # to any file that could be one, as `may_be_frozen` reads it, and allows the rest.
    RECORDED = None

#: The one name a plan frozen in place has. Matched whole and by case, as the mod matches it.
PLAN = "PREREG.md"


def located(path_text: str, cwd: str) -> pathlib.Path:
    """Where `path_text` is, read as the mod reads it: from the session's directory, not ours."""
    if path_text.startswith("~/"):
        return pathlib.Path.home() / path_text[2:]
    path = pathlib.Path(path_text)
    if path.is_absolute():
        return path
    return (pathlib.Path(cwd) if cwd else pathlib.Path.cwd()) / path


def deny(reason: str) -> int:
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        },
        sys.stdout,
    )
    return 0


def same_file(first: pathlib.Path, second: pathlib.Path) -> bool:
    try:
        return first.exists() and second.exists() and os.path.samefile(first, second)
    except OSError:
        return False


def candidates(path: pathlib.Path) -> list[pathlib.Path]:
    """The target as named, then with every symlink resolved, each once."""
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError):
        return [path]
    return [path] if resolved == path else [path, resolved]


def freeze_record(path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path] | None:
    """(frozen file, its record) where `path` is a file frozen whole, or None."""
    for target in candidates(path):
        record = target.parent / RECORDS / f"{target.name}.json"
        if record.exists():
            return target, record
        records = target.parent / RECORDS
        if not records.is_dir() or not target.exists():
            continue
        for record in sorted(records.glob("*.json")):
            frozen = target.parent / record.name[: -len(".json")]
            if same_file(frozen, target):
                return frozen, record
    return None


def plan_in_place(path: pathlib.Path) -> pathlib.Path | None:
    """The `PREREG.md` that `path` is, by name or by identity, or None."""
    for target in candidates(path):
        if target.name == PLAN:
            return target
        plan = target.parent / PLAN
        if same_file(plan, target):
            return plan
    return None


def may_be_frozen(path: pathlib.Path) -> bool:
    """Whether `path` could be a frozen file: named `PREREG.md` in any case, or in a folder
    holding `.prereg/`, as named or resolved. Deciding yes when that cannot be read."""
    try:
        return any(
            target.name.lower() == PLAN.lower() or (target.parent / RECORDS).exists()
            for target in candidates(path)
        )
    except Exception:
        return True


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0

    path_text = (payload.get("tool_input") or {}).get("file_path", "")
    if not path_text:
        return 0
    path = located(path_text, payload.get("cwd") or "")

    if RECORDED is None:
        if not may_be_frozen(path):
            return 0
        return deny(
            f"{path} may be a frozen preregistration, and this hook could not load the check that "
            f"tells (frozen_plan_changed.py beside it), so the edit is refused. Run `prereg "
            f"check` to see whether it is frozen, and ask the user before changing it."
        )

    found = freeze_record(path)
    if found is not None:
        frozen, record = found
        return deny(
            f"{frozen} has a freeze record ({record}), and a frozen file never changes by one "
            f"byte. Record a note with `prereg log`, or a change to the plan as an amendment "
            f"with `prereg amend`, which is a file of its own. Ask the user before doing either."
        )

    plan = plan_in_place(path)
    if plan is None:
        return 0

    try:
        if not plan.is_file():
            return 0
        text = plan.read_text(errors="replace")
    except OSError:
        return 0

    if not RECORDED.search(text):
        # Not frozen, or not a preregistration. Either way there is nothing to refuse.
        return 0

    return deny(
        f"{plan} is a frozen registration, and a frozen plan is not edited in place. Record a "
        f"note with `prereg log`, or a change to the plan as an amendment with `prereg amend`, "
        f"which is a file of its own. Ask the user before doing either."
    )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Constraint 1.
        sys.exit(0)
