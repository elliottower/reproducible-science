"""Where each line of an extracted text starts in its folded form, found in one pass."""

from __future__ import annotations

import time

from citations.verify import passage_fold
from claims.adapters.prose import line_starts


def test_each_line_starts_where_the_folded_text_has_it():
    raw = "First line\n\n  second   line\nhyphen-\nated word\nlast"
    folded = passage_fold(raw)
    starts = line_starts(raw, folded, passage_fold)

    assert folded == "first line second line hyphenated word last"
    assert [folded[at : at + 6] for at in starts] == [
        "first ",
        "second",
        "second",
        "hyphen",
        "ated w",
        "last",
    ]


def test_a_text_that_does_not_fold_line_by_line_has_no_starts():
    assert line_starts("one\ntwo", "something else", passage_fold) is None


def timed_starts(lines: int) -> tuple[float, list[int] | None, str]:
    raw = "".join(f"step {n}: loss 0.{n:05d}\n" for n in range(lines))
    folded = passage_fold(raw)
    started = time.perf_counter()
    starts = line_starts(raw, folded, passage_fold)
    return time.perf_counter() - started, starts, folded


def test_finding_line_starts_grows_linearly_with_the_number_of_lines():
    small, _, _ = timed_starts(20_000)
    large, starts, folded = timed_starts(100_000)

    assert starts is not None and len(starts) == 100_001
    assert folded.startswith("step 99999:", starts[99_999])
    # Five times the lines: about five times the time when linear, about 25 times when
    # quadratic, as the look-ahead that took 28 s on the larger input was. A ratio rather
    # than a time in seconds, so a slow runner or coverage tracing does not fail it.
    assert large / small < 12
