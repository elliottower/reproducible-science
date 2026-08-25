#!/usr/bin/env python3
"""Notice when a number enters a manuscript without a run behind it.

Runs as a Claude Code PostToolUse hook. Reads the tool call on stdin, works out which numbers
the edit added to a manuscript, and reports any that no recorded claim names.

The reason this is a hook rather than an instruction. Binding a claim to a run is a separate
deliberate act, and separate deliberate acts do not happen -- literate programming solved this
problem completely in 1984 and lost anyway. The address is on screen while the sentence is
written and gone immediately after, so the moment to record it is that moment, and something
has to notice when the moment passes.

Design constraints, in order:

1. Never break the session. Every failure exits 0 in silence. A hook that can halt the work
   it observes gets turned off, and a hook that is off notices nothing.
2. Never block. This witnesses and reports; it does not refuse an edit.
3. Say nothing when there is nothing to say. A hook that fires on every edit is noise, and
   noise gets muted. It speaks only when a manuscript gained a number nothing backs.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

try:
    # One source of truth for what counts as a number and what owes no run. The hook runs as
    # a bare script, so the package may not be importable; the fallbacks below keep it
    # working rather than silently doing nothing.
    from results.manuscript import LAYOUT, NUMBER, SUFFIXES, constraining_digits, needs_no_claim
except ImportError:  # pragma: no cover - exercised only outside an installed environment
    NUMBER = re.compile(
        r"(?<![\w.])(?:(?<![-‐‑‒–—])[-+])?"
        r"\d(?:,?\d)*(?:\.\d+)?(?:[eE][-+]?\d+)?(?![\w])"
    )
    LAYOUT = re.compile(
        r"\\(?:vspace|hspace|setlength|includegraphics|multirow|multicolumn|cmidrule|cline"
        r"|rule|label|ref|eqref|cite[a-z]*|bibitem|newcommand|usepackage|documentclass)"
        r"\s*(?:\[[^\]]*\])?\s*(?:\{[^{}]*\})*",
        re.I,
    )
    SUFFIXES = {".tex", ".md", ".rmd", ".qmd", ".typ", ".org", ".rst", ".txt"}
    _CONSTANTS = {"0", "1", "2", "3", "4", "5", "10", "100", "1000", "1.96", "0.05",
                  "0.01", "0.001", "95", "99", "0.5", "0.95", "2.5", "97.5"}

    def constraining_digits(printed: str) -> int:
        body = printed.lstrip("-+").replace(",", "")
        if "." in body:
            return max(1, len(body.replace(".", "").lstrip("0")))
        return max(1, len(body.strip("0") or "0"))

    def needs_no_claim(printed: str, line: str, at: int) -> str | None:
        if printed in _CONSTANTS:
            return "a constant of the formula"
        if constraining_digits(printed) < 2:
            return "a single digit"
        return None

#: Never read a ledger larger than this. A hook runs on every edit and must stay cheap.
MAX_LEDGER_BYTES = 8 * 1024 * 1024

#: How many unbound values to name before summarising the rest.
MAX_SHOWN = 8


def added_numbers(payload: dict) -> set[str]:
    """Numbers this edit put into the file that were not in the text it replaced."""
    tool_input = payload.get("tool_input") or {}
    before, after = "", ""
    if "content" in tool_input:
        after = str(tool_input["content"])
    elif "edits" in tool_input:
        for edit in tool_input["edits"] or []:
            before += str(edit.get("old_string", ""))
            after += str(edit.get("new_string", ""))
    else:
        before = str(tool_input.get("old_string", ""))
        after = str(tool_input.get("new_string", ""))

    def owing(text: str) -> set[str]:
        stripped = LAYOUT.sub(" ", text)
        found = set()
        for line in stripped.splitlines():
            for match in NUMBER.finditer(line):
                if needs_no_claim(match.group(0), line, match.start()) is None:
                    found.add(match.group(0))
        return found

    return owing(after) - owing(before)


def bound_values(start: pathlib.Path) -> tuple[set[str], pathlib.Path] | None:
    """Numbers named by a recorded claim, and the ledger naming them, or None if untracked."""
    for directory in [start, *start.parents]:
        ledger = directory / ".results" / "ledger.jsonl"
        if not ledger.is_file():
            continue
        try:
            if ledger.stat().st_size > MAX_LEDGER_BYTES:
                return None
            found: set[str] = set()
            for line in ledger.read_text(errors="replace").splitlines():
                if '"claim"' not in line:
                    continue
                record = json.loads(line)
                if record.get("event") == "claim":
                    found.update(NUMBER.findall(record.get("claim", "")))
            return found, ledger
        except (OSError, ValueError):
            return None
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0

    path_text = (payload.get("tool_input") or {}).get("file_path", "")
    if not path_text:
        return 0
    path = pathlib.Path(path_text)
    if path.suffix.lower() not in SUFFIXES:
        return 0

    # Only ever walk up from the file itself. Falling back to the working directory finds the
    # ledger of whichever repository the session started in, and reports an unrelated
    # project's numbers as unbound.
    tracked = bound_values(path.parent)
    if tracked is None:
        return 0
    bound, ledger = tracked

    unbound = sorted(added_numbers(payload) - bound)
    if not unbound:
        return 0

    shown = ", ".join(unbound[:MAX_SHOWN])
    if len(unbound) > MAX_SHOWN:
        shown += f", and {len(unbound) - MAX_SHOWN} more"
    message = (
        f"{len(unbound)} number(s) entered {path.name} that no recorded claim names: {shown}. "
        f"The source is in context now and will not be later. For each one that states a "
        f"result, record it before moving on:\n"
        f'  results claim --run-id <run> --location "<where in the manuscript>" '
        f'"<the sentence as it appears>"\n'
        f"For a value quoted from another paper, or a parameter fixed by choice, say so once "
        f"rather than each time. `results coverage {path.name}` audits the whole draft. "
        f"Ledger: {ledger}"
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
        # Constraint 1. Nothing this hook can fail at is worth interrupting the work.
        sys.exit(0)
