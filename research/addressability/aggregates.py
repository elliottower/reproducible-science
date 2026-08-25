"""Values a paper reports that its artifact never stores, because they are computed from it.

A capsule stores one AUC per run; the paper reports their average. The average appears
nowhere in the artifact, and a scanner comparing printed strings calls it absent -- which is
false, since the artifact fully determines it.

The fix has to be narrow. Searching for any subset of stored values whose mean equals the
target will succeed on almost any target: 62,819 values admit more four-element subsets than
there are distinct four-decimal numbers. That is manufactured agreement, and the decoy test
catches it every time.

So aggregation is over a **column**, not over a subset. A tabular file with a numeric column
offers one mean, one median, one sum, one minimum, one maximum and one standard deviation --
six candidates per column rather than combinatorially many. A match against `mean of column
auc in results.csv` names a group the artifact itself defined, and a fabricated value has no
more reason to equal it than to equal any other single stored number.
"""

from __future__ import annotations

import csv
import io
import math
import pathlib
import re
import statistics

#: Decimal places a derived value must agree to before the match counts. An aggregate is
#: computed, not transcribed, so the real one agrees to full float precision; a loose
#: comparison invites collisions instead. At two decimals three different target AUCs all
#: matched the mean of a training-label column in one capsule, which is agreement
#: manufactured by rounding.
MIN_PLACES = 6

#: Tabular files whose columns are a group the artifact defines.
TABULAR = {".csv", ".tsv", ".txt", ".dat"}

#: Delimiters tried, in order of how strongly they indicate a table.
DELIMITERS = [",", "\t", ";", "|"]

#: A column needs at least this many numeric entries before its mean means anything. Two
#: values have a mean that is no more constrained than either of them.
MIN_COLUMN = 3

#: Columns beyond this in one file are not read. A wide matrix dump is not a results table,
#: and indexing thousands of columns reintroduces the coincidence problem by volume.
MAX_COLUMNS = 60

#: Rows read from any one file. Enough for a results table; a bounded read keeps a scan over
#: a large artifact from turning into a load of it.
MAX_ROWS = 20_000

NUMERIC = re.compile(r"^[-+]?\d(?:,?\d)*(?:\.\d+)?(?:[eE][-+]?\d+)?$")


def _delimiter(sample: str) -> str | None:
    counts = {d: sample.count(d) for d in DELIMITERS}
    best = max(counts, key=lambda d: counts[d])
    return best if counts[best] >= 2 else None


def columns(path: pathlib.Path) -> dict[str, list[float]]:
    """Numeric columns of a tabular file, keyed by header where there is one.

    A file without a header row keys its columns by position, since a column's identity is
    what makes its mean a named quantity rather than an arbitrary grouping.
    """
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return {}
    head = text[:8192]
    delimiter = _delimiter(head.splitlines()[0] if head.splitlines() else "")
    if delimiter is None:
        return {}

    try:
        rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    except (csv.Error, ValueError):
        return {}
    if len(rows) < MIN_COLUMN + 1:
        return {}

    header = rows[0]
    numeric_header = sum(1 for cell in header if NUMERIC.match(cell.strip()))
    names = (
        [f"column {i}" for i in range(len(header))]
        if numeric_header > len(header) / 2
        else [cell.strip() or f"column {i}" for i, cell in enumerate(header)]
    )
    body = rows if numeric_header > len(header) / 2 else rows[1:]

    found: dict[str, list[float]] = {}
    for index, name in enumerate(names[:MAX_COLUMNS]):
        values = []
        for row in body[:MAX_ROWS]:
            if index >= len(row):
                continue
            cell = row[index].strip()
            if NUMERIC.match(cell):
                try:
                    values.append(float(cell.replace(",", "")))
                except ValueError:
                    continue
        if len(values) >= MIN_COLUMN:
            found[name] = values
    return found


def summarise(values: list[float]) -> dict[str, float]:
    """The aggregates a paper is likely to report over a column."""
    out = {
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "sum": math.fsum(values),
        "min": min(values),
        "max": max(values),
    }
    if len(values) > 1:
        out["standard deviation"] = statistics.stdev(values)
        out["standard error"] = statistics.stdev(values) / math.sqrt(len(values))
    return out


def derived(paths: list[pathlib.Path], root: pathlib.Path) -> dict[str, tuple[str, str]]:
    """Every column aggregate in the artifact, keyed by its printed form.

    The value maps to the file and the description of what it aggregates, so a confirmation
    reads `mean of column auc in results.csv` rather than asserting a bare match.
    """
    index: dict[str, tuple[str, str]] = {}
    for path in paths:
        if path.suffix.lower() not in TABULAR:
            continue
        relative = str(path.relative_to(root))
        for name, values in columns(path).items():
            for label, result in summarise(values).items():
                if not math.isfinite(result):
                    continue
                description = f"{label} of column {name!r} ({len(values)} rows)"
                index.setdefault(repr(result), (relative, description))
                for places in range(MIN_PLACES, 13):
                    index.setdefault(f"{result:.{places}f}", (relative, description))
    return index
