# citations

Check that the passages you quote actually appear in the sources you cite, and keep a library of
the ones that do.

```bash
uv tool install citations      # or: pip install citations

citations init                 # a library here
citations verify --claims <dir>
```

## What it reports

```
2,940 quotes

  found         2,940
  not found         0

warnings
      213  short — the source may qualify this in the next clause
      155  normalized — matched after ignoring punctuation and spacing

all found.
```

Three results, and they are exhaustive:

| | |
|---|---|
| `found` | the passage is in the source |
| `not found` | the source was read and the passage is not in it |
| `unchecked` | the source could not be read, so no measurement was made |

Warnings are separate, because a passage can be found and still worth a second look. A quote
can be short enough that the next clause changes its meaning — `"We trained 50"` appears
verbatim in a paper whose sentence continues `"...and 5 refits each for 12 layered"`.

`unchecked` is neither a pass nor a failure. Only `not found` fails; `--strict` also fails on
unchecked, for CI.

`not found` means read the source. A mirror-reversed scan or a two-column extraction produces
the same signal as a passage that was never there.

## Where the library lives

```
$CITATIONS_HOME             if set
./.citations/ walking up    this project's own, the way git finds .git
the shared library          if you made one with citations init --user
none of those               it tells you to run citations init
```

Project-local by default, so running the tool inside a paper works on that paper and there is
no hidden global state. `citations init --user` makes one shared across projects; point at it
with `CITATIONS_HOME`.

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
