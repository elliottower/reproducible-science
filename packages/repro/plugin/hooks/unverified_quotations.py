#!/usr/bin/env python3
"""Notice when a quotation enters a manuscript that no claim file pins to a source.

Runs as a Claude Code PostToolUse hook. Reads the tool call on stdin, finds the passages the
edit quoted, and reports any that appear in no `claims/*.yaml`.

A quotation is the one thing in a paper that can be checked exactly. It either appears in the
source or it does not, and a model writing prose is the likeliest place for one to drift: a
remembered sentence is nearly right, and nearly right is wrong. The check is cheap while the
source is open and impossible once the paper is finished.

Design constraints, in order:

1. Never break the session. Every failure exits 0 in silence. A hook that can halt the work
   it observes gets turned off, and a hook that is off notices nothing.
2. Never block. This witnesses and reports; it does not refuse an edit.
3. Say nothing when there is nothing to say. It speaks only when a manuscript gained a
   passage nothing pins.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

#: Manuscript sources a quotation can be written into.
MANUSCRIPT = {".tex", ".md", ".rmd", ".qmd", ".typ", ".org", ".rst", ".txt"}

#: How a quotation is written. LaTeX prefers ``like this'', packages add \enquote and
#: \textquote, and Markdown uses ordinary double quotes.
QUOTATIONS = [
    re.compile(r"``(.+?)''", re.S),
    re.compile(r"\\(?:enquote|textquote|blockquote)\s*\{(.+?)\}", re.S),
    re.compile(r"[\u201c](.+?)[\u201d]", re.S),
    re.compile(r'"([^"\n]{40,})"'),
]

#: Shorter than this and a passage is a phrase rather than a quotation: a title, a term of
#: art, a variable name in prose. `citations` uses the same floor when deciding whether a
#: quote is checkable at all.
MIN_QUOTE_CHARS = 40

#: Claim files are small; a directory of them is not. Read no more than this many.
MAX_CLAIM_FILES = 400


def fold(text: str) -> str:
    """A passage reduced to what survives retyping: case, spacing and punctuation removed.

    Quotations drift in ways that do not change the words -- a curly apostrophe becomes
    straight, a line break becomes a space, an en dash becomes a hyphen. Comparing folded
    forms keeps those from reading as a passage nobody pinned.
    """
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def quoted(text: str) -> set[str]:
    found = set()
    for pattern in QUOTATIONS:
        for match in pattern.finditer(text):
            passage = " ".join(match.group(1).split())
            if len(passage) >= MIN_QUOTE_CHARS:
                found.add(passage)
    return found


def added(payload: dict) -> set[str]:
    """Passages this edit quoted that the text it replaced did not."""
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
    return quoted(after) - quoted(before)


def pinned(start: pathlib.Path) -> tuple[set[str], pathlib.Path] | None:
    """Every folded passage a claim file pins, and the directory holding them.

    Walks upward, since a manuscript usually sits beside the claims directory rather than
    inside it. Returns None where no claims directory governs this file, so a project that
    never opted in is never lectured.
    """
    for directory in [start, *start.parents]:
        claims = directory / "claims"
        if not claims.is_dir():
            continue
        found: set[str] = set()
        for path in sorted(claims.rglob("*.y*ml"))[:MAX_CLAIM_FILES]:
            try:
                text = path.read_text(errors="replace")
            except OSError:
                continue
            # Read as text rather than as YAML: the hook must not depend on a parser being
            # installed, and a passage is recognisable without one.
            for match in re.finditer(r"(?:exact|text)\s*:\s*(.+)", text):
                value = match.group(1).strip().strip("\"'|>-").strip()
                if len(value) >= MIN_QUOTE_CHARS:
                    found.add(fold(value))
        return found, claims
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
    if path.suffix.lower() not in MANUSCRIPT:
        return 0

    library = pinned(path.parent)
    if library is None:
        return 0
    known, claims = library

    # A pinned passage may be quoted in part, so a manuscript passage counts as pinned when
    # it is contained in one. The reverse would let a single word stand in for a paragraph.
    loose = [q for q in added(payload) if not any(fold(q) in k for k in known)]
    if not loose:
        return 0

    listed = "\n".join(f"    - {q[:110]}" for q in sorted(loose)[:4])
    more = f"\n    ... and {len(loose) - 4} more" if len(loose) > 4 else ""
    message = (
        f"{len(loose)} quotation(s) entered {path.name} that no claim file pins to a "
        f"source:\n{listed}{more}\n"
        f"A remembered sentence is usually nearly right, and nearly right is wrong. Add each "
        f"to a claim file under {claims} with the source it came from, then run "
        f"`citations verify --claims {claims}`. If a passage is the author's own words "
        f"rather than a quotation, leave it and say so once."
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
