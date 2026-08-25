#!/usr/bin/env python3
"""Notice when a preregistration changes after it was frozen.

Runs as a Claude Code PostToolUse hook. When an edit touches a plan carrying a recorded
digest, the digest is recomputed and compared. A mismatch means the registered plan and the
plan on disk are different documents.

This is the one check in the set that is exact rather than heuristic. Everything else here
reports a likelihood; this recomputes a hash the author themselves recorded and compares two
strings. It is also the check whose failure matters most: a preregistration exists to stop a
plan being rewritten around the result, and an unrecorded edit to a frozen plan defeats it
entirely, silently, and in a way no reader can detect afterward.

The hook does not refuse the edit. Amending a registration is legitimate; amending it without
saying so is not, and `prereg log` is how it is said.

Design constraints, in order:

1. Never break the session. Every failure exits 0 in silence.
2. Never block. A deviation is a thing to record, not a thing to prevent.
3. Say nothing when there is nothing to say -- when the plan is unfrozen, unchanged, or not
   a preregistration at all.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys

try:
    # One source of truth for what the digest covers. The hook runs as a bare script, so the
    # package may not be importable; the fallback reproduces it rather than doing nothing.
    from prereg.plan import plan_of, sha256_of
except ImportError:  # pragma: no cover - exercised only outside an installed environment
    # This must agree with `prereg.plan` exactly. A fallback that computes a different digest
    # reports every frozen plan as altered, and a hook that cries wolf on the first day is a
    # hook nobody keeps. Mirrored from plan.py: truncate at the log marker, drop the status
    # lines, strip, and end with one newline.
    MARK = "\n---\n\n## Log\n"
    STATUS_PREFIXES = ("**Status:**", "**Plan sha256:**", "**Frozen:**", "**Log:**")

    def plan_of(text: str) -> str:
        """The plan without its status block, which carries the digest and cannot hash itself."""
        at = text.find(MARK)
        plan = text if at < 0 else text[:at]
        keep = [line for line in plan.splitlines() if not line.startswith(STATUS_PREFIXES)]
        return "\n".join(keep).strip() + "\n"

    def sha256_of(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


#: Where a freeze records the digest it took.
RECORDED = re.compile(r"^\*\*Plan sha256:\*\*[ \t]*`([0-9a-f]{64})`", re.M)

#: Files a preregistration is written in.
PLANS = {".md", ".markdown", ".txt"}

#: A plan larger than this is not a plan. A hook runs on every edit and must stay cheap.
MAX_BYTES = 2 * 1024 * 1024


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0

    path_text = (payload.get("tool_input") or {}).get("file_path", "")
    if not path_text:
        return 0
    path = pathlib.Path(path_text)
    if path.suffix.lower() not in PLANS or not path.is_file():
        return 0

    try:
        if path.stat().st_size > MAX_BYTES:
            return 0
        text = path.read_text(errors="replace")
    except OSError:
        return 0

    recorded = RECORDED.search(text)
    if not recorded:
        # Not frozen, or not a preregistration. Either way there is nothing to compare.
        return 0

    current = sha256_of(plan_of(text))
    if current == recorded.group(1):
        return 0

    message = (
        f"{path.name} carries a recorded digest and no longer matches it.\n"
        f"  recorded  {recorded.group(1)}\n"
        f"  now       {current}\n"
        f"The registered plan and the plan on disk are different documents. That is allowed "
        f"and is called a deviation; leaving it unsaid is what a preregistration exists to "
        f"prevent, and no reader can detect it afterward.\n"
        f"Record what changed and why:\n"
        f'  prereg log {path} "<what changed, and why>"\n'
        f"Then re-freeze if the change was intended. Do neither without asking the author: "
        f"amending someone's registration on their behalf is the one thing this must not do."
    )
    json.dump(
        {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": message}},
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Constraint 1.
        sys.exit(0)
