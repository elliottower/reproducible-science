"""Run the three stages over development articles and record what each one settles.

Development articles are the 155 in the frame that the sample did not take. They are used to
tune the scan; the sampled 60 are never opened here. Every article processed is appended to
`results.jsonl` before the next begins, so an interrupted run resumes rather than restarts,
and a run that dies halfway leaves a usable partial record rather than nothing.

Nothing here estimates a registered quantity. The output is an engineering measurement of
how much of a paper the scan can settle and how much of that is coincidence.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import ssl
import subprocess
import sys
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from confirm_numbers import (BINARY, COMPRESSORS, TIERS, TRACEABLE,  # noqa: E402
                             build_index, collect, strength)
from precision_check import decoys  # noqa: E402
from scan_numbers import scan  # noqa: E402

HERE = pathlib.Path(__file__).parent
FRAME = HERE / "frame.json"
CORPUS = HERE / "dev_corpus"
RESULTS = CORPUS / "results.jsonl"

USER_AGENT = "addressability-sample/1.0 (research; contact elliot@elliottower.ai)"

#: A repository past this size is recorded and skipped. The scan reads text; a multi-gigabyte
#: checkout is model weights or image data, and cloning it buys nothing.
MAX_REPO_KB = 400_000


def _context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


CONTEXT = _context()


def fetch(url: str, timeout: int = 60) -> bytes | None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=CONTEXT) as response:
            return response.read()
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def article_text(entry: dict, into: pathlib.Path) -> pathlib.Path | None:
    """The article as laid-out text, downloaded once and cached.

    `-layout` is required rather than preferred: column alignment is what separates a table
    row from a flattened figure, and the default mode discards it.
    """
    target = into / "article.txt"
    if target.exists():
        return target
    match = re.search(r"zenodo\.(\d+)", entry.get("doi", ""))
    if not match:
        return None
    payload = fetch(f"https://zenodo.org/record/{match.group(1)}/files/article.pdf")
    if not payload:
        return None
    pdf = into / "article.pdf"
    pdf.write_bytes(payload)
    result = subprocess.run(["pdftotext", "-layout", str(pdf), str(target)],
                            capture_output=True)
    pdf.unlink(missing_ok=True)
    return target if result.returncode == 0 and target.exists() else None


def clone(entry: dict, into: pathlib.Path) -> tuple[pathlib.Path | None, str]:
    """A shallow checkout of the article's repository, or the reason there is none."""
    target = into / "repo"
    if target.exists():
        return target, ""
    match = re.search(r"github\.com[/:]([^/]+)/([^/\s#?]+)", entry.get("code_url") or "")
    if not match:
        return None, "no github url"
    owner, repo = match.group(1), re.sub(r"\.git$", "", match.group(2))
    meta = fetch(f"https://api.github.com/repos/{owner}/{repo}", timeout=30)
    if meta is None:
        return None, "repository not reachable"
    size = json.loads(meta).get("size", 0)
    if size > MAX_REPO_KB:
        return None, f"repository is {size // 1000} MB"
    result = subprocess.run(
        ["git", "clone", "--depth", "1", "-q", f"https://github.com/{owner}/{repo}.git",
         str(target)], capture_output=True, timeout=600)
    if result.returncode != 0:
        shutil.rmtree(target, ignore_errors=True)
        return None, "clone failed"
    return target, ""


def measure(text_path: pathlib.Path, repo: pathlib.Path) -> dict:
    """Categories, verdicts and the decoy rate for one article."""
    records = scan(text_path.read_text(errors="replace"))
    categories: dict[str, int] = {}
    for record in records:
        categories[record["kind"]] = categories.get(record["kind"], 0) + 1

    groups = collect(repo)
    index, partial = build_index(
        groups["data"] + groups["spreadsheet"] + groups["binary"] + groups["compressed"]
        + groups["code"], repo)
    unread = partial + [str(p.relative_to(repo)) for p in groups["unread"]]

    traceable = [r for r in records if r["kind"] in TRACEABLE]
    printed = {r["printed"] for r in traceable}
    tiers: dict[str, dict] = {}
    for tier in TIERS:
        row = [r for r in traceable if strength(r["printed"]) == tier]
        if not row:
            continue
        hits = sum(1 for r in row if r["printed"] in index)
        trials = [d for r in row for d in decoys(r["printed"]) if d not in printed]
        tiers[tier] = {
            "values": len(row),
            "confirmed": hits,
            "verdict_for_misses": "unchecked" if unread else "absent",
            "decoy_trials": len(trials),
            "decoy_hits": sum(1 for d in trials if d in index),
        }

    return {
        "numeric_tokens": len(records),
        "categories": categories,
        "files": {k: len(v) for k, v in groups.items()},
        "index_size": len(index),
        "unread": unread[:20],
        "tiers": tiers,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=20, help="articles to add this run")
    args = parser.parse_args()

    CORPUS.mkdir(exist_ok=True)
    done = set()
    if RESULTS.exists():
        done = {json.loads(line)["key"] for line in RESULTS.read_text().splitlines() if line}

    frame = json.loads(FRAME.read_text())
    sampled = set(frame["selected"])
    candidates = [e for e in frame["ordered_frame"]
                  if e["key"] not in sampled and e["key"] not in done
                  and "github.com" in (e.get("code_url") or "")]

    added = 0
    for entry in candidates:
        if added >= args.limit:
            break
        key = entry["key"]
        into = CORPUS / key.replace(":", "_")
        into.mkdir(parents=True, exist_ok=True)

        text_path = article_text(entry, into)
        if text_path is None:
            record = {"key": key, "status": "no article text"}
        else:
            repo, reason = clone(entry, into)
            if repo is None:
                record = {"key": key, "status": reason}
            else:
                record = {"key": key, "status": "measured", "year": entry.get("year", ""),
                          **measure(text_path, repo)}
                # The checkout is the bulk of the disk cost and nothing downstream needs it
                # once the index has been reduced to counts.
                shutil.rmtree(repo, ignore_errors=True)

        with RESULTS.open("a") as handle:
            handle.write(json.dumps(record) + "\n")
        added += 1
        print(f"  [{added:2}/{args.limit}] {key:<22} {record['status']}"
              + (f"  {record.get('numeric_tokens', '')} tokens,"
                 f" index {record.get('index_size', '')}"
                 if record["status"] == "measured" else ""), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
