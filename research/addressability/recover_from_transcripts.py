"""Recover the runs behind a printed table from Claude Code session transcripts.

A script that prints its results and writes nothing leaves the values in scrollback and
nowhere else. On one manuscript being prepared for submission, the script producing a results
table ends in `print("LaTeX table rows:")` and never opens a file, so the numbers in the paper
have no address on disk and no search can find one -- there is nothing correct to find.

The transcripts are the surviving record. Where a script was run inside a session, its stdout
is in `~/.claude/projects/<project>/<session>.jsonl`, or in a persisted `tool-results` file
when the output was large.

This is the one case where searching beats addressing, because no address exists. It is a
recovery path and not a verification: what it returns is what some run printed, which is
evidence about history rather than about the artifact. Two runs printing different values for
one metric is the finding, and the tool reports both rather than choosing.
"""

from __future__ import annotations

import argparse
import collections
import datetime
import json
import pathlib
import re

TRANSCRIPTS = pathlib.Path.home() / ".claude" / "projects"

#: A row of a printed table: a label, a separator, and a number. Matches LaTeX rows and the
#: aligned plain-text form, since scripts usually print both.
#:
#: No line anchor. A `.jsonl` transcript stores stdout as an escaped string, so its newlines
#: are the two characters `\` and `n` rather than line breaks, and an anchored pattern matches
#: nothing in the file that holds most of the output.
ROW = re.compile(
    r"(?:^|\\n|\n)[ \t]*([A-Za-z][A-Za-z0-9 ()\-/.']{1,38}?)"
    r"[ \t]*(?:&|\|{1,2}|[ \t]{2,})[ \t]*"
    r"\$?([+-]?\d+\.\d{2,})"
)

#: Characters either side of the marker to read rows from. A whole chunk admits every table
#: printed anywhere near it: an 8 MB block once contributed a table from an unrelated project
#: because both appeared in one long session.
WINDOW = 6000

#: Files larger than this are read in chunks rather than whole; a transcript can be hundreds
#: of megabytes and a recovery pass must not need to hold one in memory.
CHUNK = 8 * 1024 * 1024


def transcripts(project: str | None) -> list[pathlib.Path]:
    root = TRANSCRIPTS
    if not root.is_dir():
        return []
    dirs = [d for d in root.iterdir() if d.is_dir()]
    if project:
        dirs = [d for d in dirs if project.lower() in d.name.lower()]
    found: list[pathlib.Path] = []
    for d in dirs:
        found += sorted(d.glob("*.jsonl"))
        found += sorted(d.glob("*/tool-results/*.txt"))
    return found


def rows_near(text: str, marker: str) -> list[tuple[str, str]]:
    """Table rows within `WINDOW` characters of each occurrence of the marker."""
    found: list[tuple[str, str]] = []
    unfolded = text.replace("\\n", "\n")
    lowered = unfolded.lower()
    at = lowered.find(marker.lower())
    while at != -1:
        window = unfolded[max(0, at - WINDOW // 4) : at + WINDOW]
        for label, value in ROW.findall(window):
            label = " ".join(label.split())
            if len(label) > 2 and not label[0].isdigit():
                found.append((label, value))
        at = lowered.find(marker.lower(), at + 1)
    return found


def scan(path: pathlib.Path, marker: str) -> list[tuple[str, str, str]]:
    """Rows printed near `marker`, each with when the record carrying it was written.

    A `.jsonl` transcript is one record per line and every record carries its own timestamp,
    so the runs can be ordered rather than merely counted. That matters more than the count:
    knowing a metric printed four values says the manuscript quotes one of them, and knowing
    which was last says whether it quotes the newest.
    """
    rows: list[tuple[str, str, str]] = []
    try:
        if path.suffix == ".jsonl":
            with path.open("r", errors="replace") as handle:
                for line in handle:
                    if marker.lower() not in line.lower():
                        continue
                    when = ""
                    try:
                        when = (json.loads(line).get("timestamp") or "")[:19]
                    except ValueError:
                        pass
                    for label, value in rows_near(line, marker):
                        rows.append((label, value, when))
        else:
            # A persisted tool result has no record of its own; the file's mtime is the
            # closest thing to when it was written and is labelled as such.
            when = datetime.datetime.fromtimestamp(path.stat().st_mtime).isoformat()[:19]
            with path.open("r", errors="replace") as handle:
                while True:
                    block = handle.read(CHUNK)
                    if not block:
                        break
                    for label, value in rows_near(block, marker):
                        rows.append((label, value, when))
    except OSError:
        return rows
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "marker", help="a string the run printed: a script name, a table caption, a header line"
    )
    parser.add_argument("--project", help="limit to transcripts of one project directory")
    parser.add_argument("--label", help="only report rows whose label contains this")
    parser.add_argument("--show", type=int, default=20)
    args = parser.parse_args()

    files = transcripts(args.project)
    if not files:
        print(f"  no transcripts under {TRANSCRIPTS}")
        return 1

    values: dict[str, dict[str, str]] = collections.defaultdict(dict)
    for path in files:
        for label, value, when in scan(path, args.marker):
            if args.label and args.label.lower() not in label.lower():
                continue
            # Keep the latest sighting of each value, so a run can be ordered by when it ran.
            if when > values[label].get(value, ""):
                values[label][value] = when

    if not values:
        print(f"  nothing printed near {args.marker!r} in {len(files)} transcripts")
        return 0

    print(f"\n  {len(files)} transcripts searched for {args.marker!r}")
    print(f"  {len(values)} labels with a printed value\n")
    varying = {k: v for k, v in values.items() if len(v) > 1}
    for label in sorted(values, key=lambda k: (-len(values[k]), k))[: args.show]:
        seen = sorted(values[label].items(), key=lambda kv: kv[1])
        newest = seen[-1][0] if seen else ""
        rendered = ", ".join(
            f"{v}{' (newest)' if v == newest and len(seen) > 1 else ''}" for v, _ in seen[:6]
        )
        when = seen[-1][1][:10] if seen and seen[-1][1] else "no date"
        print(f"    {label:<26} {rendered}")
        if len(seen) > 1:
            print(f"    {'':<26} last printed {when}")
    if varying:
        print(
            f"\n  {len(varying)} label(s) printed more than one value. A script that writes "
            f"nothing\n  leaves no way to tell which run a manuscript quoted; the fix is one "
            f"line in the\n  script, not a better search."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
