# citations

Check that the passages you quote actually appear in the sources you cite, and keep a library of
the ones that do.

## Install

```bash
pip install citations
```

## Quick start

```bash
citations init
citations verify --claims claims/
```

```
2,940 quotes

  found         2,940
  not found         0

warnings
      213  short — the source may qualify this in the next clause
      155  normalized — matched after ignoring punctuation and spacing

all found.
```

## Commands

| Command | What it does |
|---------|-------------|
| `citations init` | Create a library here |
| `citations verify` | Do the quotations resolve in their sources? |
| `citations resolve` | Backfill missing DOIs and arXiv ids |
| `citations build` | Rebuild records from bibliographies |
| `citations lint` | BibTeX correctness, via papis |
| `citations link` | Point pdfs/ at the papers' artifacts |

## Verify output

Three results, and they are exhaustive:

| Result | Meaning |
|--------|---------|
| `found` | The passage is in the source |
| `not found` | The source was read and the passage is not in it |
| `unchecked` | The source could not be read, so no measurement was made |

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
no hidden global state.

## What a claim file looks like

One file per source, in the paper's `claims/` directory. `citations verify --claims claims`
reads all of them.

```yaml
source:
  citation: schiffman2026             # the bibkey
  local: reference/schiffman2026.pdf  # what gets read
  sha256: 3f9a…                       # which bytes were read
  extract_cmd: pdftotext

claims:
  orthogonal-cores:
    statement: 'Cores meeting equivalent causal criteria sit at principal angles of 75-90 degrees.'
    quotes:
      - exact: 'and principal angles ranged'
        section: 'body'
```

`statement` is yours; `exact` is theirs. The tool checks the second only, so a `statement` that
overreaches its quote is for review to catch — the command cannot.

## Records are YAML

So `git diff` shows what changed. A binary store cannot show you that a year moved from 2021 to
2022 — a real discrepancy this found between two of one author's own papers.

## Claude Code

`plugin/` is a Claude Code plugin that tells Claude when to reach for the CLI.

```bash
/plugin marketplace add elliottower/citations
/plugin install citations@citations
```

For all three reproducible-science tools in one plugin (citations + [prereg](https://github.com/elliottower/prereg) + [results](https://github.com/elliottower/results)):

```bash
/plugin marketplace add elliottower/reproducible-science
```

MIT licensed. `docs/` has the working practices this came out of.
