# citations

Check that the passages you quote actually appear in the sources you cite, and keep a library of
the ones that do.

```bash
uv tool install citations      # or: pip install citations

citations init
citations verify
```

## What verify reports

| | |
|---|---|
| `ok` | found verbatim in the pinned source |
| `loose` | matched ignoring punctuation and spacing. Reported, not failed — this cannot tell `a - b` from `a + b` |
| `too-short` | resolves, but is short enough that the source may qualify it in the next clause |
| `no-source` | the file is not on disk, so nothing was checked |
| `missing` | the file was read and the passage is not in it |

`missing` means read the source. A mirror-reversed scan, a two-column extraction, or an
image-only PDF all produce the same signal as a passage that was never there.

Quote enough text to carry its qualifiers. `"We trained 50"` resolves against a paper whose
sentence continues `"...and 5 refits each for 12 layered"` — a real case where a record claimed
fifty and the true number was five.

## Where the library lives

```
$CITATIONS_HOME             if set
./.citations/ walking up    this project's own, like .git
neither                     run citations init
```

Nothing is written to a directory you did not name. `citations` commits inside its own library
and never pushes.

## Other commands

```
citations resolve    backfill missing DOIs and arXiv ids from Crossref, OpenAlex and arXiv
citations build      rebuild records from the bibliographies that cite into the library
citations lint       BibTeX correctness, via papis
citations link       point pdfs/ at wherever your papers keep the files
```

## Records are YAML

So `git diff` shows what changed. A binary store cannot show you that a year moved from 2021 to
2022 — a real discrepancy this found between two of one author's own papers.

## Claude Code

`plugin/` is a Claude Code plugin that tells Claude when to reach for the CLI.

```bash
cp -r plugin ~/.claude/skills/citations
```

MIT licensed. `docs/` has the working practices this came out of.
