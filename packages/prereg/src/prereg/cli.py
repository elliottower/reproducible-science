"""Freeze a plan before you run it, and record what changed after.

    prereg new <name>     scaffold the plan, in OSF's headings
    prereg freeze         record the commit and hash, append to the log
    prereg log <note>     append a line without freezing
    prereg check          has anything above the line changed since the freeze?

One file per experiment, one rule: never edit above the line, only append below it.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import pathlib
import re
import subprocess
import sys

from prereg import osf, template

PREREG = "PREREG.md"
MARK = "\n---\n\n## Log\n"
ACCESS = ["nothing run", "no results seen", "results not opened", "results seen"]


def today() -> str:
    return datetime.date.today().isoformat()


def git(*args, cwd=None) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def find(start: pathlib.Path | None = None) -> pathlib.Path | None:
    """The PREREG.md governing this directory: here, or the nearest one above."""
    here = (start or pathlib.Path.cwd()).resolve()
    for d in [here, *here.parents]:
        if (d / PREREG).is_file():
            return d / PREREG
    return None


def plan_of(text: str) -> str:
    """What the freeze hashes: the plan, minus its own status block.

    The status lines carry the commit, the hash and the freeze date, and they are written into
    the file by `freeze` itself. Including them would mean the hash covered a value derived
    from the hash, so the check could never pass.
    """
    i = text.find(MARK)
    plan = text if i < 0 else text[:i]
    keep = [
        ln
        for ln in plan.splitlines()
        if not ln.startswith(("**Status:**", "**Plan sha256:**", "**Frozen:**", "**Log:**"))
    ]
    return "\n".join(keep).strip() + "\n"


def sha256_of(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def unhashed_content(text: str) -> list[str]:
    """Parts of the plan the hash would not cover, which `freeze` refuses to register.

    Two things are skipped when hashing, both for good reasons, and both exploitable if they
    appear where they are not meant to. The log marker ends the hashed region, so a second one
    in the body leaves everything after it editable without `check` noticing. Marker-prefixed
    lines are skipped because `freeze` writes them, so one in the body is editable the same way.

    Refusing is better than hashing them anyway: changing what the hash covers would invalidate
    every plan already frozen, while refusing only affects plans not yet registered.
    """
    problems = []
    if text.count(MARK) > 1:
        problems.append(
            "the log marker (`---` then `## Log`) appears more than once. Hashing stops at the "
            "first, so the plan after it would not be covered."
        )
    i = text.find(MARK)
    plan = text if i < 0 else text[:i]
    m = STATUS_BLOCK.search(plan)
    body = (plan[: m.start()] + plan[m.end() :]) if m else plan
    stray = [
        ln
        for ln in body.splitlines()
        if ln.startswith(("**Status:**", "**Plan sha256:**", "**Frozen:**"))
    ]
    if stray:
        problems.append(
            "these lines sit outside the status block and are skipped when hashing, so they "
            "could be edited after freezing without `check` noticing:\n      "
            + "\n      ".join(stray[:5])
        )
    return problems


STATUS_BLOCK = re.compile(r"^\*\*Status:\*\*.*?(?=\n[ \t]*\n|\Z)", re.S | re.M)

# A status line may carry a note after its sentence — "third version; see Log".
# The note is plan content and has to survive a freeze; the marker and its own
# value do not.
STATUS_VALUES = [
    re.compile(r"^\*\*Status:\*\*[ \t]*DRAFT[ \t]*—[ \t]*not frozen\.?"),
    re.compile(r"^\*\*Status:\*\*[ \t]*FROZEN at `[^`]*`\.?"),
    re.compile(r"^\*\*Plan sha256:\*\*[ \t]*`[0-9a-f]*`\.?"),
    re.compile(r"^\*\*Frozen:\*\*[ \t]*\d{4}-\d{2}-\d{2}\.?"),
]


def status_note(block: str) -> str:
    """Whatever the status block says beyond the markers' own values."""
    out = []
    for line in block.splitlines():
        for rx in STATUS_VALUES:
            stripped = rx.sub("", line, count=1)
            if stripped != line:
                line = stripped
                break
        if line.strip():
            out.append(line.strip())
    return " ".join(out)


def rewrite_status(text: str, commit: str, digest: str, date: str) -> str:
    """Replace the whole status block, draft or already frozen.

    Matching only the literal draft sentence did nothing on a plan that was
    already frozen, so `--force` printed a new hash, wrote none of it, and left
    the plan failing its own check — silently, with a zero exit code. Matching
    the block also stops a note written after `**Status:**` from being glued onto
    the freeze date, which is what a prefix-only replacement did to it.
    """
    m = STATUS_BLOCK.search(text)
    if m is None:
        return text
    note = status_note(m.group(0))
    block = (
        f"**Status:** FROZEN at `{commit[:12]}`\n**Plan sha256:** `{digest}`\n**Frozen:** {date}"
    )
    if note:
        block += f"\n{note}"
    return text[: m.start()] + block + text[m.end() :]


LOG_MARK = "\u00b7"  # separates the entry from its chain value


def log_lines(text: str) -> list[str]:
    """The log entries, in order, without the fence."""
    _, _, tail = text.partition(MARK)
    inside = tail.partition("```")[2].rpartition("```")[0]
    return [ln.rstrip() for ln in inside.splitlines() if ln.strip()]


def chain_value(previous: str, entry: str) -> str:
    """Each entry's link. Short, because it sits in a file people read."""
    return sha256_of(f"{previous}\x00{entry.strip()}")[:8]


LOG_ANCHOR = re.compile(r"^\*\*Log:\*\* (\d+) entries, head `([0-9a-f]{8})`", re.M)


def log_head(text: str) -> tuple[int, str]:
    """Number of entries and the chain value of the last, for the anchor line."""
    previous, count = "", 0
    for line in log_lines(text):
        entry, _, recorded = line.rpartition(LOG_MARK)
        previous = recorded.strip() if entry else chain_value(previous, line)
        count += 1
    return count, previous


def set_log_anchor(text: str) -> str:
    """Record the log's length and head beside the plan hash.

    Chaining alone cannot see an entry removed from the *end*: the entries that remain still
    follow one another. The anchor is the witness to the length, exactly as the ledger's is,
    and it sits on a marker line the plan hash skips, so recording it cannot change the hash.
    """
    count, head = log_head(text)
    line = f"**Log:** {count} entries, head `{head or '00000000'}`"
    if LOG_ANCHOR.search(text):
        return LOG_ANCHOR.sub(line.replace("\\", "\\\\"), text, count=1)
    marker = re.search(r"^\*\*Plan sha256:\*\* .*$", text, re.M)
    if marker:
        return text[: marker.end()] + "\n" + line + text[marker.end() :]
    return text


def log_problems(text: str) -> list[str]:
    """Where the log has been edited, reordered or had an entry removed.

    The plan's hash deliberately stops at the log, since the log is written after freezing and
    including it would make the hash cover itself. That left the record of deviations -- the
    file's only account of what changed after the plan was fixed -- freely deletable with any
    editor, while `check` still reported the plan unchanged. Chaining the entries makes a
    removal visible without bringing them under the plan hash.
    """
    problems: list[str] = []
    previous = ""
    for i, line in enumerate(log_lines(text), start=1):
        entry, _, recorded = line.rpartition(LOG_MARK)
        if not entry:
            # Written before the log was chained, or by hand. Fold it in rather than report
            # it: the chain protects every entry from the first chained one onward, and
            # calling a plain line tampering would flag every plan written under the old
            # format.
            previous = chain_value(previous, line)
            continue
        expected = chain_value(previous, entry)
        if recorded.strip() != expected:
            problems.append(
                f"log entry {i} does not follow the one before it: an entry has been "
                f"edited, reordered or removed"
            )
            return problems
        previous = expected

    anchor = LOG_ANCHOR.search(text)
    if anchor:
        count, head = log_head(text)
        if int(anchor.group(1)) != count:
            problems.append(
                f"the log records {anchor.group(1)} entries and holds {count}: "
                f"an entry has been removed from the end"
            )
        elif anchor.group(2) != (head or "00000000"):
            problems.append("the log's last entry is not the one recorded")
    return problems


def append(path: pathlib.Path, date: str, event: str, access: str) -> None:
    text = path.read_text()
    if MARK not in text:
        text += MARK.rstrip("\n") + "\n\n```\n```\n"
    head, _, tail = text.partition(MARK)
    # Two spaces, not just padding. `{event:<36}` emits nothing extra once the note passes 36
    # characters, and the access level then runs into the note — losing the boundary of the one
    # field that separates an amendment from a deviation.
    entry = f"{date}  {event:<36}  {access}"
    previous = ""
    for existing in log_lines(text):
        entry_text, _, recorded = existing.rpartition(LOG_MARK)
        # An entry written before the log was chained carries no value; fold it in so the
        # chain still covers it rather than restarting from nothing.
        previous = recorded.strip() if entry_text else chain_value(previous, existing)
    line = f"{entry}  {LOG_MARK}{chain_value(previous, entry)}"
    if "```" in tail:
        before, fence, after = tail.rpartition("```")
        tail = before.rstrip("\n") + f"\n{line}\n" + fence + after
    else:
        tail = tail.rstrip("\n") + f"\n{line}\n"
    path.write_text(set_log_anchor(head + MARK + tail))


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


def main() -> int:
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

    a = ap.parse_args()
    if not a.cmd:
        ap.print_help()
        return 0
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
