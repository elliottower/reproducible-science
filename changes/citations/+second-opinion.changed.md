A `not found` on a paginated source consults the remaining readers before it stands. `not found`
is an accusation against the manuscript -- the source was read and the passage is not in it --
and one reader was making it.

`pdftotext -layout` preserves a page's visual geometry, so on a two-column paper it interleaves
the columns and shreds every sentence spanning the gutter. Measured on one such paper: 110 of
its 160 quotations read as absent under `-layout` and 157 resolve under pypdf, from a correctly
pinned source with nothing wrong with the quotations.

Whichever reader answers is recorded as a fallback naming the one that missed it, so a rescued
passage never reads like one the declared reader found. Where no reader finds the passage, the
detail names every reader that looked. The escalation is on the failure path alone: a passage
the first reader resolves still costs one extraction, and `ambiguous` is never escalated, since
a reader that merges columns could hide an occurrence rather than settle anything.
