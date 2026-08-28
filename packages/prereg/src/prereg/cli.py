"""Preregister your plan to prevent p-hacking and unfalsifiable post-hoc analysis.

    prereg new <name>     scaffold the plan, in OSF's headings
    prereg freeze         record the commit and hash, append to the log
    prereg log <note>     append a line without freezing
    prereg check          has anything above the line changed since the freeze?

One file per experiment, one rule: never edit above the line, only append below it.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

from provenance_core import hint
from provenance_core.gitref import try_run

from prereg import osf, template
from prereg.log import (
    ACCESS,
    append,
    log_problems,
)
from prereg.plan import (
    PREREG,
    STATUS_BLOCK,
    find,
    plan_of,
    rewrite_status,
    sha256_of,
    today,
    unhashed_content,
)


def git(*args, cwd=None) -> str:
    """Stdout of a git command, or "" where git could not answer.

    The empty string is load-bearing here and every caller checks it: `freeze` refuses when
    `rev-parse HEAD` comes back empty, which is how a repository with no commit is caught.
    The shared helper raises instead, so the policy is applied here rather than assumed.
    """
    return try_run(*args, cwd=cwd) or ""


def cmd_new(a) -> int:
    d = pathlib.Path(a.name)
    if (d / PREREG).exists():
        print(f"{d / PREREG} already exists")
        return 1
    (d / "tests").mkdir(parents=True, exist_ok=True)
    (d / "results").mkdir(exist_ok=True)
    title = a.title or d.name.replace("_", " ").replace("-", " ")
    (d / PREREG).write_text(template.render(title, today()))
    print(f"created {d}/")
    print(f"  {PREREG}   the plan, in OSF's headings")
    print("  tests/  results/")
    print("\nfill it in, then `prereg freeze`. Never edit above the log line afterwards.")
    return 0


def cmd_freeze(a) -> int:
    path = find()
    if path is None:
        print(f"no {PREREG} here or above. `prereg new <name>` makes one.")
        return 2
    text = path.read_text()
    if STATUS_BLOCK.search(text) is None:
        print(f"{path} has no `**Status:**` line, so there is nowhere to record the freeze.")
        print("Add one — `**Status:** DRAFT — not frozen.` — or scaffold with `prereg new`.")
        return 1
    if "**Status:** DRAFT" not in text and not a.force:
        print(f"{path} is already frozen. Use `prereg log` to append, or --force.")
        return 1

    problems = unhashed_content(text)
    if problems:
        print(f"{path} has content the freeze would not cover:\n")
        for p in problems:
            print(f"  - {p}")
        print(
            "\nA freeze that leaves part of the plan editable is worse than none, because it"
            "\nreads as registered. Fix these and freeze again."
        )
        return 1

    repo = path.parent
    dirty = git("status", "--porcelain", str(path), cwd=repo)
    if dirty and not a.force:
        print(f"{path} has uncommitted changes. Commit first — the freeze names a commit.")
        return 1

    commit = git("rev-parse", "HEAD", cwd=repo)
    if not commit:
        # `git()` returns "" on any non-zero exit, so a missing binary, a locked index and a
        # directory outside a repository all read as clean. Recording a commit-shaped string
        # in place of a commit made an unanchored freeze look like an anchored one.
        print(f"{path} is not in a git repository with a commit, so a freeze would name none.")
        print("A freeze is evidence because it is anchored: commit the plan first.")
        return 1
    # Normalize the layout first, then hash. Freezing moves any status note onto
    # its own line, and `plan_of` skips marker lines but not that one, so hashing
    # the pre-freeze text would store a digest of a layout the file no longer has
    # and `check` would fail on the freeze itself. Hashing after also makes the
    # freeze idempotent: commit and date sit on skipped lines, so re-freezing an
    # unedited plan reproduces the same digest.
    placeholder = "0" * 64
    text = rewrite_status(text, commit, placeholder, today())
    digest = sha256_of(plan_of(text))
    text = text.replace(f"`{placeholder}`", f"`{digest}`", 1)
    path.write_text(text)
    # `nothing run` was unconditional, so a rewrite forced after a `results seen` entry logged
    # itself as an amendment directly beneath the line saying the outcomes had been examined.
    # The template calls that column the thing that distinguishes an amendment from a
    # deviation; writing it blind defeated the distinction.
    access = getattr(a, "access", None) or ("nothing run" if not a.force else None)
    if access is None:
        print(f"{path} is being re-frozen, and the log already records what has been seen.")
        print("Pass --access with one of: nothing run, no results seen, results not opened,")
        print("results seen. A forced re-freeze cannot describe itself.")
        return 1
    append(path, today(), f"frozen at {commit[:12]}", access)
    print(f"frozen  {path}")
    print(f"  commit  {commit[:12]}")
    print(f"  sha256  {digest[:16]}…  (of everything above the log)")
    print("\nCommit this. The freeze is only evidence once it is in history.")

    if a.osf:
        try:
            _draft_id, url = osf.push_draft(text)
            print(f"\nOSF draft created: {url}")
            print("Review and submit it there — submission is irreversible.")
        except RuntimeError as e:
            print(f"\nOSF push failed: {e}", file=sys.stderr)
            return 1

    return 0


def cmd_log(a) -> int:
    path = find()
    if path is None:
        print(f"no {PREREG} here or above.")
        return 2
    if a.access not in ACCESS:
        print(f"access must be one of: {', '.join(ACCESS)}")
        return 1
    # The log is the tamper record, so a note is not free text. One line of it is one entry, and
    # a note carrying a newline writes a second line that reads exactly like an entry somebody
    # made — including a `frozen at ...` one. A fence closes the block early and puts everything
    # after it outside the log.
    if "\n" in a.note or "\r" in a.note:
        print("a note is one line — a newline in it would read as a second log entry.")
        return 1
    if "```" in a.note:
        print("a note cannot contain ``` — it would close the log block early.")
        return 1
    append(path, today(), a.note, a.access)
    print(f"logged: {a.note}  ({a.access})")
    if a.access == "results seen":
        print("\nRecorded as a deviation: the results were already known.")
    return 0


def check_one(path: pathlib.Path) -> int:
    """0 unchanged, 1 changed, 2 not frozen."""
    text = path.read_text()
    m = re.search(r"\*\*Plan sha256:\*\* `([0-9a-f]{64})`", text)
    if not m:
        print(f"not frozen   {path}")
        return 2
    # `plan_of` skips marker-prefixed lines so the hash cannot cover itself, and `freeze`
    # refuses a plan that hides content behind one. `check` did not, so a line inserted after
    # the freeze -- `**Frozen:** we will also accept p<0.10` -- sat in the plan uncovered and
    # reported unchanged.
    hidden = unhashed_content(text)
    log = log_problems(text)

    now = sha256_of(plan_of(text))
    if now != m.group(1):
        print(f"CHANGED      {path}")
        print(f"  frozen  {m.group(1)[:16]}…")
        print(f"  now     {now[:16]}…")
        return 1
    if hidden:
        print(f"UNCOVERED    {path}")
        for problem in hidden:
            print(f"  - {problem}")
        return 1
    if log:
        print(f"LOG ALTERED  {path}")
        for problem in log:
            print(f"  - {problem}")
        return 1
    print(f"unchanged    {path}")
    return 0


def cmd_setup(a) -> int:
    try:
        env_path = osf.setup_token()
        print(f"saved to {env_path}")
        print(".env added to .gitignore")
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


def cmd_check(a) -> int:
    """Check the governing plan, or every plan below when there is none.

    A repository usually holds one plan per experiment, side by side, so running this at the
    root has to mean "check them all" — otherwise the command is unusable from the one place
    someone would naturally run it.
    """
    path = find()
    if path is not None:
        rc = check_one(path)
        if rc == 1:
            print(
                "\nThe plan was edited after freezing. Restore it and record the change in the log."
            )
        elif rc == 2:
            print("\nNothing to check against yet. `prereg freeze` records the hash.")
        return rc

    found = sorted(pathlib.Path.cwd().rglob(PREREG))
    if not found:
        print(f"no {PREREG} here, above, or below.")
        return 2

    codes = [check_one(f) for f in found]
    changed = codes.count(1)
    print(
        f"\n{len(found)} plans: {codes.count(0)} unchanged, {changed} changed, "
        f"{codes.count(2)} not frozen"
    )
    if changed:
        print("A changed plan was edited after freezing. Restore it and record the change.")
    # The single-plan branch returns 2 for a plan that was never frozen; this one returned 0,
    # so whether an unfrozen registration passed CI depended on which directory it ran from.
    return 1 if (changed or codes.count(2)) else 0


def main(argv: list[str] | None = None) -> int:
    code = _main(argv)
    # After the work, never before it, and never instead of it: the note is about how this
    # project could be run, and a command that has not yet said what it found should not be
    # interrupted to say that.
    hint.note("prereg")
    return code


def _main(argv: list[str] | None = None) -> int:
    """The command. `argv` defaults to the process arguments.

    Taking it explicitly is what lets a caller in the same process run this without touching
    `sys.argv`: `repro prereg` forwards its remaining arguments here, and a test can
    drive the command the way a user does. `citations` and `repro` already had this shape.
    """
    ap = argparse.ArgumentParser(prog="prereg", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd")

    n = sub.add_parser("new", help="scaffold a plan")
    n.add_argument("name")
    n.add_argument("--title")
    n.set_defaults(fn=cmd_new)

    f = sub.add_parser("freeze", help="record the commit and hash")
    f.add_argument("--force", action="store_true")
    f.add_argument(
        "--access",
        choices=["nothing run", "no results seen", "results not opened", "results seen"],
        help="what had been seen when this freeze was recorded; required with --force",
    )
    f.add_argument("--osf", action="store_true", help="push as a draft registration to OSF")
    f.set_defaults(fn=cmd_freeze)

    lg = sub.add_parser("log", help="append a line")
    lg.add_argument("note")
    lg.add_argument("--access", default="no results seen", help=f"one of: {', '.join(ACCESS)}")
    lg.set_defaults(fn=cmd_log)

    s = sub.add_parser("setup", help="save OSF token to .env")
    s.set_defaults(fn=cmd_setup)

    c = sub.add_parser("check", help="has the plan changed since the freeze?")
    c.set_defaults(fn=cmd_check)

    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 0
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
