- **[citations] `citations lint --bib` reports an author list written as family names with no
  given names.** `author = {Bhaskar and Wettig and Friedman and Chen}` prints as "Bhaskar,
  Wettig, Friedman, and Chen." in the reference list, and five entries in one paper's
  bibliography were like that on the day it was submitted. `--authors` passed all five, because
  the four family names are the four arXiv:2406.16778 lists, in order, and family names are all
  that comparison reads. Nothing outside the file settles a missing given name, so the check
  sits in the offline mode beside the repeated keys and needs no network. A name that is one
  word, carries no comma and is not braced has no given part for a reference style to print;
  `{NASA}` and `{Open Science Collaboration}` are braced, which is how BibTeX is told a name is
  complete as written, so neither is a finding. `--bib` now reports both kinds under one exit
  code and one JSON document, each finding naming its kind.

- **[citations] A braced author is no longer split at an ` and ` inside its braces.**
  `{President's Council of Advisors on Science and Technology}` was read as two authors, the
  second of which is `Technology}`, and `{U.S. Food and Drug Administration}` as two more. Both
  `--bib` and `--authors` read names through the same splitter, so the second of those phantom
  authors counted against the registry's list as well.
