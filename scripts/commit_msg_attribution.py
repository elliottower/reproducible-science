"""Rewrite AI co-authorship trailers into a disclosure trailer.

`Co-Authored-By` is GitHub's *credit* convention: it lists the named party as a contributor on
the commit and on the repository's contributor graph. For a model that is the wrong claim
twice over -- it asserts authorship that cannot be held, and it reads as padding.

Removing the line entirely is the other wrong answer, because then a commit written with
assistance is indistinguishable from one written without, and the disclosure is what keeps
that honest.

So the trailer is rewritten, not deleted:

    Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
    ->
    Assisted-by: Claude Opus 5

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
TRAILER = re.compile(r"^Co-Authored-By:\s*(.+?)\s*$", re.IGNORECASE)
#: Strip the address: an email implies a mailbox that can be corresponded with.
ADDRESS = re.compile(r"\s*<[^>]*>\s*$")


def rewrite(message: str) -> str:
    out, seen = [], set()
    for line in message.splitlines():
        match = TRAILER.match(line)
        if not match or not AI_AUTHOR.search(match.group(1)):
            out.append(line)
            continue
        name = ADDRESS.sub("", match.group(1)).strip()
        trailer = f"Assisted-by: {name}"
        if trailer not in seen:  # a rebase can duplicate trailers
            seen.add(trailer)
            out.append(trailer)
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
