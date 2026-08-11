# citations

A library of quotations checked against the sources they came from.

Not a faster grep. The point is to accumulate quotations that have been verified against a
pinned artifact, so later work quotes from the library instead of from memory — which is a
different class of error than writing from recollection.

```bash
uv tool install citations      # or: pip install citations

citations init                 # a library here
citations verify               # do my quotations resolve in their sources?
```

## What verify reports

Five states, and the distinction between them is the design:

| | |
|---|---|
| `ok` | found verbatim in the pinned artifact |
| `loose` | matched on the alphanumeric skeleton — reported, never failed, because a skeleton match cannot tell `a - b` from `a + b` |
| `too-short` | resolves, but is short enough or truncated enough to verify a claim its source qualifies two words later |
| `no-source` | the artifact is not on disk. **Nothing was checked** |
| `missing` | the artifact was read and the text is not in it |

`missing` means *look at this*. It never means fabricated — a mirror-reversed scan or a broken
extraction produces the same signal, and a tool that accuses an author of invention on that
evidence is worse than no tool.

A run that checked nothing exits non-zero. A check that passes by examining nothing is the
failure this tool exists to prevent, and it is the failure it committed on its own first run.

## Where the library lives

```
$CITATIONS_HOME             explicit
./.citations/ walking up    this project's own, like .git
neither                     "run citations init"
```

Nothing is written to a directory you did not name. `citations` commits inside its own library
and never pushes.

## Other commands

```
citations resolve    backfill missing DOIs and arXiv ids — Crossref, then OpenAlex, then arXiv
citations build      rebuild records from the bibliographies of the papers that cite into it
citations lint       BibTeX correctness, borrowed from papis doctor
citations link       point pdfs/ at wherever the papers keep the artifacts
```

## Why the records are YAML

So `git diff` shows you what changed. A binary store cannot show you that a year silently moved
from 2021 to 2022, which is a real bug this found across one author's own papers.

MIT licensed. `docs/` carries the practices this came out of and the alternatives that were
rejected.
