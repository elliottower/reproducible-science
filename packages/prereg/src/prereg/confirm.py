"""A typed confirmation, asked on the controlling terminal, before anything is written to OSF.

A registration cannot be deleted, an immediate one is public at once, a view-only link is a URL
anyone holding it can open, and a draft carries the plan and its files off this machine. The question is asked on `/dev/tty` rather than stdin, so
`echo "register abc12" | prereg register ...` does not answer it, and a process with no
controlling terminal -- an agent's shell, CI, cron -- cannot be asked at all and stops there.
There is no flag or variable that skips it.

This raises the cost of an accidental write; it is not a security boundary. A program can
allocate a pseudo-terminal and type into it, and anything that can read `OSF_TOKEN` can call the
API without this package. What keeps an unattended process off OSF is the token not being
readable by it: kept in a secret source that asks the person at read time, such as a
pipe-backed `.env`, which `osf._token` reads only after this confirmation.
"""

from __future__ import annotations

from typing import TextIO

TTY = "/dev/tty"


class NotConfirmed(Exception):
    """Nobody typed the phrase. Nothing has been sent."""


def _open_tty() -> tuple[TextIO, TextIO]:
    # Two handles: a terminal is not seekable, so one opened "r+" in text mode fails on the
    # first write.
    reader = open(TTY, encoding="utf-8")  # closed by the caller
    try:
        writer = open(TTY, "w", encoding="utf-8")
    except OSError:
        reader.close()
        raise
    return reader, writer


def confirm(summary: list[str], phrase: str) -> None:
    """Show `summary` on the terminal and return only if `phrase` is typed back exactly."""
    try:
        reader, writer = _open_tty()
    except OSError as e:
        raise NotConfirmed(
            f"no terminal to confirm on ({TTY}: {e.strerror}). Writing to OSF needs a person "
            "at a terminal to type the confirmation; run this command yourself."
        ) from e
    with reader, writer:
        writer.write("\n".join(summary) + "\n\n")
        writer.write(f"Type `{phrase}` to continue. Anything else cancels.\n> ")
        writer.flush()
        answer = reader.readline()
    if answer.strip() != phrase:
        raise NotConfirmed("cancelled: the confirmation did not match. Nothing was sent to OSF.")
