"""Download the ReScience/MLRC article PDFs the reader comparison is measured on.

The sampling frame in `reproducible-science-evaluations` reserves 60 of its 215 articles for
a registered sample. Those are never opened here: this script takes only the 155 development
articles, the same ones `batch_dev.py` tunes against, so a measurement of PDF readers cannot
consume the registered sample.

Each PDF is written before the next is requested, and an article already on disk is skipped,
so an interrupted run resumes where it stopped.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import ssl
import time
import urllib.error
import urllib.request

USER_AGENT = "reproducible-science pdf-reader-comparison (contact elliot@elliottower.ai)"


def context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


CONTEXT = context()


def fetch(url: str, timeout: int = 90) -> bytes | None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=CONTEXT) as response:
            return response.read()
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def development_articles(frame: dict) -> list[dict]:
    """The frame minus the registered sample."""
    reserved = set(frame["selected"])
    return [e for e in frame["ordered_frame"] if e["key"] not in reserved]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frame", type=pathlib.Path, required=True)
    parser.add_argument("--into", type=pathlib.Path, required=True)
    parser.add_argument("--limit", type=int, default=0, help="0 takes every development article")
    args = parser.parse_args()

    frame = json.loads(args.frame.read_text())
    articles = development_articles(frame)
    if args.limit:
        articles = articles[: args.limit]
    args.into.mkdir(parents=True, exist_ok=True)
    log = args.into / "fetch_log.jsonl"

    for i, entry in enumerate(articles, 1):
        key = entry["key"].replace(":", "-")
        target = args.into / f"{key}.pdf"
        if target.exists():
            continue
        match = re.search(r"zenodo\.(\d+)", entry.get("doi", ""))
        if not match:
            with log.open("a") as fh:
                fh.write(json.dumps({"key": entry["key"], "status": "no zenodo doi"}) + "\n")
            continue
        payload = fetch(f"https://zenodo.org/record/{match.group(1)}/files/article.pdf")
        status = "ok"
        if not payload or not payload.startswith(b"%PDF"):
            status = "unavailable"
        else:
            target.write_bytes(payload)
        with log.open("a") as fh:
            fh.write(
                json.dumps(
                    {
                        "key": entry["key"],
                        "doi": entry["doi"],
                        "status": status,
                        "bytes": len(payload or b""),
                    }
                )
                + "\n"
            )
        print(f"[{i}/{len(articles)}] {entry['key']} {status}", flush=True)
        time.sleep(1.0)


if __name__ == "__main__":
    main()
