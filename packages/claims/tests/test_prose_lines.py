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


def test_a_log_of_a_hundred_thousand_lines_takes_well_under_a_second_per_ten_thousand():
    raw = "".join(f"step {n}: loss 0.{n:05d}\n" for n in range(100_000))
    folded = passage_fold(raw)
    started = time.perf_counter()
    starts = line_starts(raw, folded, passage_fold)
    took = time.perf_counter() - started

    assert starts is not None and len(starts) == 100_001
    assert folded.startswith("step 99999:", starts[99_999])
    # Linear: the quadratic look-ahead took about 28 s on this input.
    assert took < 5
