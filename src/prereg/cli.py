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

from prereg import template

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
    keep = [ln for ln in plan.splitlines()
            if not ln.startswith(("**Status:**", "**Plan sha256:**", "**Frozen:**"))]
    return "\n".join(keep).strip() + "\n"


def sha256_of(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


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
    block = (f"**Status:** FROZEN at `{commit[:12]}`\n"
             f"**Plan sha256:** `{digest}`\n"
             f"**Frozen:** {date}")
    if note:
        block += f"\n{note}"
    return text[:m.start()] + block + text[m.end():]


def append(path: pathlib.Path, date: str, event: str, access: str) -> None:
    text = path.read_text()
    if MARK not in text:
        text += MARK.rstrip("\n") + "\n\n```\n```\n"
    head, _, tail = text.partition(MARK)
    line = f"{date}  {event:<36}{access}"
    if "```" in tail:
        before, fence, after = tail.rpartition("```")
        tail = before.rstrip("\n") + f"\n{line}\n" + fence + after
    else:
        tail = tail.rstrip("\n") + f"\n{line}\n"
    path.write_text(head + MARK + tail)


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
    print(f"  tests/  results/")
    print("\nfill it in, then `prereg freeze`. Never edit above the log line afterwards.")
    return 0


def cmd_freeze(a) -> int:
    path = find()
    if path is None:
        print(f"no {PREREG} here or above. `prereg new <name>` makes one.")
        return 2
    text = path.read_text()
    if "**Status:** DRAFT" not in text and not a.force:
        print(f"{path} is already frozen. Use `prereg log` to append, or --force.")
        return 1

    repo = path.parent
    dirty = git("status", "--porcelain", str(path), cwd=repo)
    if dirty and not a.force:
        print(f"{path} has uncommitted changes. Commit first — the freeze names a commit.")
        return 1

    commit = git("rev-parse", "HEAD", cwd=repo) or "(not in a git repository)"
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
    append(path, today(), f"frozen at {commit[:12]}", "nothing run")
    print(f"frozen  {path}")
    print(f"  commit  {commit[:12]}")
    print(f"  sha256  {digest[:16]}…  (of everything above the log)")
    print("\nCommit this. The freeze is only evidence once it is in history.")
    return 0


def cmd_log(a) -> int:
    path = find()
    if path is None:
        print(f"no {PREREG} here or above.")
        return 2
    if a.access not in ACCESS:
        print(f"access must be one of: {', '.join(ACCESS)}")
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
    now = sha256_of(plan_of(text))
    if now == m.group(1):
        print(f"unchanged    {path}")
        return 0
    print(f"CHANGED      {path}")
    print(f"  frozen  {m.group(1)[:16]}…")
    print(f"  now     {now[:16]}…")
    return 1


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
            print("\nThe plan was edited after freezing. Restore it and record the change in the log.")
        elif rc == 2:
            print("\nNothing to check against yet. `prereg freeze` records the hash.")
        return rc

    found = sorted(pathlib.Path.cwd().rglob(PREREG))
    if not found:
        print(f"no {PREREG} here, above, or below.")
        return 2

    codes = [check_one(f) for f in found]
    changed = codes.count(1)
    print(f"\n{len(found)} plans: {codes.count(0)} unchanged, {changed} changed, "
          f"{codes.count(2)} not frozen")
    if changed:
        print("A changed plan was edited after freezing. Restore it and record the change.")
    return 1 if changed else 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="prereg", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd")

    n = sub.add_parser("new", help="scaffold a plan")
    n.add_argument("name")
    n.add_argument("--title")
    n.set_defaults(fn=cmd_new)

    f = sub.add_parser("freeze", help="record the commit and hash")
    f.add_argument("--force", action="store_true")
    f.set_defaults(fn=cmd_freeze)

    lg = sub.add_parser("log", help="append a line")
    lg.add_argument("note")
    lg.add_argument("--access", default="no results seen",
                    help=f"one of: {', '.join(ACCESS)}")
    lg.set_defaults(fn=cmd_log)

    c = sub.add_parser("check", help="has the plan changed since the freeze?")
    c.set_defaults(fn=cmd_check)

    a = ap.parse_args()
    if not a.cmd:
        ap.print_help()
        return 0
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
