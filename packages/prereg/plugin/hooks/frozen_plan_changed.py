#!/usr/bin/env python3
"""Notice when a preregistration changes after it was frozen.

Runs as a Claude Code PostToolUse hook. When an edit touches a file with a recorded digest, the
digest is recomputed and compared. A mismatch means the registered document and the one on disk
are different documents.

A freeze is recorded in one of two places. A file frozen whole, a plan or an amendment, has a
record beside it in `.prereg/<name>.json` holding the sha256 of all its bytes. A plan frozen by
an earlier version carries the digest of its plan section in a `**Plan sha256:**` line.

This is the one check in the set that is exact rather than heuristic. Everything else here
reports a likelihood; this recomputes a hash the author themselves recorded and compares two
strings. It is also the check whose failure matters most: a preregistration exists to stop a
plan being rewritten around the result, and an unrecorded edit to a frozen plan defeats it
entirely, silently, and in a way no reader can detect afterward.

The hook does not refuse the edit. Amending a registration is legitimate; amending it without
saying so is not, and `prereg amend` and `prereg log` are how it is said.

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


#: Where a freeze in place records the digest it took.
RECORDED = re.compile(r"^\*\*Plan sha256:\*\*[ \t]*`([0-9a-f]{64})`", re.M)

#: Where a freeze of the whole file records it, beside the file.
RECORDS = ".prereg"


def frozen_whole(path: pathlib.Path) -> str | None:
    """The sha256 `path` was frozen whole with, or None where it has no freeze record."""
    record = path.parent / RECORDS / f"{path.name}.json"
    if not record.is_file():
        return None
    digest = json.loads(record.read_text()).get("sha256")
    return digest if isinstance(digest, str) else None


def report(message: str) -> int:
    json.dump(
        {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": message}},
        sys.stdout,
    )
    return 0


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
        data = path.read_bytes()
    except OSError:
        return 0

    whole = frozen_whole(path)
    if whole is not None:
        now = hashlib.sha256(data).hexdigest()
        if now == whole:
            return 0
        return report(
            f"{path.name} was frozen whole and no longer matches its freeze record.\n"
            f"  recorded  {whole}\n"
            f"  now       {now}\n"
            f"A frozen file never changes by one byte, and `prereg check` now reports this one "
            f"as CHANGED. Restore it from git. A change to the plan is recorded as an amendment, "
            f"a file of its own:\n"
            f"  prereg amend\n"
            f"and a note with `prereg log`. Do neither without asking the author: amending "
            f"someone's registration on their behalf is the one thing this must not do."
        )
    text = data.decode(errors="replace")

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
    return report(message)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Constraint 1.
        sys.exit(0)
