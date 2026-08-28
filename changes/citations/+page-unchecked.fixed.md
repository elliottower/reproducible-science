A page assertion the declared extractor cannot be asked about is reported rather than dropped.

A page is verifiable only where this module can request one page on its own terms, which means
no declared `extract_cmd`: an arbitrary program has no page flag, and asking `pdftotext` for
page 4 of a source whose author declared `detex` would run a PDF reader over something they just
said is not a PDF. That reasoning still holds. What did not hold was doing it in silence.

A record asserting `page: 3` under a declared `pdftotext -layout` had the assertion dropped and
nothing said so: 154 page assertions in one audited claim, where page 9999 on a three-page
document graded identically to the correct page. The new `page unchecked` warning does not change
a verdict; it makes the omission visible, which is the difference between a check that passed and
a check that never ran.

A plain-text source is exempt. It has no pages, so a page recorded against one is an inapplicable
field rather than an unverified assertion.
