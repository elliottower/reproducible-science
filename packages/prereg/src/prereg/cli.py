"""Preregister your plan to prevent p-hacking and unfalsifiable post-hoc analysis.

    prereg new <name>     scaffold the plan, in OSF's headings
    prereg freeze         record the commit and hash, append to the log
    prereg log <note>     append a line without freezing
    prereg check          has anything above the line changed since the freeze?
    prereg timestamp      complete the freeze's outside timestamp, and check it against Bitcoin
    prereg setup          save an OSF token to .env
    prereg register       submit the plan's OSF draft as a registration (--all: every plan)
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

from provenance_core import (
    anchor,
    atomic_write,
    atomic_write_bytes,
    exclusive_lock,
    hint,
    shared_lock,
)
from provenance_core.gitref import try_run

from prereg import osf, pinned, template
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


FROZEN_DIGEST = re.compile(r"\*\*Plan sha256:\*\* `([0-9a-f]{64})`")


def proof_path(path: pathlib.Path) -> pathlib.Path:
    """Where a plan's timestamp proof is kept: `PREREG.md.ots`, the name `ots` itself would use."""
    return path.with_name(path.name + ".ots")


def _stamp(path: pathlib.Path, digest: str) -> None:
    """Send the freeze's digest to the calendars and keep the proof beside the plan.

    A freeze that cannot be stamped is still a freeze, so a failure here is reported and never
    undoes it. A proof of an earlier freeze is kept under its digest rather than overwritten: it
    dates the plan as it was then, which a forced re-freeze does not make untrue.
    """
    proof = proof_path(path)
    if proof.exists():
        try:
            anchor.status(proof.read_bytes(), digest)
            return
        except anchor.AnchorError:
            earlier = anchor.proved_digest(proof.read_bytes())[:16]
            proof.rename(path.with_name(f"{path.name}.{earlier}.ots"))
    try:
        atomic_write_bytes(proof, anchor.stamp(digest))
    except anchor.AnchorError as e:
        print(f"\nnot timestamped: {e}")
        print("`prereg timestamp` stamps it once the calendars can be reached.")
        return
    print(f"  timestamp  {proof.name}, pending until Bitcoin confirms it, usually within hours")
    print("             `prereg timestamp` then completes the proof. Commit it with the plan.")


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
            push = _prepare_push(text, a.attach or [], _metadata_args(a))
        except (RuntimeError, OSError) as e:
            print(f"{e}\nNothing was frozen and nothing was sent.")
            return 1
    atomic_write(path, text)
    append(path, today(), f"frozen at {commit[:12]}", access)
    print(f"frozen  {path}")
    print(f"  commit  {commit[:12]}")
    print(f"  sha256  {digest[:16]}…  (of everything above the log)")
    if not a.no_timestamp:
        _stamp(path, digest)
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
    metadata: osf.Metadata


@dataclass(frozen=True)
class MetadataArgs:
    title_prefix: str
    description: str
    tags: list[str]
    category: str
    license: str
    copyright_holders: list[str]
    subjects: list[str]


def _metadata_args(a) -> MetadataArgs:
    return MetadataArgs(
        title_prefix=a.title_prefix or "",
        description=a.description or "",
        tags=a.tag or [],
        category=a.category or "",
        license=a.license,
        copyright_holders=a.copyright_holder or [],
        subjects=a.subject or [],
    )


def _prepare_push(text: str, files: list[str], m: MetadataArgs) -> Push:
    """Read the attachments, build the draft and resolve its metadata. Writes nothing.

    Every check that can refuse runs here, before the local freeze: a plan that cannot map, a
    subject or license OSF does not have, a missing attachment, no token. A refusal found after
    the freeze left a frozen plan with no draft and no clean way to retry.

    There is no typed confirmation. A draft is private to its author and can be deleted, and a
    phrase asked five times for five plans was a cost paid on the step that risks nothing. The
    phrase guards `register`, which cannot be undone.

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
    if m.category and m.category not in osf.CATEGORIES:
        raise RuntimeError(
            f"{m.category!r} is not an OSF category. One of: {', '.join(osf.CATEGORIES)}."
        )
    token = osf.require_token()
    title = body["data"]["attributes"]["title"]
    holders = m.copyright_holders
    meta = osf.Metadata(
        # Always sent: OSF ignores the title in the POST that creates the draft, so without it
        # here every draft pushed with no prefix came back titled "".
        title=m.title_prefix + title,
        description=m.description,
        tags=tuple(m.tags),
        category=m.category,
        license_id=osf.find_license(m.license, token) if holders else None,
        license_name=m.license if holders else None,
        year=today()[:4],
        copyright_holders=tuple(holders),
        subject_ids=tuple(osf.find_subjects(m.subjects, token)),
        subject_names=tuple(m.subjects),
    )
    return Push(token, body, attachments, meta)


def _push(path: pathlib.Path, push: Push, digest: str, access: str) -> None:
    draft = osf.create_draft(push.body, push.token)
    append(path, today(), osf.draft_event(draft.id, digest), access)
    print(f"\nOSF draft created: https://osf.io/registries/drafts/{draft.id}/")
    osf.set_metadata(draft.id, push.metadata, push.token)
    meta = push.metadata
    if meta.subject_names:
        print(f"  subjects  {', '.join(meta.subject_names)}")
    else:
        print("  no subject: OSF refuses to register a draft without one. Add one on the")
        print("  draft's Metadata page, or push with --subject.")
    if meta.license_name:
        print(f"  license   {meta.license_name}, {meta.year} {', '.join(meta.copyright_holders)}")
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
        # Here and not in `cmd_check`, which printed it after every failure: beneath `LOG
        # ALTERED` it told the author the plan had been edited when the plan hash matched.
        print("  the plan was edited after freezing: restore it and record the change in the log")
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
    return _report_timestamp(path, m.group(1))


def _report_timestamp(path: pathlib.Path, digest: str) -> int:
    """One line on the freeze's outside timestamp, read from the proof with no network.

    A proof of another digest fails the check: it would otherwise lend this freeze the date of a
    plan that is not this one. A missing proof does not fail it, because every plan frozen before
    timestamps existed has none.
    """
    proof = proof_path(path)
    if not proof.exists():
        print("  timestamp  none. `prereg timestamp` makes one.")
        return 0
    try:
        found = anchor.status(proof.read_bytes(), digest)
    except anchor.AnchorError as e:
        print(f"TIMESTAMP    {path}")
        print(f"  - {proof.name}: {e}")
        return 1
    if found.is_complete:
        print(f"  timestamp  Bitcoin block {found.blocks[0]}. `prereg timestamp` checks the block.")
    else:
        print(
            f"  timestamp  pending at {len(found.pending)} calendars. `prereg timestamp` completes it."
        )
    return 0


@dataclass(frozen=True)
class Registrable:
    path: pathlib.Path
    title: str
    digest: str
    draft_id: str
    files: list[tuple[str, str]]


def _registrable(path: pathlib.Path) -> Registrable | str:
    """The draft this plan's log recorded at its freeze, or why it cannot be registered."""
    # A registration cannot be deleted, so it has to be of the plan that was frozen. `check`
    # already knows every way a plan can differ from its freeze, the log included.
    if check_one(path) != 0:
        return "only a plan unchanged since its freeze can be registered"
    text = path.read_text()
    digest = re.search(r"\*\*Plan sha256:\*\* `([0-9a-f]{64})`", text)
    entries = log_lines(text)
    draft = osf.last(osf.DRAFT_EVENT, entries)
    if draft is None or digest is None:
        return "the log records no OSF draft. `prereg freeze --osf` creates one"
    draft_id = draft.group(1)
    if draft.group(2) != digest.group(1)[:16]:
        # The draft holds the plan as it was pushed. After a forced re-freeze the plan the
        # hash describes is not the one on OSF, and registering would register the old one.
        return (
            f"OSF draft {draft_id} was made from plan {draft.group(2)}…, and the plan is now "
            f"frozen as {digest.group(1)[:16]}…. Push the current freeze with "
            "`prereg freeze --force --osf --access ...` and register that draft"
        )
    for line in entries:
        done = osf.REGISTRATION_EVENT.search(line)
        if done and done.group(2) == draft_id:
            return f"OSF draft {draft_id} is already registered as {done.group(1)}"
    after = entries[entries.index(draft.string) + 1 :]
    files = [(m.group(1), m.group(2)) for m in map(osf.ATTACHED_EVENT.search, after) if m]
    return Registrable(path, osf._parse_plan(text)[0], digest.group(1), draft_id, files)


def cmd_register(a) -> int:
    """Submit the drafts made at the freeze as registrations, after one typed phrase.

    With `--all`, or run where no plan governs, every plan below is registered: one phrase
    naming the whole list, so five plans are five registrations and one confirmation. Every
    plan is checked before anyone is asked, and one that cannot be registered stops the batch,
    except a plan already registered, which is skipped so a batch interrupted partway can be
    run again.
    """
    path = None if a.all else find()
    if path is not None:
        paths = [path]
    else:
        paths = sorted(pathlib.Path.cwd().rglob(PREREG))
        if not paths:
            print(f"no {PREREG} here, above, or below.")
            return 2
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

    todo: list[Registrable] = []
    for p in paths:
        r = _registrable(p)
        if isinstance(r, Registrable):
            todo.append(r)
        elif len(paths) > 1 and "is already registered" in r:
            print(f"skipped      {p}: {r}.")
        else:
            print(f"\n{p}: {r}. Nothing was sent.")
            return 1
    if not todo:
        print("\nEvery plan here is already registered. Nothing was sent.")
        return 1

    choice = (
        f"embargo until {embargo} — private until then, public on that date"
        if embargo
        else "immediate — public as soon as it is approved"
    )
    lines = [
        f"Registering {len(todo)} plan{'s' if len(todo) > 1 else ''} on OSF. "
        "A registration cannot be deleted.",
        f"  choice  {choice}",
    ]
    for r in todo:
        lines += [
            "",
            f"  plan    {r.title}  ({r.path})",
            f"  sha256  {r.digest}",
            f"  draft   {r.draft_id}",
            *(f"  file    {name}  sha256 {sha}" for name, sha in r.files),
        ]
    if len(todo) == 1:
        phrase = f"register {todo[0].draft_id}"
    else:
        # A phrase that names the list: typing it confirms these drafts and no others.
        ids = ",".join(r.draft_id for r in todo)
        phrase = f"register {len(todo)} plans {hashlib.sha256(ids.encode()).hexdigest()[:8]}"
    try:
        confirm(lines, phrase)
        # After the confirmation: reading a pipe-backed token asks the person to approve, and a
        # cancelled command should not have asked.
        token = osf.require_token()
    except (RuntimeError, NotConfirmed) as e:
        print(str(e))
        return 1
    failed = 0
    for r in todo:
        try:
            reg = osf.register(r.draft_id, embargo, token)
        except RuntimeError as e:
            print(f"\n{r.path}: {e}")
            failed += 1
            continue
        append(r.path, today(), osf.registration_event(reg, r.draft_id, embargo), a.access)
        note = "  (OSF reported an error; found registered)" if reg.recovered_from else ""
        print(f"registered  {reg.url}  {r.path}{note}")
    print("OSF emails every admin; each is pending until they approve or 48 hours pass.")
    print("\nCommit the log. Changes to a registration are made on OSF, not here.")
    return 1 if failed else 0


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

    Registrations frozen by a commit line are checked as well, wherever git tracks them below
    here: a study registered under that convention has no `PREREG.md`, and reported nothing.
    """
    path = find()
    documents = pinned.check_below(pathlib.Path.cwd())
    if path is not None:
        rc = check_one(path)
        if rc == 2:
            print("\nNothing to check against yet. `prereg freeze` records the hash.")
        return _report_pinned(documents, rc)

    found = sorted(pathlib.Path.cwd().rglob(PREREG))
    if not found:
        if not documents:
            print(f"no {PREREG} here, above, or below.")
            return 2
        return _report_pinned(documents, 0)

    codes = [check_one(f) for f in found]
    changed = codes.count(1)
    print(
        f"\n{len(found)} plans: {codes.count(0)} unchanged, {changed} changed, "
        f"{codes.count(2)} not frozen"
    )
    # No summary of what a changed plan means: `check_one` has said, per plan, whether the plan,
    # an uncovered line or the log is what differs, and one sentence for all three was wrong for
    # two of them.
    # The single-plan branch returns 2 for a plan that was never frozen; this one returned 0,
    # so whether an unfrozen registration passed CI depended on which directory it ran from.
    return _report_pinned(documents, 1 if (changed or codes.count(2)) else 0)


def _report_pinned(documents: list[pinned.Pinned], rc: int) -> int:
    """List the commit-pinned documents under their own heading, and fold them into the exit code.

    A changed document is a finding, as a changed plan is. One whose commit line names no commit,
    or names one this repository does not hold, was not compared: it exits 2 unless something
    else changed, and the summary counts it, because a check that could not run is not a pass.
    """
    if not documents:
        return rc
    print("\nregistrations frozen by a commit line:")
    for d in documents:
        label = "CHANGED" if d.status == pinned.CHANGED else d.status
        at = f"  at {d.commit}" if d.commit else ""
        print(f"{label:<12} {d.path}{at}")
        for line in d.detail:
            print(f"  {line}")
    statuses = [d.status for d in documents]
    print(
        f"\n{len(documents)} commit-pinned: "
        + ", ".join(
            f"{statuses.count(s)} {s}"
            for s in (
                pinned.UNCHANGED,
                pinned.APPENDED,
                pinned.CHANGED,
                pinned.PENDING,
                pinned.UNKNOWN,
            )
        )
    )
    if rc == 1 or pinned.CHANGED in statuses:
        return 1
    if rc == 2 or pinned.PENDING in statuses or pinned.UNKNOWN in statuses:
        return 2
    return 0


def timestamp_one(path: pathlib.Path) -> int:
    """Stamp, complete or check one plan's timestamp. 0 dated, 1 failed, 2 nothing to date yet."""
    with shared_lock(path):
        m = FROZEN_DIGEST.search(path.read_text())
    if not m:
        print(f"not frozen   {path}")
        return 2
    digest, proof = m.group(1), proof_path(path)
    if not proof.exists():
        try:
            atomic_write_bytes(proof, anchor.stamp(digest))
        except anchor.AnchorError as e:
            print(f"NOT STAMPED  {path}\n  - {e}")
            return 1
        print(f"stamped      {path}\n  pending until Bitcoin confirms it, usually within hours.")
        return 2
    try:
        data = anchor.upgrade(proof.read_bytes(), digest)
        found = anchor.status(data, digest)
        if data != proof.read_bytes():
            atomic_write_bytes(proof, data)
        block = anchor.confirm(data, digest) if found.is_complete else None
    except anchor.AnchorError as e:
        print(f"TIMESTAMP    {path}\n  - {e}")
        return 1
    if block is None:
        print(
            f"pending      {path}\n  at {len(found.pending)} calendars; try again in a few hours."
        )
        return 2
    print(f"timestamped  {path}")
    print(f"  Bitcoin block {block.height}, {block.time:%Y-%m-%d %H:%M} UTC")
    print("  The plan existed in this form by then. Commit the proof if it changed.")
    return 0


def cmd_timestamp(a) -> int:
    """Timestamp the governing plan, or every plan below when there is none, as `check` does."""
    path = find()
    paths = [path] if path is not None else sorted(pathlib.Path.cwd().rglob(PREREG))
    if not paths:
        print(f"no {PREREG} here, above, or below.")
        return 2
    codes = [timestamp_one(p) for p in paths]
    return 1 if 1 in codes else (2 if 2 in codes else 0)


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
    f.add_argument(
        "--no-timestamp",
        action="store_true",
        help="do not send the plan's digest to the OpenTimestamps calendars",
    )
    f.add_argument("--osf", action="store_true", help="push as a draft registration to OSF")
    f.add_argument(
        "--attach",
        action="append",
        metavar="PATH",
        help="with --osf: upload this file into the draft, so it is registered with the plan",
    )
    # The draft's Metadata page. OSF needs a subject to register; the rest is optional.
    f.add_argument(
        "--subject", action="append", metavar="TEXT", help="with --osf: an OSF subject, by name"
    )
    f.add_argument("--description", metavar="TEXT", help="with --osf: the draft's description")
    f.add_argument("--tag", action="append", metavar="TEXT", help="with --osf: a tag")
    f.add_argument("--category", metavar="NAME", help="with --osf: an OSF category")
    f.add_argument(
        "--copyright-holder",
        action="append",
        metavar="NAME",
        help="with --osf: sets the license, with this holder and the current year",
    )
    f.add_argument(
        "--license",
        default=osf.DEFAULT_LICENSE,
        metavar="NAME",
        help=f"with --copyright-holder: an OSF license by name (default {osf.DEFAULT_LICENSE})",
    )
    f.add_argument(
        "--title-prefix", metavar="TEXT", help="with --osf: put before the plan's title on OSF"
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

    t = sub.add_parser(
        "timestamp", help="complete the freeze's outside timestamp and check it against Bitcoin"
    )
    t.set_defaults(fn=cmd_timestamp)

    r = sub.add_parser("register", help="submit the plan's OSF draft as a registration")
    # No default. An immediate registration is public, and a default either way decides for
    # the author whether their plan is published today.
    when = r.add_mutually_exclusive_group(required=True)
    when.add_argument("--embargo", metavar="YYYY-MM-DD", help="private until this date")
    when.add_argument("--immediate", action="store_true", help="public once approved")
    r.add_argument("--access", required=True, choices=ACCESS, help="what had been seen")
    r.add_argument(
        "--all", action="store_true", help="every frozen plan below here, after one phrase"
    )
    r.set_defaults(fn=cmd_register)

    lk = sub.add_parser("link", help="create a view-only link on the OSF registration")
    lk.add_argument("--anonymous", action="store_true", help="hide contributors, for blind review")
    lk.add_argument("--name", help="the link's name on OSF")
    lk.add_argument("--access", required=True, choices=ACCESS, help="what had been seen")
    lk.set_defaults(fn=cmd_link)

    a = ap.parse_args(argv)
    if a.cmd == "freeze" and not a.osf:
        for flag in (
            "attach",
            "subject",
            "description",
            "tag",
            "category",
            "copyright_holder",
            "title_prefix",
        ):
            if getattr(a, flag):
                ap.error(f"--{flag.replace('_', '-')} describes the OSF draft, so it needs --osf")
    if not a.cmd:
        ap.print_help()
        return 0
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
