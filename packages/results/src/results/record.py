"""The commands that put an event in the ledger.

`init`, `seal`, `access`, `run`, `retire`, `claim`, `review` and `annotate` share a shape:
find the governing `.results/`, build one event, append it, and report what was written. What
separates them is the refusal each makes first -- a path that is not a file, an access level
outside the four, a run id already in use, a path retired that no seal or run recorded, a
confirmatory claim resting on a run recorded after the outcomes were seen, a review with a
verdict outside the four, an annotation whose kind is not `namespace:type`.

Each returns the process's exit code. `cli.py` unpacks the argparse namespace and calls in.
"""

from __future__ import annotations

import os
import pathlib
import re

from provenance_core import SIDECAR_SUFFIXES, sha256_of_tree

from results import freezes, history, ledger, outputs, timeline
from results.manuscript import readable
from results.paths import RESULTS_DIR, ledger_own, ledger_path, record_path, require_root

ACCESS_LEVELS = [
    "nothing seen",
    "metadata only",
    "structure seen",
    "outcomes seen",
]

VERDICTS = ["pass", "fail", "partial", "uncertain"]

#: What an annotation's target is, as `namespace:type`: `wandb:artifact`, `doi:dataset`,
#: `osf:node`, `url:page`. Open-ended, because the outside systems a project links to are not
#: this tool's to enumerate; only the shape is fixed, so that a reader can group by namespace.
KIND = re.compile(r"[a-z0-9._-]+:[a-z0-9._-]+")

#: A digest as the outside system states it: `algorithm:hex`.
DIGEST = re.compile(r"([a-z0-9][a-z0-9_-]*):([0-9a-fA-F]+)")

#: Hex digits in the digests whose length is fixed. Any other algorithm is taken at any length.
DIGEST_LENGTHS = {"md5": 32, "sha1": 40, "sha256": 64, "sha512": 128}

#: Written into every annotation and printed wherever one is shown.
LINKED = "linked, not checked"


#: Written into `.results/` so the ledger is tracked without anyone editing the project's own
#: ignore file. The ledger and its anchor are the record a claim appeals to, and one that exists
#: on a single disk cannot be appealed to by anyone else; only the lock sidecars are ignored.
GITIGNORE = """\
# Commit ledger.jsonl and ledger.head: a record is evidence once it is in history.
# Everything in the ledger becomes public with the repository, notes included.

# Lock sidecars. They hold nothing; the kernel releases a lock when its holder exits.
*.lock
*.provenance-lock
*.provenance-tmp
"""


def init() -> int:
    d = pathlib.Path.cwd() / RESULTS_DIR
    if d.exists():
        print(f"{d} already exists.")
        return 1
    d.mkdir()
    lp = d / ledger.LEDGER
    lp.touch()
    ledger.append_event(lp, {"event": "init"})
    (d / ".gitignore").write_text(GITIGNORE)
    print(f"created {RESULTS_DIR}/")
    print(f"  {ledger.LEDGER}   append-only event log")
    print("  .gitignore     ignores the lock files only, so the ledger is committed")
    print("\nseal your inputs before running: `results seal prereg.md script.py data.csv`")
    return 0


def own_files(p: pathlib.Path, root: pathlib.Path) -> str | None:
    """Why `p` cannot be sealed or recorded as an output, where it is or holds the ledger's own
    files; None where it is neither.

    The ledger, its anchor `ledger.head` and the timestamp proofs change with every event, so a
    seal of one is out of date at the next command and `verify --files` would report it as
    changed for good. A directory holding `.results/` has the same defect through its digest.
    """
    if ledger_own(record_path(p, root)):
        return "is one of the ledger's own files, which change with every event"
    if p.is_dir() and root.resolve().is_relative_to(p):
        return f"holds {RESULTS_DIR}/, whose files change with every event"
    return None


def seal(files: list[str], role: str) -> int:
    root = require_root()
    lp = ledger_path(root)
    # A sealed entry holds a path and digest, a kind, a file count for a tree, and the names a
    # tree digest did not cover. Declared once so writing and reading it agree.
    sealed: list[dict[str, str | int | list[str]]] = []
    for name in files:
        p = pathlib.Path(name).resolve()
        if refusal := own_files(p, root):
            print(f"not sealed: {name} {refusal}")
            print("nothing was written. Seal the files the work reads and writes.")
            return 1
        if p.is_dir():
            # A dataset is a directory. Sealing it meant naming every file, and a file added
            # afterwards was then simply absent from the record with nothing to notice -- a seal
            # that looks complete and is not. The digest covers relative paths as well as
            # contents, so a rename inside the tree changes it.
            digest, covered, skipped = sha256_of_tree(p)
            # Annotated, because the literal alone infers `dict[str, str | int]` and the
            # skipped list below is neither.
            entry: dict[str, str | int | list[str]] = {
                "path": record_path(p, root),
                "sha256": digest,
                "kind": "tree",
                "files": len(covered),
            }
            # What the digest did not cover, on the record. A seal that quietly ignored
            # something means a different thing on the next machine, and the reader cannot see
            # the boundary unless it is written down.
            if skipped:
                entry["skipped"] = skipped
            sealed.append(entry)
            continue
        if not p.is_file():
            print(f"not a file: {name}")
            return 1
        digest = ledger.sha256_of_file(p)
        sealed.append({"path": record_path(p, root), "sha256": digest, "kind": "file"})
    ledger.append_event(
        lp,
        {
            "event": "seal",
            "role": role,
            "files": sealed,
        },
    )
    # A sealed entry's values are heterogeneous because the ledger carries them that way, so
    # each read narrows rather than the type widening to fit the loosest use.
    trees = [e for e in sealed if e.get("kind") == "tree"]
    within = sum(n for e in trees if isinstance(n := e.get("files"), int))
    what = (
        f"{len(sealed)} file(s)"
        if not trees
        else f"{len(sealed) - len(trees)} file(s) and {len(trees)} tree(s) "
        f"covering {within} file(s)"
    )
    print(f"sealed {what} as {role}")
    for entry in sealed:
        print(f"  {str(entry['sha256'])[:16]}…  {entry['path']}")
        # Recorded in the event and said nowhere, so a symlink to data outside the tree, or a
        # cache directory, sat outside a seal its author read as covering the directory.
        for line in skipped_lines(entry.get("skipped"), root.parent / str(entry["path"])):
            print(line)
    return 0


#: Skipped names listed when a tree is sealed or verified; the ledger holds all of them.
SHOWN_SKIPPED = 10

#: Names skipped that are filesystem droppings and nothing else, never worth a warning.
DROPPINGS = (".DS_Store", "Thumbs.db")


def skipped_lines(skipped: object, tree: pathlib.Path) -> list[str]:
    """A warning naming what a tree digest did not cover and why, or nothing.

    A symlink is not followed and a cache directory is not read, so a dataset whose files are
    symlinks into a store elsewhere seals as an empty tree, and nothing said so. `.DS_Store`
    and its kind are left unsaid: they differ between two checkouts of the same data.
    """
    if not isinstance(skipped, list):
        return []
    notable = [
        str(name)
        for name in skipped
        if not str(name).endswith(DROPPINGS) and not str(name).endswith(tuple(SIDECAR_SUFFIXES))
    ]
    if not notable:
        return []
    lines = [f"    warning: {len(notable)} name(s) the digest does not cover:"]
    for name in notable[:SHOWN_SKIPPED]:
        why = "a symlink, not followed" if (tree / name).is_symlink() else "a cache directory"
        lines.append(f"      {name}  ({why})")
    if len(notable) > SHOWN_SKIPPED:
        lines.append(f"      ... and {len(notable) - SHOWN_SKIPPED} more, listed in the ledger")
    return lines


def access(note: str, level: str) -> int:
    root = require_root()
    lp = ledger_path(root)
    if level not in ACCESS_LEVELS:
        print(f"level must be one of: {', '.join(ACCESS_LEVELS)}")
        return 1
    ledger.append_event(
        lp,
        {
            "event": "access",
            "level": level,
            "note": note,
        },
    )
    print(f"recorded: {level} — {note}")
    if level == "outcomes seen":
        print("\nany analysis registered after this is retrospective, not confirmatory.")
        print("`results claim --confirmatory` will now refuse runs recorded after this point.")
    return 0


#: What a run's outputs can be declared to hold where they hold no outcome. A run recorded
#: without one is taken to hold results, which is what a run meant before the field existed.
RUN_HOLDS = ["metadata only", "structure seen"]


def run(
    files: list[str],
    run_id: str,
    note: str | None,
    anyway: bool,
    holds: str | None = None,
    strict: bool = False,
) -> int:
    if holds is not None and holds not in RUN_HOLDS:
        print(f"--holds must be one of: {', '.join(RUN_HOLDS)}")
        print("a run whose outputs hold outcomes is recorded without --holds.")
        return 1
    root = require_root()
    lp = ledger_path(root)
    existing = ledger.read_ledger(lp)
    existing_ids = {e["run_id"] for e in existing if e.get("event") == "run"}
    if run_id in existing_ids and not anyway:
        # A warning was not enough: both the claim-time refusal and `verify`'s contested list
        # resolve an id to one timestamp, so two runs sharing an id let a claim rest on the
        # earlier of them. Typing the same id twice defeated the confirmatory guard.
        print(f"run id '{run_id}' already exists in the ledger.")
        print("one run id names one run: choose another, or pass --anyway to record both")
        print("and accept that a claim naming this id is ordered by the later run.")
        return 1
    written = []
    for name in files:
        p = pathlib.Path(name).resolve()
        if refusal := own_files(p, root):
            print(f"not recorded: {name} {refusal}")
            print("nothing was written. Record the files the run wrote.")
            return 1
        if not p.is_file():
            print(f"not a file: {name}")
            return 1
        digest = ledger.sha256_of_file(p)
        path = record_path(p, root)
        if (earlier := rerecorded(existing, path, digest)) is not None:
            # An output edited by hand and then recorded again, under the same id with
            # `--anyway` or under a new one, read as an honest re-run: verify said RESEALED
            # and passed. A re-run is a run of its inputs, and the ledger shows one as a seal.
            # A warning by default, since iterating under new ids is ordinary; `--strict`
            # refuses, as `verify --strict` fails it.
            print(
                f"{'not recorded' if strict else 'warning'}: {name} was recorded by run "
                f"'{earlier}' with other bytes, and no input of that run has been sealed since."
            )
            print("  a re-run reads its inputs: seal them before recording what it wrote")
            print("  (`results seal <script> <data>`), or write the new version to a new file.")
            if strict:
                print("nothing was written.")
                return 1
            print("  `results verify` reports it as RERECORDED.")
        written.append({"path": path, "sha256": digest})
    event = {
        "event": "run",
        "run_id": run_id,
        "outputs": written,
        "note": note or "",
    }
    if holds is not None:
        # Written with the run and never afterwards: no command labels a run already recorded,
        # so the declaration is in the chain before anything that reads it.
        event["holds"] = holds
    ledger.append_event(lp, event)
    print(f"run {run_id}: {len(written)} output(s){f', holding {holds}' if holds else ''}")
    for o in written:
        print(f"  {o['sha256'][:16]}…  {o['path']}")
    return 0


def rerecorded_paths(events: list[dict]) -> dict[str, tuple[str, str]]:
    """Each path a run recorded as an output under other bytes than an earlier run recorded
    there, with no input of the earlier run sealed again between the two, and the two runs.
    Where a path was re-recorded more than once, the latest pair: keeping the first made every
    later re-record of the path silent at `results run`.

    What separates a re-run from an output edited and recorded again is that a re-run reads
    its inputs, and an input the ledger knows is a seal. The inputs of a run are the paths
    sealed before it was recorded, and a seal of one of them after it, with bytes other than
    its previous seal held, is the record of a re-run.
    A seal of anything else is not: sealing an unrelated file cleared the check. A retirement
    in between makes the later bytes new rather than a re-record.
    """
    sealed: dict[str, str] = {}
    last: dict[str, tuple[str, str, frozenset[str]]] = {}
    refreshed: set[str] = set()
    found: dict[str, tuple[str, str]] = {}
    for e in events:
        kind = e.get("event")
        if kind == "seal":
            files = {f.get("path", ""): f.get("sha256", "") for f in e.get("files", [])}
            # A seal of an input with the bytes it already had records no change to what the
            # run reads, so it is no record of a re-run.
            now = {path for path, digest in files.items() if sealed.get(path) != digest}
            refreshed |= {path for path, (_, _, inputs) in last.items() if now & inputs}
            sealed |= files
        elif kind == "retire":
            for path in e.get("paths", []):
                last.pop(path, None)
        elif kind == "run":
            run_id = str(e.get("run_id", ""))
            for o in e.get("outputs", []):
                path, digest = o.get("path", ""), o.get("sha256", "")
                if path in last and last[path][1] != digest and path not in refreshed:
                    found[path] = (last[path][0], run_id)
                last[path] = (run_id, digest, frozenset(set(sealed) - {path}))
                refreshed.discard(path)
    return found


def rerecorded(events: list[dict], path: str, digest: str) -> str | None:
    """The run that last recorded `path` as an output, where recording it now under `digest`
    would be a re-record (see `rerecorded_paths`); None where it is a re-run or a first."""
    probe = {"event": "run", "run_id": "", "outputs": [{"path": path, "sha256": digest}]}
    found = rerecorded_paths([*events, probe])
    return found[path][0] if path in found and found[path][1] == "" else None


def label(run_id: str, holds: str, note: str) -> int:
    """Declare, after the fact, that a recorded run's outputs hold no outcome.

    For the run recorded without `--holds` by oversight. The declaration is an event of its
    own, so the ledger shows it was made after the run and what else had been recorded by
    then; the run event is not rewritten. A run is declared once and a label is never changed.
    """
    if holds not in RUN_HOLDS:
        print(f"--holds must be one of: {', '.join(RUN_HOLDS)}")
        return 1
    if not note.strip():
        print("a note is required: say why the run was not labelled when it was recorded.")
        return 1
    root = require_root()
    lp = ledger_path(root)
    events = ledger.read_ledger(lp)
    runs = [e for e in events if e.get("event") == "run" and e.get("run_id") == run_id]
    if not runs:
        print(f"no run '{run_id}' in the ledger.")
        return 1
    if len(runs) > 1:
        print(f"run id '{run_id}' names {len(runs)} runs, and a label has to name one.")
        return 1
    declared = [e for e in events if e.get("event") == "label" and e.get("run_id") == run_id]
    if "holds" in runs[0] or declared:
        print(f"run '{run_id}' already says what it holds; a label is not changed.")
        return 1
    ledger.append_event(lp, {"event": "label", "run_id": run_id, "holds": holds, "note": note})
    print(f"run {run_id}: declared after the fact as holding {holds}")
    print("`prereg freeze` reports a declaration made after the run was recorded as such.")
    return 0


def recorded_paths(events: list[dict]) -> set[str]:
    """Every path a seal or a run recorded."""
    return {f["path"] for e in events for f in e.get("files", []) + e.get("outputs", [])}


def retired(events: list[dict]) -> dict[str, dict[str, str]]:
    """Each path retired and not recorded again since, with what its retirement said: the
    `note`, and the `superseded_by` path where one was given.

    Read in ledger order, so the latest event about a path decides: a seal or a run after a
    retirement makes the path part of the project again.
    """
    found: dict[str, dict[str, str]] = {}
    for e in events:
        if e.get("event") == "retire":
            said = {"note": e.get("note", "")}
            if replacement := e.get("superseded_by"):
                said["superseded_by"] = replacement
            found |= dict.fromkeys(e.get("paths", []), said)
        for f in e.get("files", []) + e.get("outputs", []):
            found.pop(f["path"], None)
    return found


def retire(files: list[str], note: str, superseded_by: str | None = None) -> int:
    """Record that recorded paths are no longer part of the project, and why.

    The seals and runs that recorded each path stay in the ledger as they were; this adds an
    event after them. `verify --files` then reports the path `RETIRED` and passes it, and fails
    it as `REAPPEARED` where a file at that path holds bytes no record names.

    `superseded_by` names the path that replaces them, which has to exist. Where the ledger
    records that path too, the event also carries the digest it holds now, so the retirement
    names the bytes it pointed to.
    """
    if not note.strip():
        print("a note is required: say why these paths are no longer part of the project.")
        return 1
    root = require_root()
    lp = ledger_path(root)
    events = ledger.read_ledger(lp)
    known, already = recorded_paths(events), retired(events)
    paths = []
    for name in files:
        path = record_path(pathlib.Path(name).resolve(), root)
        if path not in known:
            print(f"not retired: {name} was never recorded by a seal or a run.")
            print("nothing was written. Only a path the ledger names can be retired.")
            return 1
        if path in already:
            print(f"not retired: {name} is already retired: {already[path]['note']}")
            print("nothing was written.")
            return 1
        if path not in paths:
            paths.append(path)
    event: dict[str, object] = {"event": "retire", "paths": paths, "note": note}
    if superseded_by is not None:
        replacement = pathlib.Path(superseded_by).resolve()
        if not replacement.exists():
            print(f"not retired: --superseded-by {superseded_by} does not exist.")
            print("nothing was written. Name the path that replaces them as it is on disk.")
            return 1
        event["superseded_by"] = record_path(replacement, root)
        if event["superseded_by"] in known:
            event["superseded_by_sha256"] = (
                sha256_of_tree(replacement)[0]
                if replacement.is_dir()
                else ledger.sha256_of_file(replacement)
            )
    ledger.append_event(lp, event)
    print(f"retired {len(paths)} path(s): {note}")
    for path in paths:
        print(f"  {path}")
    if superseded_by is not None:
        print(f"  superseded by {event['superseded_by']}")
    print("their seals and runs stay in the ledger; `verify --files` reports each as RETIRED.")
    return 0


def claim(
    text: str,
    run_id: str,
    confirmatory: bool,
    anyway: bool,
    frozen_at: str | None,
    location: str | None,
    strict: bool = False,
    derived: str | None = None,
) -> int:
    root = require_root()
    lp = ledger_path(root)

    # A claim on a ledger whose committed history it does not extend rests on a chain that was
    # rewritten: `verify` fails it, and recording a claim on it is refused as `reanchor` is.
    if rewrites := history.rewritten(lp):
        print("refusing: git history holds a ledger this one does not extend.")
        for problem in rewrites:
            print(f"  {problem}")
        print("nothing was written. Restore the ledger from the commit, then record the claim.")
        return 1

    events = ledger.read_ledger(lp)
    run_ids = {e["run_id"] for e in events if e.get("event") == "run"}
    if run_id not in run_ids:
        print(f"no run with id '{run_id}' in the ledger.")
        print(f"known runs: {', '.join(sorted(run_ids)) or '(none)'}")
        return 1

    # The numbers the sentence prints, against what the run wrote. Said before anything is
    # written, and under `--strict` a refusal, so a claim the run does not back never enters
    # the ledger by accident; without it a warning, since a run's outputs may hold a number in
    # a form this cannot read.
    if hidden := readable(text)[1]:
        print(
            f"warning: the claim holds {hidden} format character(s), zero-width or invisible; "
            "its numbers are read without them."
        )
    held = outputs.held_by(events, run_id, root.parent)
    owed = outputs.owed(text)
    absent = outputs.missing(text, held) if held.read else owed
    if derived is not None and not derived.strip():
        print("--derived takes how the number was derived, in words.")
        return 1
    if owed and absent and not derived:
        said = "refusing" if strict else "warning"
        if held.read:
            print(
                f"{said}: run '{run_id}' wrote no value that rounds to {', '.join(absent)} "
                "at the precision the claim prints."
            )
        elif held.unchecked:
            print(
                f"{said}: no output of run '{run_id}' is the bytes it recorded, so the claim's "
                "numbers were not checked against it."
            )
        else:
            print(
                f"{said}: run '{run_id}' records no output this can read as text, so the "
                "claim's numbers were not checked against it."
            )
        for path in held.changed:
            print(f"  {record_path(path, root)} is not the bytes run '{run_id}' recorded, so")
            print("  it was not read: `results verify --files` reports it as changed.")
        for path in held.absent:
            print(f"  {record_path(path, root)} is not on disk.")
        print("  `results verify` reports it until the claim and the run agree.")
        if strict:
            print("nothing was written. Name the run that wrote these numbers.")
            return 1

    recorded = freezes.read_all(root.parent, lp)
    freeze = None
    if frozen_at:
        freeze = _named_freeze(root, frozen_at, recorded)
        if freeze is None:
            return 1
    lines = freezes.lines_of(lp)
    seen = timeline.first_outcomes_seen(events)
    seen_at = freezes.index_of(lines, "access", lambda e: e.get("level") == "outcomes seen")
    run_at = freezes.run_index(lines, run_id)
    recorded_at = timeline.first_run_timestamp(events, run_id)

    retrospective = None
    if confirmatory and seen is not None:
        if recorded_at is None or recorded_at > seen:
            retrospective = seen

    # Exposure is evidence of possible contamination, not contamination. What
    # threatens a confirmatory reading is propagation: outcome information
    # reaching a consequential choice. A plan frozen before the exposure
    # cannot be reached by it, so the disposition is confirmatory with the
    # exposure logged, and the demotion is scoped to decisions not so protected.
    # Before means before in the ledger's order, read from the freeze record: never the commit
    # date, which the committer sets.
    ordered = freezes.before(freeze, seen_at, seen) if freeze and retrospective else None
    protected = bool(retrospective and ordered)
    if protected:
        retrospective = None

    # A confirmatory claim rests on a run the plan governed. A run recorded before the plan it
    # cites, or before every plan where it cites none, was not governed by one. Said, and kept
    # in the claim, and never refused: an earlier run can be a pilot the plan was written from.
    compared = [freeze] if freeze else recorded
    unplanned = bool(
        confirmatory
        and compared
        and all(freezes.before(f, run_at, recorded_at) is False for f in compared)
    )

    if retrospective and not anyway:
        print(
            f"refusing: outcomes were seen at {retrospective[:19]}, and run "
            f"'{run_id}' was recorded after that."
        )
        if freeze is not None and ordered is False:
            print(f"the freeze record {freeze.record} was written after the outcomes were seen.")
        elif freeze is not None:
            print(f"the freeze record {freeze.record} cannot be placed before the exposure:")
            print(f"  {freeze.misplaced or 'it holds no position in this ledger and no time'}")
        print("a claim from a run that postdates seeing the outcomes is retrospective,")
        print("unless the choices it rests on were fixed before the exposure.")
        print("if a plan was frozen before then, pass --frozen-at <the commit its record names>;")
        print("otherwise drop --confirmatory, or pass --anyway to record it as")
        print("confirmatory with the ordering noted permanently in the ledger.")
        return 1

    event = {
        "event": "claim",
        "claim": text,
        "run_id": run_id,
        "confirmatory": confirmatory,
        "after_outcomes_seen": bool(retrospective),
        "frozen_at": frozen_at or "",
        "frozen_at_time": freeze.frozen_at if freeze else "",
        "location": location or "",
    }
    if derived:
        event["derived"] = derived
    if unplanned:
        event["run_before_freeze"] = True
    ledger.append_event(lp, event)
    status = "confirmatory" if confirmatory else "exploratory"
    print(f"claim ({status}): {text[:72]}")
    print(f"  backed by run: {run_id}")
    if location:
        print(f"  appears in: {location}")
    if derived:
        print(f"  derived: {derived}; its numbers are not compared with the run's outputs")
    if protected and freeze is not None:
        print(f"  plan frozen at {frozen_at} on {freeze.frozen_at[:19]}, before outcomes")
        print("  were seen: confirmatory, exposure logged")
    elif retrospective:
        print(f"  recorded after outcomes were seen at {retrospective[:19]}; verify will report it")
    if unplanned:
        which = "the plan it cites" if freeze else "every plan frozen here"
        print(f"  run '{run_id}' was recorded before {which} was frozen; verify will report it")
    return 0


def _named_freeze(
    root: pathlib.Path, frozen_at: str, recorded: list[freezes.Freeze]
) -> freezes.Freeze | None:
    """The freeze record `--frozen-at` names, or None after saying why it names none.

    A full commit id, which a record beside a frozen plan holds. Any reference git resolves was
    accepted before, `HEAD` included, and then dated by its commit date.
    """

    def known() -> None:
        if recorded:
            print("the freeze records here name:")
            for f in recorded:
                print(f"  {f.commit}  {f.record}")
        else:
            print("no freeze record is here: `prereg freeze` writes one beside the plan.")

    if not freezes.FULL_COMMIT.fullmatch(frozen_at):
        print(f"--frozen-at takes the full commit id a freeze record names, not '{frozen_at}'.")
        known()
        return None
    if timeline.freeze_timestamp(root, frozen_at) is None:
        print(f"cannot resolve --frozen-at '{frozen_at}': not a commit in this repository.")
        print("a freeze reference must name a commit that contains the frozen plan.")
        return None
    freeze = freezes.named(recorded, frozen_at)
    if freeze is None:
        print(f"no freeze record names commit {frozen_at}.")
        known()
    return freeze


def session(model: str | None) -> dict[str, str]:
    """Where the command ran and which model the caller names, for a review's record.

    Read off the environment and the `--model` flag, and checked against nothing. Claude Code
    exports its own version and session but not the model, so the model is whatever the caller
    passes. A person who runs the command from inside a session is recorded the same way as a
    model that does, which is why the reviewer is a separate, required field.
    """
    found: dict[str, str] = {}
    if model:
        found["model"] = model
    if os.environ.get("CLAUDECODE") == "1":
        found["harness"] = "Claude Code"
        version = pathlib.PurePath(os.environ.get("CLAUDE_CODE_EXECPATH", "")).name
        if re.fullmatch(r"\d+(\.\d+)+", version):
            found["harness_version"] = version
        if session_id := os.environ.get("CLAUDE_CODE_SESSION_ID"):
            found["session_id"] = session_id
    return found


def digests_of(files: list[str], root: pathlib.Path) -> list[dict[str, str]] | None:
    """Each named file or directory by its digest, or None once one of them is neither.

    What a review and an annotation both record under `subjects`. Named `subjects`, never
    `files`: `verify --files` reads `files` as seals, and a subject that later changes would
    then report the path as sealed twice.
    """
    subjects = []
    for name in files:
        p = pathlib.Path(name).resolve()
        if p.is_dir():
            digest = sha256_of_tree(p)[0]
            subjects.append({"path": record_path(p, root), "sha256": digest, "kind": "tree"})
            continue
        if not p.is_file():
            print(f"not a file: {name}")
            return None
        digest = ledger.sha256_of_file(p)
        subjects.append({"path": record_path(p, root), "sha256": digest, "kind": "file"})
    return subjects


def review(
    files: list[str],
    scope: str,
    procedure: str,
    verdict: str,
    reviewer: str,
    model: str | None,
    note: str | None,
) -> int:
    root = require_root()
    lp = ledger_path(root)
    if verdict not in VERDICTS:
        print(f"verdict must be one of: {', '.join(VERDICTS)}")
        return 1
    subjects = digests_of(files, root)
    if subjects is None:
        return 1
    ran_in = session(model)
    ledger.append_event(
        lp,
        {
            "event": "review",
            "subjects": subjects,
            "scope": scope,
            "procedure": procedure,
            "verdict": verdict,
            "reviewer": reviewer,
            "session": ran_in,
            "note": note or "",
        },
    )
    print(f"review ({verdict}) by {reviewer}: {scope[:72]}")
    for subject in subjects:
        print(f"  {subject['sha256'][:16]}…  {subject['path']}")
    if ran_in:
        print(f"  session: {', '.join(f'{k} {v}' for k, v in ran_in.items())}")
    if "harness" in ran_in and "model" not in ran_in:
        print("  ran inside Claude Code with no --model; pass it if a model did the review.")
    print("self-reported and unsigned: the ledger records that this was said, and of which bytes.")
    return 0


def annotate(
    files: list[str],
    kind: str,
    ref: str,
    digest: str | None,
    by: str | None,
    note: str | None,
    location: str | None,
) -> int:
    root = require_root()
    lp = ledger_path(root)
    if not KIND.fullmatch(kind):
        print(f"kind must be namespace:type, such as wandb:artifact or doi:dataset; got '{kind}'")
        print("lowercase letters, digits, '-', '_' and '.' on each side of one colon.")
        return 1
    if not ref.strip():
        print("ref must name the outside thing: an artifact path, a DOI, a URL, an id.")
        return 1
    if digest is not None:
        stated = DIGEST.fullmatch(digest)
        length = DIGEST_LENGTHS.get(stated[1]) if stated else None
        if not stated or (length is not None and len(stated[2]) != length):
            print(f"digest must be algorithm:hex, such as sha256:<64 hex digits>; got '{digest}'")
            return 1
    subjects = digests_of(files, root)
    if subjects is None:
        return 1
    # No session is read here. A review says who or what did the reading, so it records where
    # the command ran; an annotation makes no such statement, and `--by` is whatever was typed.
    target = {"kind": kind, "ref": ref}
    if digest:
        target["digest"] = digest
    event: dict[str, object] = {
        "event": "annotation",
        "subjects": subjects,
        "target": target,
        "status": LINKED,
        "note": note or "",
    }
    if by:
        event["by"] = by
    if location:
        event["location"] = location
    ledger.append_event(lp, event)
    print(f"annotation: {kind}  {ref[:72]}" + (f"  by {by}" if by else ""))
    for subject in subjects:
        print(f"  {subject['sha256'][:16]}…  {subject['path']}")
    if digest:
        print(f"  digest as stated: {digest}")
    if location:
        print(f"  appears in: {location}")
    print(f"{LINKED}: the ledger records that this link was stated, and of which bytes.")
    print("Nothing was fetched or compared.")
    return 0
