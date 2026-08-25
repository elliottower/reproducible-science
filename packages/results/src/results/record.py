"""The commands that put an event in the ledger.

`init`, `seal`, `access`, `run` and `claim` share a shape: find the governing `.results/`,
build one event, append it, and report what was written. What separates them is the refusal
each makes first -- a path that is not a file, an access level outside the four, a run id
already in use, a confirmatory claim resting on a run recorded after the outcomes were seen.

Each returns the process's exit code. `cli.py` unpacks the argparse namespace and calls in.
"""

from __future__ import annotations

import pathlib

from results import ledger, timeline
from results.paths import RESULTS_DIR, ledger_path, record_path, require_root

ACCESS_LEVELS = [
    "nothing seen",
    "metadata only",
    "structure seen",
    "outcomes seen",
]


def init() -> int:
    d = pathlib.Path.cwd() / RESULTS_DIR
    if d.exists():
        print(f"{d} already exists.")
        return 1
    d.mkdir()
    lp = d / ledger.LEDGER
    lp.touch()
    ledger.append_event(lp, {"event": "init"})
    print(f"created {RESULTS_DIR}/")
    print(f"  {ledger.LEDGER}   append-only event log")
    print("\nseal your inputs before running: `results seal prereg.md script.py data.csv`")
    return 0


def seal(files: list[str], role: str) -> int:
    root = require_root()
    lp = ledger_path(root)
    sealed = []
    for name in files:
        p = pathlib.Path(name).resolve()
        if not p.is_file():
            print(f"not a file: {name}")
            return 1
        digest = ledger.sha256_of_file(p)
        sealed.append({"path": record_path(p, root), "sha256": digest})
    ledger.append_event(
        lp,
        {
            "event": "seal",
            "role": role,
            "files": sealed,
        },
    )
    print(f"sealed {len(sealed)} file(s) as {role}")
    for s in sealed:
        print(f"  {s['sha256'][:16]}…  {s['path']}")
    return 0


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


def run(files: list[str], run_id: str, note: str | None, anyway: bool) -> int:
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
    outputs = []
    for name in files:
        p = pathlib.Path(name).resolve()
        if not p.is_file():
            print(f"not a file: {name}")
            return 1
        digest = ledger.sha256_of_file(p)
        outputs.append({"path": record_path(p, root), "sha256": digest})
    ledger.append_event(
        lp,
        {
            "event": "run",
            "run_id": run_id,
            "outputs": outputs,
            "note": note or "",
        },
    )
    print(f"run {run_id}: {len(outputs)} output(s)")
    for o in outputs:
        print(f"  {o['sha256'][:16]}…  {o['path']}")
    return 0


def claim(
    text: str,
    run_id: str,
    confirmatory: bool,
    anyway: bool,
    frozen_at: str | None,
    location: str | None,
) -> int:
    root = require_root()
    lp = ledger_path(root)

    events = ledger.read_ledger(lp)
    run_ids = {e["run_id"] for e in events if e.get("event") == "run"}
    if run_id not in run_ids:
        print(f"no run with id '{run_id}' in the ledger.")
        print(f"known runs: {', '.join(sorted(run_ids)) or '(none)'}")
        return 1

    retrospective = None
    frozen_time = timeline.freeze_timestamp(root, frozen_at) if frozen_at else None
    if frozen_at and frozen_time is None:
        print(f"cannot resolve --frozen-at '{frozen_at}': not a commit in this repository.")
        print("a freeze reference must name a commit that contains the frozen plan.")
        return 1

    if confirmatory:
        seen = timeline.first_outcomes_seen(events)
        if seen is not None:
            recorded = timeline.first_run_timestamp(events, run_id)
            if recorded is None or recorded > seen:
                retrospective = seen

    # Exposure is evidence of possible contamination, not contamination. What
    # threatens a confirmatory reading is propagation: outcome information
    # reaching a consequential choice. A plan committed before the exposure
    # cannot be reached by it, so the disposition is confirmatory with the
    # exposure logged, and the demotion is scoped to decisions not so protected.
    protected = bool(
        retrospective and frozen_time and timeline.precedes(frozen_time, retrospective)
    )
    if protected:
        retrospective = None

    if retrospective and not anyway:
        print(
            f"refusing: outcomes were seen at {retrospective[:19]}, and run "
            f"'{run_id}' was recorded after that."
        )
        print("a claim from a run that postdates seeing the outcomes is retrospective,")
        print("unless the choices it rests on were fixed before the exposure.")
        print("if a commit contains the frozen plan, pass --frozen-at <commit>;")
        print("otherwise drop --confirmatory, or pass --anyway to record it as")
        print("confirmatory with the ordering noted permanently in the ledger.")
        return 1

    ledger.append_event(
        lp,
        {
            "event": "claim",
            "claim": text,
            "run_id": run_id,
            "confirmatory": confirmatory,
            "after_outcomes_seen": bool(retrospective),
            "frozen_at": frozen_at or "",
            "frozen_at_time": frozen_time or "",
            "location": location or "",
        },
    )
    status = "confirmatory" if confirmatory else "exploratory"
    print(f"claim ({status}): {text[:72]}")
    print(f"  backed by run: {run_id}")
    if location:
        print(f"  appears in: {location}")
    if protected and frozen_time:
        print(f"  plan frozen at {frozen_at} on {frozen_time[:19]}, before outcomes")
        print("  were seen: confirmatory, exposure logged")
    elif retrospective:
        print(f"  recorded after outcomes were seen at {retrospective[:19]}; verify will report it")
    return 0
