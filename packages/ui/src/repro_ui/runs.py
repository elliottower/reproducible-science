"""Re-runs the page starts, kept apart from the page: each `repro reproduce` runs as a process of
its own, in a session of its own, so closing the tab, stopping the server or closing the terminal
does not stop it.

A run leaves two files in the page's data folder, under runs/:

    <run>.json   the marker: process id, the steps asked for, when it started, and how many
                 re-runs the record held before it, written before the run can finish
    <run>.log    what `repro reproduce` printed

The page reads them back. A live process is a run still going. A finished one is read from the
re-run `repro reproduce` appended to .repro/reproductions.jsonl; a process that is gone with no
such re-run was interrupted. A step with a live run cannot be started again until it ends.
"""

from __future__ import annotations

import datetime
import json
import os
import pathlib
import re
import secrets
import signal
import subprocess

#: A run's name, as it is written and as a request must give it.
RUN_ID = re.compile(r"^[0-9]{8}T[0-9]{6}-[0-9a-f]{6}$")
#: How much of a run's log the page is sent.
LOG_TAIL = 64_000
#: How many finished runs are kept; older markers and logs are removed.
KEEP = 50

#: Processes this server started, by process id. A child that has ended stays a zombie until it
#: is waited for, and a zombie still answers `kill(pid, 0)`, so these are asked directly.
_children: dict[int, subprocess.Popen] = {}


class Busy(Exception):
    """A run asked for a step that a live run already covers."""

    def __init__(self, run: dict) -> None:
        self.run = run
        steps = ", ".join(run["only"]) if run["only"] else "every step"
        super().__init__(f"{steps} is already running")


def folder(data: pathlib.Path) -> pathlib.Path:
    return data / "runs"


def record_lines(project: pathlib.Path) -> list[str]:
    path = project / ".repro" / "reproductions.jsonl"
    return [x for x in path.read_text().splitlines() if x.strip()] if path.exists() else []


def alive(pid: int) -> bool:
    child = _children.get(pid)
    if child is not None:
        return child.poll() is None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # someone else's process now holds the id: not this run
        return False
    return True


def markers(data: pathlib.Path) -> list[dict]:
    """Every run's marker, newest first."""
    out = []
    for f in folder(data).glob("*.json"):
        if not RUN_ID.match(f.stem):
            continue
        try:
            out.append(json.loads(f.read_text()))
        except ValueError:  # a marker being written; read again on the next request
            continue
    return sorted(out, key=lambda m: m["run_id"], reverse=True)


def overlaps(a: list[str] | None, b: list[str] | None) -> bool:
    return a is None or b is None or bool(set(a) & set(b))


def start(
    project: pathlib.Path, data: pathlib.Path, argv: list[str], only: list[str] | None
) -> dict:
    """Start `argv` (`repro reproduce` and its options) as a process of its own, and write its
    marker. Raises Busy where a live run covers one of the steps asked for."""
    for m in markers(data):
        if alive(m["pid"]) and overlaps(m["only"], only):
            raise Busy(m)
    runs = folder(data)
    runs.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now(datetime.UTC)
    run_id = f"{now:%Y%m%dT%H%M%S}-{secrets.token_hex(3)}"
    log = runs / f"{run_id}.log"
    before = len(record_lines(project))
    with open(log, "wb") as out:
        proc = subprocess.Popen(
            argv,
            cwd=project,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
    _children[proc.pid] = proc
    marker = {
        "run_id": run_id,
        "pid": proc.pid,
        "only": only,
        "started_at": now.isoformat(timespec="seconds"),
        "record_before": before,
    }
    partial = runs / f"{run_id}.json.partial"
    partial.write_text(json.dumps(marker))
    partial.replace(runs / f"{run_id}.json")
    prune(data)
    return marker


def prune(data: pathlib.Path) -> None:
    for m in markers(data)[KEEP:]:
        if not alive(m["pid"]):
            for suffix in (".json", ".log"):
                (folder(data) / f"{m['run_id']}{suffix}").unlink(missing_ok=True)


def result(project: pathlib.Path, marker: dict, lines: list[str]) -> dict | None:
    """The re-run this run appended to the record: the first one after the marker was written
    that ran the steps asked for. None where there is none."""
    for line in lines[marker["record_before"] :]:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        ran = [r for r in e.get("regenerations", []) if r.get("state") != "not_rerun"]
        if marker["only"] is not None and {r.get("regeneration_id") for r in ran} != set(
            marker["only"]
        ):
            continue
        return {
            "ended_at": e.get("ended_at"),
            "steps": [
                {
                    "id": r.get("regeneration_id"),
                    "state": r.get("state"),
                    "seconds": r.get("duration_seconds"),
                    "detail": r.get("detail", ""),
                    "exit_code": r.get("exit_code"),
                }
                for r in ran
            ],
        }
    return None


def state(project: pathlib.Path, data: pathlib.Path, marker: dict, lines: list[str]) -> dict:
    """A run as the page shows it: running, done (with what the record says) or interrupted."""
    log = folder(data) / f"{marker['run_id']}.log"
    text = ""
    if log.is_file():
        with open(log, "rb") as f:
            f.seek(max(0, log.stat().st_size - LOG_TAIL))
            text = f.read().decode("utf-8", errors="replace")
    out = {**marker, "log": text}
    if alive(marker["pid"]):
        return {**out, "state": "running"}
    found = result(project, marker, lines)
    return {**out, "state": "done", **found} if found else {**out, "state": "interrupted"}


def listed(project: pathlib.Path, data: pathlib.Path, limit: int = 20) -> list[dict]:
    lines = record_lines(project)
    return [state(project, data, m, lines) for m in markers(data)[:limit]]


def stop(data: pathlib.Path, run_id: str) -> bool:
    """Send SIGTERM to a live run's process group. False where there is no such live run."""
    if not RUN_ID.match(run_id):
        return False
    m = next((m for m in markers(data) if m["run_id"] == run_id), None)
    if m is None or not alive(m["pid"]):
        return False
    try:
        os.killpg(m["pid"], signal.SIGTERM)
    except ProcessLookupError:
        return False
    return True
