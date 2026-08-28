A quotation is checked by counting its occurrences, where it was checked by testing whether the
document contained it at all. A quotation points at one passage; a pointer resolving to three of
them has identified none, and the page and section attached to it are then asserted about a
passage nobody picked out. A passage occurring more than once is now `ambiguous`, a fifth state
distinct from `indeterminate` -- the extractors disagreeing about what a document holds asks for
a better reader, while a repeated passage asks for an anchor the author writes.

`Quote` gains `prefix` and `suffix`, the W3C Web Annotation `TextQuoteSelector` neighbours. They
are joined to the passage and counted in its place where it repeats, and are consulted nowhere
else. Both default to empty, so a quotation that resolves uniquely is checked exactly as before.

Counting respects token boundaries: `the catalog` inside `the catalogue` is a shared prefix and
not the document saying it twice.
