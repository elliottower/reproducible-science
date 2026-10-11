#!/usr/bin/env python3
"""Refuse an edit to a frozen preregistration, before it happens.

Runs as a Claude Code PreToolUse hook on `Edit`, `Write` and `MultiEdit`. A file is frozen by
the rule the mod uses (`mod/hooks/register.ts`), in two cases. A file of any name with a freeze
record beside it in `.prereg/<name>.json`, which a plan or an amendment frozen whole has, is
frozen: the record existing is enough, whatever it holds. A file named `PREREG.md` carrying a
`**Plan sha256:**` line is a plan frozen in place by an earlier version; the line is found with
the pattern `frozen_plan_changed.py` reads it with. An amendment still in draft has neither and
is edited freely, as is an unfrozen plan and every file that is not a preregistration.

This is the one hook in the set that denies a tool call. A frozen file never changes by one
byte, so there is no edit to it worth letting through and reporting afterward: a note goes in
the log with `prereg log`, and a change to the plan goes in an amendment with `prereg amend`,
which is a file of its own. `frozen_plan_changed.py` still runs after an edit and reports a
frozen file changed by a route this hook does not see.

Design constraints, in order:

1. Never break the session. Every failure exits 0 in silence, which allows the edit.
2. Deny only what is frozen. A plan that cannot be opened and a payload that is not one both
   allow the edit; the check after it reports what this one missed. A freeze record that does
   not parse is still a freeze record, and the edit is refused.
3. Say nothing when there is nothing to refuse.
"""

from __future__ import annotations

import json
import pathlib
import sys

try:
    # One detector for both hooks. A script runs with its own directory first on the path, so
    # the sibling is importable wherever the plugin is installed.
    from frozen_plan_changed import MAX_BYTES, RECORDED, RECORDS
except Exception:
    # Constraint 1.
    sys.exit(0)

#: The one name a plan frozen in place has. Matched whole and by case, as the mod matches it.
PLAN = "PREREG.md"


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


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0

    path_text = (payload.get("tool_input") or {}).get("file_path", "")
    if not path_text:
        return 0
    path = pathlib.Path(path_text)

    record = path.parent / RECORDS / f"{path.name}.json"
    if record.exists():
        return deny(
            f"{path} has a freeze record ({record}), and a frozen file never changes by one "
            f"byte. Record a note with `prereg log`, or a change to the plan as an amendment "
            f"with `prereg amend`, which is a file of its own. Ask the user before doing either."
        )

    if path.name != PLAN:
        return 0

    try:
        if not path.is_file() or path.stat().st_size > MAX_BYTES:
            return 0
        text = path.read_text(errors="replace")
    except OSError:
        return 0

    if not RECORDED.search(text):
        # Not frozen, or not a preregistration. Either way there is nothing to refuse.
        return 0

    return deny(
        f"{path} is a frozen registration, and a frozen plan is not edited in place. Record a "
        f"note with `prereg log`, or a change to the plan as an amendment with `prereg amend`, "
        f"which is a file of its own. Ask the user before doing either."
    )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Constraint 1.
        sys.exit(0)
