An extraction that fails is cached, where only a successful one was. `functools.lru_cache`
stores a value on a normal return and stores nothing when the call raises, so the cache around
`extract` memoized every reading it managed and none of the ones it could not, and a source no
extractor could read was re-attempted once per quotation rather than once per document.

Measured on a sixteen-claim corpus whose sources all declared an extractor that printed nothing:
2,210 poppler invocations for 14 unique artifacts, 158 times the work the corpus requires, and
21 minutes of wall clock of which 95% was the repeated subprocess. The same run now takes 14.6
seconds.

`reading_with` had the same shape and matters more, because the second-opinion path reaches it
on every `not found`: a document no reader could open was re-attempted by every reader, once per
quotation. `extract.cache_clear` and `reading_with.cache_clear` keep working -- the memoization
moved underneath them and the handles are delegated, since both were public and a caller
managing the cache should not have to know which function holds it.
