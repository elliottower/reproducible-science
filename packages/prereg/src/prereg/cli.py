"""Preregister your plan to prevent p-hacking and unfalsifiable post-hoc analysis.

    prereg new <name>     scaffold the plan, in OSF's headings
    prereg freeze         record the commit and hash, append to the log
    prereg log <note>     append a line without freezing
    prereg check          has anything above the line changed since the freeze?
    prereg setup          save an OSF token to .env
    prereg register       submit the plan's OSF draft as a registration
    prereg link           create a view-only link on the OSF registration

One file per experiment, one rule: never edit above the line, only append below it.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import pathlib
import re
import sys
from dataclasses import dataclass

from provenance_core import atomic_write, exclusive_lock, hint, shared_lock
from provenance_core.gitref import try_run

from prereg import osf, template
from prereg.confirm import NotConfirmed, confirm
from prereg.log import (
    ACCESS,
    ACCESS_HELP,
    ACCESS_MEANING,
    append,
    log_lines,
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


#: What a plan's directory should not track. A locked write leaves a sidecar beside `PREREG.md`,
#: and `prereg new` wrote no `.gitignore`, so it turned up in the author's repository as an
#: untracked file with no explanation of what had created it.
NEW_GITIGNORE = """\
# Sidecars from provenance_core.locking. They hold nothing: the kernel releases a lock when its
# holder exits, and a leftover temp file means a write was killed partway through.
*.provenance-lock
*.provenance-tmp
"""


def cmd_new(a) -> int:
    d = pathlib.Path(a.name)
    if (d / PREREG).exists():
        print(f"{d / PREREG} already exists")
        return 1
    (d / "tests").mkdir(parents=True, exist_ok=True)
    (d / "results").mkdir(exist_ok=True)
    title = a.title or d.name.replace("_", " ").replace("-", " ")
    (d / PREREG).write_text(template.render(title, today()))
    if not (d / ".gitignore").exists():
        (d / ".gitignore").write_text(NEW_GITIGNORE)
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
    # The plan is read below and written near the end of this function, and `prereg log` appends
    # to the same file. Without a hold across both, a log entry landing between them is erased --
    # and `set_log_anchor` runs over the stale text too, so the surviving chain and its count
    # agree and `check` reports nothing missing. Freeze was bypassing the lock the log itself
    # takes, which is the silent loss that chain exists to make visible.
    with exclusive_lock(path):
        return _freeze_locked(a, path)


def _freeze_locked(a, path: pathlib.Path) -> int:
    """The freeze itself. Assumes the caller holds the lock for `path`."""
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
    # `nothing run` was unconditional, so a rewrite forced after a `results seen` entry logged
    # itself as an amendment directly beneath the line saying the outcomes had been examined.
    # The template calls that column the thing that distinguishes an amendment from a
    # deviation; writing it blind defeated the distinction.
    access = getattr(a, "access", None) or ("nothing run" if not a.force else None)
    if access is None:
        print(f"{path} is being re-frozen, and the log already records what has been seen.")
        print("A forced re-freeze cannot describe itself. Pass --access with one of:")
        for level, why in ACCESS_MEANING.items():
            print(f"  {level:<20} {why}")
        return 1
    # Everything that can refuse runs before anything is written, here or on OSF: a plan whose
    # sections cannot map, a missing attachment, no confirmation or no token. A refusal found
    # after the local freeze left a frozen plan with no draft and no clean way to retry.
    push = None
    if a.osf:
        try:
            push = _prepare_push(path, text, digest, a.attach or [])
        except (RuntimeError, OSError, NotConfirmed) as e:
            print(f"{e}\nNothing was frozen and nothing was sent.")
            return 1
    atomic_write(path, text)
    append(path, today(), f"frozen at {commit[:12]}", access)
    print(f"frozen  {path}")
    print(f"  commit  {commit[:12]}")
    print(f"  sha256  {digest[:16]}…  (of everything above the log)")
    print("\nCommit this. The freeze is only evidence once it is in history.")

    if push:
        try:
            _push(path, push, digest, access)
        except RuntimeError as e:
            print(f"\nOSF push failed: {e}", file=sys.stderr)
            return 1

    return 0


@dataclass(frozen=True)
class Attachment:
    name: str
    content: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


@dataclass(frozen=True)
class Push:
    token: str
    body: dict
    attachments: list[Attachment]


def _prepare_push(path: pathlib.Path, text: str, digest: str, files: list[str]) -> Push:
    """Read the attachments, build the draft and ask for confirmation. Writes nothing.

    The order is the point. The checks that can refuse run first, against OSF's public schema,
    so a plan that cannot map is refused before anyone is asked anything. The token is read
    last, after the phrase: reading a pipe-backed `.env` asks the person to approve, and a
    cancelled command should not have asked.

    The bytes read here are the bytes uploaded and the bytes hashed, so the digest logged is of
    exactly what OSF was sent even if the file changes on disk meanwhile.
    """
    attachments = [Attachment(pathlib.Path(f).name, pathlib.Path(f).read_bytes()) for f in files]
    names = [att.name for att in attachments]
    if len(set(names)) != len(names):
        raise RuntimeError(f"two attachments share a name, and OSF stores them by name: {names}")
    for name in names:
        if "`" in name or not name.isprintable():
            raise RuntimeError(f"{name!r} cannot be written into the log as one entry.")
    body = osf.build_draft(text)
    confirm(
        [
            "Creating a draft registration on OSF and uploading its files.",
            "Nothing is registered until `prereg register`.",
            f"  plan    {body['data']['attributes']['title']}  ({path})",
            f"  sha256  {digest}",
            *(f"  file    {att.name}  sha256 {att.sha256}" for att in attachments),
        ],
        f"push {digest[:12]}",
    )
    return Push(osf.require_token(), body, attachments)


def _push(path: pathlib.Path, push: Push, digest: str, access: str) -> None:
    draft = osf.create_draft(push.body, push.token)
    append(path, today(), osf.draft_event(draft.id, digest), access)
    print(f"\nOSF draft created: {draft.url}")
    if push.attachments and not draft.node_id:
        raise RuntimeError(
            f"OSF did not name the node holding draft {draft.id}'s files, so nothing was attached."
        )
    for att in push.attachments:
        received = osf.upload(draft.node_id or "", att.name, att.content, push.token)
        # A check that can fail: OSF hashes what it received, and a truncated upload or a
        # proxy rewriting line endings would register a different file under the same name.
        if received != att.sha256:
            raise RuntimeError(
                f"OSF holds {att.name} with sha256 {received}, not the {att.sha256} sent."
            )
        append(path, today(), osf.attached_event(att.name, att.sha256), access)
        print(f"  attached  {att.name}  sha256 {att.sha256[:16]}…")
    print("`prereg register` submits it. Registration is irreversible.")


def cmd_log(a) -> int:
    path = find()
    if path is None:
        print(f"no {PREREG} here or above.")
        return 2
    if a.access not in ACCESS:
        print("access must be one of:")
        for level, why in ACCESS_MEANING.items():
            print(f"  {level:<20} {why}")
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
    # Read under a shared lock: a freeze or a log entry in flight would otherwise be read
    # half-written and reported as `CHANGED` or `not frozen`, which is a tampering report against
    # a plan nobody touched.
    with shared_lock(path):
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


def cmd_register(a) -> int:
    """Submit the draft made at the freeze as a registration."""
    path = find()
    if path is None:
        print(f"no {PREREG} here or above.")
        return 2
    # A registration cannot be deleted, so it has to be of the plan that was frozen. `check`
    # already knows every way a plan can differ from its freeze, the log included.
    if check_one(path) != 0:
        print("\nOnly a plan unchanged since its freeze can be registered. Nothing was sent.")
        return 1
    text = path.read_text()
    digest = re.search(r"\*\*Plan sha256:\*\* `([0-9a-f]{64})`", text)
    entries = log_lines(text)
    draft = osf.last(osf.DRAFT_EVENT, entries)
    if draft is None or digest is None:
        print("the log records no OSF draft. `prereg freeze --osf` creates one.")
        return 1
    draft_id = draft.group(1)
    if draft.group(2) != digest.group(1)[:16]:
        # The draft holds the plan as it was pushed. After a forced re-freeze the plan the
        # hash describes is not the one on OSF, and registering would register the old one.
        print(f"OSF draft {draft_id} was made from plan {draft.group(2)}…, and the plan is now")
        print(f"frozen as {digest.group(1)[:16]}…. Push the current freeze with")
        print("`prereg freeze --force --osf --access ...` and register that draft.")
        return 1
    for line in entries:
        done = osf.REGISTRATION_EVENT.search(line)
        if done and done.group(2) == draft_id:
            print(f"OSF draft {draft_id} is already registered as {done.group(1)}.")
            return 1
    embargo = None
    if a.embargo:
        try:
            embargo = datetime.date.fromisoformat(a.embargo)
        except ValueError:
            print(f"--embargo takes a date as YYYY-MM-DD, not {a.embargo!r}.")
            return 1
        if embargo <= datetime.date.today():
            print(f"--embargo {embargo} is not in the future.")
            return 1
    after = entries[entries.index(draft.string) + 1 :]
    files = [m.group(1, 2) for m in map(osf.ATTACHED_EVENT.search, after) if m]
    choice = (
        f"embargo until {embargo} — private until then, public on that date"
        if embargo
        else "immediate — public as soon as it is approved"
    )
    try:
        confirm(
            [
                "Registering on OSF. A registration cannot be deleted.",
                f"  plan    {osf._parse_plan(text)[0]}  ({path})",
                f"  sha256  {digest.group(1)}",
                f"  draft   {draft_id}",
                f"  choice  {choice}",
                *(f"  file    {name}  sha256 {sha}" for name, sha in files),
            ],
            f"register {draft_id}",
        )
        # After the confirmation: reading a pipe-backed token asks the person to approve, and a
        # cancelled command should not have asked.
        reg = osf.register(draft_id, embargo, osf.require_token())
    except (RuntimeError, NotConfirmed) as e:
        print(str(e))
        return 1
    append(path, today(), osf.registration_event(reg, draft_id, embargo), a.access)
    print(f"registered  {reg.url}")
    print("OSF emails every admin; it is pending until they approve or 48 hours pass.")
    print("\nCommit the log. Changes to a registration are made on OSF, not here.")
    return 0


def cmd_link(a) -> int:
    """Create a view-only link on the registration the log records."""
    path = find()
    if path is None:
        print(f"no {PREREG} here or above.")
        return 2
    reg = osf.last(osf.REGISTRATION_EVENT, log_lines(path.read_text()))
    if reg is None:
        print("the log records no OSF registration. `prereg register` creates one.")
        return 1
    if a.name is not None and (not a.name.isprintable() or "`" in a.name):
        print("a link name is one line of plain text.")
        return 1
    reg_id = reg.group(1)
    kind = "anonymous — contributors hidden" if a.anonymous else "named — contributors shown"
    try:
        confirm(
            [
                "Creating a view-only link. Anyone holding it can open the registration,",
                "including while it is embargoed.",
                f"  registration  {reg_id}",
                f"  kind          {kind}",
                f"  name          {a.name or '(OSF default)'}",
            ],
            f"link {reg_id}",
        )
        link = osf.view_only_link(reg_id, a.anonymous, a.name, osf.require_token())
    except (RuntimeError, NotConfirmed) as e:
        print(str(e))
        return 1
    append(path, today(), osf.link_event(link, reg_id, a.anonymous), a.access)
    print(link.url)
    print("\nThe log records the link's id, not its key: the key opens the registration.")
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
        choices=ACCESS,
        metavar="LEVEL",
        help="required with --force. " + ACCESS_HELP,
    )
    f.add_argument("--osf", action="store_true", help="push as a draft registration to OSF")
    f.add_argument(
        "--attach",
        action="append",
        metavar="PATH",
        help="with --osf: upload this file into the draft, so it is registered with the plan",
    )
    f.set_defaults(fn=cmd_freeze)

    lg = sub.add_parser("log", help="append a line")
    lg.add_argument("note")
    # Validated in `cmd_log` rather than by argparse: `choices` makes an unknown level exit 2,
    # which this CLI documents as "could not measure". A bad argument is a refusal, which is 1.
    lg.add_argument("--access", default="no results seen", metavar="LEVEL", help=ACCESS_HELP)
    lg.set_defaults(fn=cmd_log)

    s = sub.add_parser("setup", help="save OSF token to .env")
    s.set_defaults(fn=cmd_setup)

    c = sub.add_parser("check", help="has the plan changed since the freeze?")
    c.set_defaults(fn=cmd_check)

    r = sub.add_parser("register", help="submit the plan's OSF draft as a registration")
    # No default. An immediate registration is public, and a default either way decides for
    # the author whether their plan is published today.
    when = r.add_mutually_exclusive_group(required=True)
    when.add_argument("--embargo", metavar="YYYY-MM-DD", help="private until this date")
    when.add_argument("--immediate", action="store_true", help="public once approved")
    r.add_argument("--access", required=True, choices=ACCESS, help="what had been seen")
    r.set_defaults(fn=cmd_register)

    lk = sub.add_parser("link", help="create a view-only link on the OSF registration")
    lk.add_argument("--anonymous", action="store_true", help="hide contributors, for blind review")
    lk.add_argument("--name", help="the link's name on OSF")
    lk.add_argument("--access", required=True, choices=ACCESS, help="what had been seen")
    lk.set_defaults(fn=cmd_link)

    a = ap.parse_args(argv)
    if getattr(a, "attach", None) and not a.osf:
        ap.error("--attach uploads into the OSF draft, so it needs --osf")
    if not a.cmd:
        ap.print_help()
        return 0
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
