"""Remove AI co-authorship trailers from a commit message.

`Co-Authored-By` is GitHub's *credit* convention: it lists the named party as a contributor on
the commit and on the repository's contributor graph. For a model that is the wrong claim twice
over -- it asserts authorship that cannot be held, and it reads as padding.

An earlier revision rewrote the line to `Assisted-by:` rather than deleting it, on the reasoning
that a disclosure keeps an assisted commit distinguishable from an unassisted one. Two things
retired that. The disclosure belongs in a paper's acknowledgements and a repository's
documentation, where a reader looks for it, rather than on nine hundred commits where nobody
does. And the `Attribution` workflow rejects `Assisted-by:` alongside the co-authorship trailer,
so this hook was producing commits the repository's own continuous integration refused -- a
disagreement between two artifacts about one fact, which is the defect this project exists to
catch.

So the trailer goes:

    Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>   ->   (removed)
    Assisted-by: Claude Opus 5                              ->   (removed)
    Claude-Session: https://claude.ai/...                   ->   (removed)

Human `Co-Authored-By` lines are left exactly as they are. Those are real people, and their
credit is not this script's to remove.

Installed as a `commit-msg` hook; takes the message file as its only argument.
"""

from __future__ import annotations

import pathlib
import re
import sys

#: Matched against the trailer's value. Deliberately narrow: anything not recognised as a
#: model is treated as a person and left alone.
AI_AUTHOR = re.compile(
    r"\b(claude|gpt-[0-9]|chatgpt|openai|copilot|codex|gemini|cursor|devin|anthropic)\b",
    re.IGNORECASE,
)
#: A co-authorship trailer, whose value decides whether it names a person or a model. Git and
#: GitHub accept any casing, and a case-sensitive version of this let `Co-authored-by:` reach a
#: public contributor graph on 2026-08-25.
TRAILER = re.compile(r"^\s*Co-Authored-By:\s*(.+?)\s*$", re.IGNORECASE)
#: Trailers naming a tool rather than an author. These carry no value line to inspect, so they
#: go on the key alone. `Claude-Session` also puts a session identifier into public history.
TOOL_TRAILER = re.compile(
    r"^\s*(Assisted-by|Claude-Session|Generated-with|AI-Assisted)\s*:", re.IGNORECASE
)


def rewrite(message: str) -> str:
    """The message without any trailer naming a model, and with human trailers untouched."""
    out = []
    for line in message.splitlines():
        if TOOL_TRAILER.match(line):
            continue
        match = TRAILER.match(line)
        if match and AI_AUTHOR.search(match.group(1)):
            continue
        out.append(line)
    while out and not out[-1].strip():  # removing a trailing trailer leaves its blank line
        out.pop()
    return "\n".join(out) + ("\n" if message.endswith("\n") else "")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: commit_msg_attribution.py <commit-msg-file>")
        return 2
    path = pathlib.Path(argv[1])
    original = path.read_text(encoding="utf-8")
    rewritten = rewrite(original)
    if rewritten != original:
        path.write_text(rewritten, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
