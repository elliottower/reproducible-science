---
name: citations
description: Verify that quotations resolve in the sources they cite, and manage a library of verified quotations. Use before quoting a paper, when adding a citation, when asked to check whether a quote is real, when a bibliography needs DOIs backfilled, or when checking whether the authors and years in a reference list match the records their identifiers resolve to. Requires the `citations` CLI (`uv tool install citations`).
---

# citations

A library of quotations checked against the sources they came from.

## The rule that matters

**Never quote a source from memory. Look it up.**

Every fabricated quotation comes from generating text that sounds like what a paper says instead
of reading what it says. If a quotation is in the library it has been checked against a pinned
artifact; if it is not, check it before using it.

## Commands

```bash
citations verify                    # do the quotations resolve in their sources?
citations verify --claims <dir>     # check a paper's claims/ directory
citations verify --strict           # also exit 1 on unchecked, indeterminate or ambiguous, for CI
citations audit                     # does the stored metadata match the registry record?
citations audit --bib refs.bib      # check a BibTeX file directly
citations resolve                   # backfill missing DOIs and arXiv ids
citations init                      # create a library here
citations lint                      # BibTeX correctness
citations lint --claims <dir>       # pinned sources that git tracks
citations fetch --claims <dir>      # download the pinned sources, keeping only matching bytes
citations pin <file> --url <URL> --id <id> --quote "<passage>"   # pin against a web page
```

## Pinning a source and a quotation

**Download the source and keep the file.** `verify` reads the file a claims file names under
`local`. A title in a chat answer or a search result is not a source: no file is behind it, so
nothing can be pinned and nothing checked.

**Pin the quotation before writing the sentence that quotes it.**

```bash
citations pin claims/<source>.yaml --id <id> --quote "<passage>"
```

`pin` resolves the passage against the pinned file first and writes nothing where it does not
resolve, so the sentence is written from a passage already found in the source.

**A web page is pinned by its URL.** `citations pin <file> --url <URL> --id <id> --quote
"<passage>"` reads the page from the `retrieved` library, which already holds a page fetched
earlier in the session where the capture hook is installed, and captures it where the library
holds none. It writes the claims file with the URL, the sha256, the retrieval time and the
path of the bytes inside the library; the page is never copied into the project. Never save a
page by hand and write its path and digest. `--recapture` fetches the page again, and the new
retrieval goes in a new claims file: a claims file pins one retrieval. Where `retrieved`
refuses the URL, or the server answers with an error, nothing is written and the reason is
printed; report it, and never work around a refusal. An HTML page is checked as the text it
shows: tags dropped, entities decoded, `<script>` and `<style>` left out, and a table row
written with ` | ` between its cells. The claims file names that reading as `extractor:
html-text`. Needs `pip install "citations[web]"`. In a clone whose library lacks the page its
quotations are `unchecked`, and the reason names the retrieved store.

**Give the bibliography entry a DOI or an arXiv id.** A record is keyed by its entry's DOI,
else its arXiv id, else a hash of the title and first author. An entry with neither becomes a
title-hash record, and a second record for the same work once another bibliography cites that
work with an identifier. `citations resolve` backfills a missing one. Write `url:` or `doi:`
under `source:` in the claims file as well: `pin` says when neither is there, and without one
`citations fetch` has nowhere to ask.

**`unchecked` is not `found`.** It means nothing could read the source, so no measurement was
made: the file is not at the path the claims file names, the extractor is not installed or was
refused, or it produced no text. Where other quotations were read, an `unchecked` one does not
fail the run without `--strict`, so a run can exit 0 over quotations nothing read. A draft with
unchecked quotations has not been verified. Report the count and the reason printed beside
each.

**The usual reasons a quotation does not resolve**, few of them a misquotation:

- The text layer dropped a character: a minus sign, an en dash, a subscript.
- A hyphen falls at a line break, where folding removes it whether or not the word has one.
- The reader is the wrong one: `pdftotext -layout` interleaves the columns of a two-column page.
- A paraphrase is stored under `exact`. `statement` holds your sentence, `exact` the source's.
- Text is left out of the middle. `exact` takes no ellipsis, and the result is `not found`.
- The passage is from another version of the work. A pin names bytes, so a passage taken from
  the journal article is looked for in the preprint where the preprint is the file pinned.
- The file is not the source: a `.pdf` that is a login page or a challenge page fails under
  every reader.

Read the source in each case, and never shorten a quotation to the part that matches.

**A source behind a challenge page or a paywall was not obtained.** Record it so: its address
as `url:` under `source:` and no file at `local`, and its quotations read `unchecked`. Never
save the page that was served as the source. The tell is that the file is HTML and not a PDF,
which `file <path>` says in one line. Never work around the block. A copy obtained with access
can be placed at the path the claims file names, and `verify` checks it against the pin.

## Reading the output

Five results, exhaustive:

| | |
|---|---|
| `found` | the passage is in the source |
| `not found` | the source was read and the passage is not in it |
| `indeterminate` | under `--triangulate`, readers that read the source disagree about whether it is in it |
| `ambiguous` | the passage occurs more than once and the record does not say which occurrence |
| `unchecked` | the source could not be read — **no measurement was made** |

Only `not found` fails a run. `indeterminate`, `ambiguous` and `unchecked` are neither a pass
nor a failure, and `--strict` fails on all three.

Warnings sit on their own axis. A passage can be `found` and still carry one: `truncated` (begins or stops
mid-word or mid-number and the source continues it), `short` (the source may qualify it in the next
clause), `normalized` (matched ignoring punctuation), `page` (found, but not where the record says).

**`truncated` is the one to stop for.** `"an accuracy of 0.9"` is genuinely present in a paper
reporting **0.95**, so it passes every other check while misstating the result. Length is not the
tell — a long quote ending one digit early is the convincing version — so `short` will not fire.
Extend the quote through the end of the number or the word.

**`unchecked` is not a pass.** Do not describe a claim as verified on the strength of it.

**`not found` means read the source.** A broken extraction reads the same as a passage that
was never there.

**A run with nothing to check exits non-zero.** The path is wrong, not everything passing.

**Check which library you are on before believing a clean run.** The library resolves in order:
`$CITATIONS_HOME`, else `.citations/` found by walking up from the current directory, else the
shared one from `citations init --user`. So the same command run one directory over can verify a
different set of records and still report `all found`.

## Keep source texts out of git

A claims file pins its source by a `sha256` and names where it came from, so no check needs
the source committed. **Keep source texts on disk and out of git**: ignore the folder they sit
in before the first `git add`. A committed source is somebody else's text published with the
repository, and taking it out later means rewriting every commit that held it.

- The record carries the digest and the address: `sha256`, and a `url`, `doi` or arXiv id.
  `citations fetch --claims <dir>` downloads each source again and keeps only bytes that match
  the pin.
- In a clone that holds no sources, `unchecked` with `file not found` is the expected report.
  Run `citations fetch`, then `verify`.
- `citations verify` and `citations lint --claims <dir>` list the pinned sources git tracks,
  and `citations pin` says when the source it just read is tracked or covered by no ignore
  rule. Each is a warning: it fails nothing, with or without `--strict`, and no command edits
  `.gitignore`.
- `citations lint --claims` with no directory reads `claims` in the working directory, or the
  nearest one above it in the same repository. `prereg freeze` asks this way and refuses to
  freeze while any is tracked, unless given `--allow-tracked-sources`; `repro audit` reports
  the count as `N sources tracked by git`.
- `git rm --cached` takes a source out of the index and out of no commit. Until the removal is
  committed the last commit still holds it: `lint --claims` lists it as `in HEAD`, `verify`
  names it, and `prereg freeze` is still refused.
- Text under a licence that allows redistribution is the author's to commit. Record the licence
  beside it.

## Quote enough text

`"We trained 50"` resolves against a sentence that continues `"...and 5 refits each for 12
layered"`. Quote through the qualifiers; never end a pin mid-clause.

## A resolving identifier says nothing about the metadata beside it

`verify` checks quotations. `audit` checks the reference itself: do the authors, year, volume
and pages stored beside a DOI match the record that DOI resolves to?

The failure is a real DOI carrying an invented author list. It resolves, the link is live, and
the quotations pinned to it are genuine, because the DOI does point at the right paper — the
names written beside it belong to someone else. A DOI checker passes it, a link checker passes
it, and `citations verify` passes it. Found in one 75-entry bibliography: four author lists
belonging to nobody on the cited paper, one PMID resolving to an unrelated article in another
field, and four lists stopping early with no `and others` marker, which is invisible because a
truncated list looks complete.

Never write an author list from memory. If a reference was assembled without reading the
record, run `citations audit` before it ships.

## Pin what you rely on, not only what you quote

A sentence that paraphrases a source makes a claim about that source, and the claim can be
wrong in every way a misquotation can be wrong. `pin` exists for both. `--says` records your
characterization of a passage and `--whose` owns it, so the claims file holds the source's own
words beside the reading you took from them, and `verify` checks that the words are really
there. Your manuscript never has to reproduce the passage.

The failure this closes is quiet. A reviewer asks where a cited paper says what you attribute
to it, and the answer is a PDF nobody has opened since the sentence was written. Pinning makes
the answer a file.

So pin a passage whenever a sentence rests on one:

- a definition or framework taken from a source and applied in your own setting
- an identity or prior result you attribute to someone ("X equals Y (Author, year)")
- a dataset's own description of what it contains, where your eligibility rule depends on it
- a method you say another paper used, especially where you then depart from it
- a number you quote from a paper rather than compute

Thirty paper repositories in this project keep a `claims/` directory. The quotations in them
are mostly passages the manuscripts never print: eight checklist items behind one sentence
about what a checklist does not ask for, a definition behind a term used without quoting it.
That is the normal case, not an edge case.

The reading that causes trouble is "nothing is quoted here, so there is nothing to pin." A
manuscript can quote no one and still make thirty claims about what thirty papers say.

## When to reach for this

- Before writing any sentence that quotes a paper, or that rests on one
- When adding a citation, to pin the artifact and its sha256
- When asked whether a quotation is real
- When a bibliography has entries with no DOI or arXiv id — `citations resolve`
- Before a bibliography ships, and after any reference was written out by hand — `citations audit`
- In CI, as `citations verify --strict` and `citations audit --strict`

## What it will not do

It cannot catch misinterpretation. A real, resolving quotation attached to a claim it does not
support passes every check here, and `audit` compares a reference against a registry rather
than against the paper it is cited for. Verification is not comprehension.

## Where this sits

Four tools guard four moments, and each is weak without the others. A frozen plan over
unsealed inputs proves nothing; a sealed run whose numbers never reach the manuscript proves
nothing either.

| moment | tool | what it fixes |
|---|---|---|
| before you run | `prereg freeze` | the plan cannot be rewritten around the result |
| before you compute | `results seal` | the inputs are what you say they were |
| after a run | `results run` | the outputs are recorded and hashed |
| writing a number | `results claim` | the number names the run behind it |
| writing a quotation | a `claims/` entry | the passage is in the source |
| before submitting | `prereg check`, `results verify`, `citations verify` | nothing drifted |

Every tool named here is installed by `uv tool install reproducible-science`, so the commands
above are available whatever plugins are present.

Each tool also ships its own plugin, adding a hook that speaks when its moment passes
unrecorded and a `-check` command. Those commands exist only where the matching plugin is
installed; the CLI calls in the table always work.
