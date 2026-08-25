"""Can a value known to be in an artifact be found in it without running anything?

Every measurement so far has lacked ground truth: when a printed value was not found, nobody
could say whether the artifact lacked it or the scanner missed it. CORE-Bench supplies the
missing half. Each capsule carries questions about the work paired with the values the
capsule produces, authored by the benchmark rather than here, over an artifact pinned by DOI.

So a miss here is unambiguous. The value is what the capsule yields; if a static read cannot
find it, that is the ceiling on reading an artifact without executing it, measured rather
than argued.

Capsules are downloaded, indexed and deleted one at a time, and every result is appended
before the next begins: 45 capsules at roughly 39 MB each is more than needs to be kept, and
a run interrupted halfway should leave the capsules it already measured.
"""

from __future__ import annotations

import argparse
import io
import json
import pathlib
import shutil
import ssl
import sys
import tarfile
import time
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from confirm_numbers import build_index, collect, strength  # noqa: E402

HERE = pathlib.Path(__file__).parent
CORPUS = HERE / "corebench"
TASKS = CORPUS / "core_train.json"
RESULTS = CORPUS / "recall.jsonl"
WORK = CORPUS / "work"

CAPSULE_URL = "https://corebench.cs.princeton.edu/capsules/{capsule_id}.tar.gz"
USER_AGENT = "addressability-sample/1.0 (research; contact elliot@elliottower.ai)"

#: Decimal places to try when looking for a value. The benchmark stores full float precision
#: and a capsule may print the same quantity rounded, so `0.9375660604380387` is looked for
#: as itself and as `0.94`, `0.938`, and so on. Each match records which form answered, since
#: finding a value at two decimals is weaker evidence than finding it at sixteen.
PLACES = range(1, 9)


def context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


CONTEXT = context()


def download(capsule_id: str, into: pathlib.Path) -> bool:
    """Fetch and unpack one capsule, or report that it could not be had."""
    request = urllib.request.Request(CAPSULE_URL.format(capsule_id=capsule_id),
                                     headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=600, context=CONTEXT) as response:
            payload = response.read()
    except Exception:
        return False
    into.mkdir(parents=True, exist_ok=True)
    root = into.resolve()
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                target = (into / member.name).resolve()
                if not str(target).startswith(str(root)):
                    # A tar member may name a path that climbs out of the directory.
                    continue
                handle = archive.extractfile(member)
                if handle is not None:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(handle.read())
    except (tarfile.TarError, OSError, ValueError):
        return False
    return True


def look_for(value: float, index: dict) -> dict | None:
    """The first form of this value present in the artifact, with how precise that form is."""
    exact = repr(value)
    if exact in index:
        return {"form": exact, "places": None, "where": index[exact][0]}
    for places in PLACES:
        rounded = f"{value:.{places}f}"
        if rounded in index:
            return {"form": rounded, "places": places, "where": index[rounded][0]}
    return None


def measure(task: dict, capsule: pathlib.Path) -> dict:
    groups = collect(capsule)
    index, unread = build_index(
        groups["data"] + groups["spreadsheet"] + groups["binary"] + groups["compressed"]
        + groups["code"], capsule)

    answers = []
    for entry in task.get("results", []):
        for question, value in entry.items():
            if not isinstance(value, (int, float)):
                continue
            hit = look_for(float(value), index)
            answers.append({
                "question": question[:160],
                "value": value,
                "found": hit is not None,
                **(hit or {}),
                "strength": strength(repr(float(value))),
            })
    return {
        "capsule_id": task["capsule_id"],
        "doi": task.get("capsule_doi", ""),
        "language": task.get("language", ""),
        "field": task.get("field", ""),
        "index_size": len(index),
        "files": {k: len(v) for k, v in groups.items()},
        "unread": len(unread),
        "answers": answers,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=45)
    args = parser.parse_args()

    tasks = json.loads(TASKS.read_text())
    done = set()
    if RESULTS.exists():
        done = {json.loads(line)["capsule_id"]
                for line in RESULTS.read_text().splitlines() if line}

    added = 0
    for task in tasks:
        if added >= args.limit or task["capsule_id"] in done:
            continue
        capsule = WORK / task["capsule_id"]
        shutil.rmtree(capsule, ignore_errors=True)
        started = time.time()
        if not download(task["capsule_id"], capsule):
            record = {"capsule_id": task["capsule_id"], "status": "not retrieved"}
        else:
            record = {"status": "measured", **measure(task, capsule)}
        shutil.rmtree(capsule, ignore_errors=True)

        with RESULTS.open("a") as handle:
            handle.write(json.dumps(record) + "\n")
        added += 1
        found = sum(1 for a in record.get("answers", []) if a["found"])
        total = len(record.get("answers", []))
        print(f"  [{added:2}/{args.limit}] {task['capsule_id']}  {record['status']:<14}"
              f"  {found}/{total} found  index {record.get('index_size', 0):>7}"
              f"  {time.time() - started:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
