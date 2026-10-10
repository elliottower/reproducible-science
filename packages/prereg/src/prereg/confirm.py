"""A typed confirmation, asked on the controlling terminal, before OSF writes that cannot be undone.

A registration cannot be deleted, an immediate one is public at once, and a view-only link is a
URL anyone holding it can open. A draft is not asked about: it is private to its author and can be
deleted, so `freeze --osf` runs unattended. The question is asked on `/dev/tty` rather than stdin, so
`echo "register abc12" | prereg register ...` does not answer it, and a process with no
controlling terminal -- an agent's shell, CI, cron -- cannot be asked at all and stops there.

One thing skips the question, for a single registration, and it takes two parts given together:
`register --confirm <draft id>`, naming the draft exactly, and `PREREG_UNATTENDED_REGISTER=1` in
the environment. The flag says which draft was approved and the variable says that registering
with nobody at the terminal was asked for; either one alone is refused. The log entry then says
the registration was unattended. A batch and a view-only link have no such path.

This raises the cost of an accidental write; it is not a security boundary. A program can
allocate a pseudo-terminal and type into it, and anything that can read `OSF_TOKEN` can call the
API without this package. What keeps an unattended process off OSF is the token not being
readable by it: kept in a secret source that asks the person at read time, such as a
pipe-backed `.env`, which `osf._token` reads only after this confirmation.
"""

from __future__ import annotations

import os
from typing import TextIO

TTY = "/dev/tty"

#: Set to `1`, with `register --confirm <draft id>`, to register with nobody at the terminal.
UNATTENDED_ENV = "PREREG_UNATTENDED_REGISTER"


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


def confirm_unattended(given: str, expected: str) -> None:
    """Return only if `given` names the draft being registered and the environment opts in.

    Stands in for the typed phrase, so it refuses the same way: before any request, with
    `NotConfirmed`. The id has to match because it is what the person approved; the variable has
    to be set because a flag alone is one argument away from every `register` an agent writes.
    """
    if given != expected:
        raise NotConfirmed(
            f"--confirm {given} does not name this plan's draft, which is {expected}. "
            "Nothing was sent to OSF."
        )
    if os.environ.get(UNATTENDED_ENV) != "1":
        raise NotConfirmed(
            f"--confirm registers with nobody at the terminal only where {UNATTENDED_ENV}=1 is "
            "set, and it is not. Nothing was sent to OSF."
        )
