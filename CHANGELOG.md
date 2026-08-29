## 0.4.0 — 2026-08-29

### citations

#### Fixed

- **[citations] A `.tex` source is read with `detex` rather than `pdftotext`.** A `.tex` with no declared `extract_cmd` got the PDF reader, which answered `Syntax Error: Couldn't read xref table`, and every quotation in it graded `unchecked` until an author declared `detex` by hand — for the commonest manuscript format in this domain, with `detex` already among the default extractors. ([#36](https://github.com/elliottower/reproducible-science/pull/36))
- **[citations] An `ambiguous` outcome is printed.** The checker could return it and the report had no column for it, so it was counted and never shown: the table stopped summing to the number of quotations above it, and a run whose only problem was ambiguity read as clean. ([#39](https://github.com/elliottower/reproducible-science/pull/39))
- **[citations] `citations build` keeps the citations of a paper whose bibliography it could not read.** Records are rewritten whole from the bibliographies, so a paper contributing none — an import with no repository on this machine, a path that moved — lost its `cited_by` entry from every record another paper also cites. Measured on this repository's own library, one such paper bled seven citations per rebuild, silently. ([#40](https://github.com/elliottower/reproducible-science/pull/40))
- **[citations] A rebuild keeps a pinned artifact it cannot repin.** `local` and `sha256` name the copy that was read and hashed, and both were filled only from a paper's own directories — so a pin the library established itself, for a work no paper's `claims/` covers, was dropped on every rebuild without being reported. ([#43](https://github.com/elliottower/reproducible-science/pull/43))
- **[citations] The command list matches the commands.** Four CLIs documented their subcommands in a module docstring that nothing compared to the parser: `citations` advertised a `bib` command that has never existed and omitted `pin` and `projects`, `prereg` omitted `setup`, `results` omitted `reanchor`, and `repro` omitted four.
- A page assertion the declared extractor cannot be asked about is reported rather than dropped.

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
- An extraction that fails is cached, where only a successful one was. `functools.lru_cache`
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
- An extractor that writes a file *beside* the source is reported. The existing check hashes the
  artifact before and after, which catches a renderer that overwrites the file it was given and
  cannot see one that writes a sibling -- the commoner shape, since `pdftotext -layout X.pdf` with
  no trailing `-` writes `X.txt` and prints nothing.

  Thirty-two such files accumulated in one audited repository over three weeks, unnoticed because
  the directory is gitignored. Nothing was corrupted there, but a `.txt` pinned as a source beside
  a same-stem PDF would have been silently replaced by this tool's own output, and every quotation
  would then have resolved against text the checker wrote.

  Narrowed to files sharing the source's stem rather than watching the whole directory, so an
  unrelated process writing there cannot trip it. Nothing is deleted: the file is named in the
  report and left where it is.
- The corpus size behind `readers.PREFERRED` is the one the measurement recorded. The README and
  `readers.py` justified preferring pypdf over pdfplumber with "1,792 passage checks", a number
  that appears in no artifact: `research/pdf-readers/results.json` records 1,593 checks over 80
  documents for the quotations corpus and 458 over 132 for the sampled one, and `verify.py` cited
  1,593 for the sibling claim in the same commit. Both now read 1,593, and both carry the
  agreement rates the artifact holds -- 92.7% against 90.2% -- so the sentence can be checked
  rather than believed.

  The preference itself was correct and is unchanged. What was wrong was the evidence cited for
  it, which is the failure these tools exist to catch.
- `fold` drops combining marks instead of composing them. A renderer typesets `naïve` as a dotless
  i carrying a combining diaeresis, which is how LaTeX writes it, while the quotation is typed with
  the precomposed letter; composing leaves those two different strings and the passage reads as
  absent. Seven quotations from one paper failed on that alone. The dotless `ı` and the dotted
  capital `İ` are mapped explicitly, since no normalization form reaches either.

  `skeleton` absorbs a hyphen joining two word characters, at least one a letter, together with any
  whitespace after it -- `prefix-matching` against `prefixmatching`, `non- sparse` against
  `nonsparse`, `pythia-1.4b` against `pythia1.4b` -- and an underscore, which is a subscript the
  extractor has already flattened. The bounds are the point: a minus sign is preceded by a space or
  by nothing, never by a word character, so `-0.42` and `0.42` stay distinct, and `5-3` is left
  alone where a range and a subtraction are indistinguishable.

#### Changed

- **[citations] A claims file states whose reading a characterization is, and the report says how many were not measured.** `verify` resolves the strings in `quotes` against the pinned bytes; nothing reads `statement`. A file whose quotation is exact and whose statement overreaches passed every check, and the report said nothing about the second object. `Interpretation` carries a required `whose`, and the report counts readings, those attributed to a party other than the source, and those marked contested — all as unchecked, because this package cannot measure them. ([#30](https://github.com/elliottower/reproducible-science/pull/30))
- A `not found` on a paginated source consults the remaining readers before it stands. `not found`
  is an accusation against the manuscript -- the source was read and the passage is not in it --
  and one reader was making it.

  `pdftotext -layout` preserves a page's visual geometry, so on a two-column paper it interleaves
  the columns and shreds every sentence spanning the gutter. Measured on one such paper: 110 of
  its 160 quotations read as absent under `-layout` and 157 resolve under pypdf, from a correctly
  pinned source with nothing wrong with the quotations.

  Whichever reader answers is recorded as a fallback naming the one that missed it, so a rescued
  passage never reads like one the declared reader found. Where no reader finds the passage, the
  detail names every reader that looked. The escalation is on the failure path alone: a passage
  the first reader resolves still costs one extraction, and `ambiguous` is never escalated, since
  a reader that merges columns could hide an occurrence rather than settle anything.
- A quotation is checked by counting its occurrences, where it was checked by testing whether the
  document contained it at all. A quotation points at one passage; a pointer resolving to three of
  them has identified none, and the page and section attached to it are then asserted about a
  passage nobody picked out. A passage occurring more than once is now `ambiguous`, a fifth state
  distinct from `indeterminate` -- the extractors disagreeing about what a document holds asks for
  a better reader, while a repeated passage asks for an anchor the author writes.

  `Quote` gains `prefix` and `suffix`, the W3C Web Annotation `TextQuoteSelector` neighbours. They
  are joined to the passage and counted in its place where it repeats, and are consulted nowhere
  else. Both default to empty, so a quotation that resolves uniquely is checked exactly as before.

  Counting respects token boundaries: `the catalog` inside `the catalogue` is a shared prefix and
  not the document saying it twice.

#### Added

- - **[citations] A PDF is readable without poppler, and every result names what read it.**
    `verify` shelled out to `pdftotext -layout` and returned `unchecked` where the binary was
    absent, so `pip install citations` could not check a PDF at all. Where poppler is missing or
    fails on a document, the chain now falls through to pypdf or pdfplumber and records the
    substitution as a fallback with its reason, so a result never rests silently on an extractor
    other than the one it names. A source declaring `extract_cmd` does not enter the chain: its
    author named the program that produces the text, so it runs or the check is `unchecked`.
    `citations verify --triangulate` asks every installed reader instead of one and reports
    disagreement as `indeterminate`, a fourth outcome that leaves the question open rather than
    asserting the passage is absent — extractors disagreeing is a fact about the readers, and
    `not found` is an accusation against the manuscript. ([#14](https://github.com/elliottower/reproducible-science/pull/14))
- - **[citations] A claims file's `extract_cmd` is read, and the report says what ran.** The
    field was declared on the model and documented in the claim-file example while
    `verify.extract` hardcoded `pdftotext -layout`, so a `.tex` manuscript reached a PDF reader
    and graded `unchecked` for every sentence in it. A source declaring `extract_cmd` is now
    read by the command it names: the source path replaces `{}` or is appended, and what the
    command prints to stdout is what the quotations resolve against. Every result carries the
    extractor and a sha256 of the text it produced, since a pin establishes that the bytes did
    not change and nothing about how they were read. The command is never handed to a shell —
    the declared string is split into a program and arguments — and only `pdftotext` and `detex`
    run unasked; anything else needs `citations verify --allow-extractor NAME`, written by
    whoever runs the check rather than by whoever wrote the file. A refused command and an
    uninstalled one are both `unchecked` and say which they are; neither makes the passage
    absent. ([#16](https://github.com/elliottower/reproducible-science/pull/16))
- A fetched document now records whether its length was checked against the extent Paperclip
  declared for it, on `Document.extent_verified` and in the `paperclip:` block a claims file
  carries. Where `tail -n 1` declares no last line the completeness check cannot run, and
  `lines` is then counted from what arrived rather than confirmed against what the source said
  it should be; the two cases were previously indistinguishable in the record.

  The field defaults to false, so anything that does not set it reads as unverified rather than
  claiming a check nothing performed. ([#18](https://github.com/elliottower/reproducible-science/pull/18))
- `citations coverage` asks the question `verify` cannot: is every quotation in the manuscript
  pinned at all? `verify` reads the claims files and takes no manuscript, so a quotation added to
  the paper and never pinned has no record, is checked by nothing, and leaves the report clean.

  ```console
  citations coverage paper/draft.tex --claims claims [--strict]
  citations coverage paper/draft.tex --claims claims --attribute
  ```

  Outcomes are `covered`, `uncovered` and `unresolvable`, reported separately rather than as a
  pass or a fail: a quotation too short to distinguish from noise, or one whose neighbouring
  source would not open, is undecided and not a defect in the manuscript. `--strict` fails on the
  undecided ones too, matching `verify`.

  `--attribute` additionally checks each quotation against the artifact of a source cited near it,
  which catches a passage credited to the wrong paper. It never reports a misattribution when any
  neighbouring source could not be read: the passage may belong to the one that would not open. ([#22](https://github.com/elliottower/reproducible-science/pull/22))
- **[citations] `citations pin` writes a quotation into a claims file and refuses one the source does not contain.** A claims file is written by hand and read by `verify` afterwards; between those two moments sat a passage transcribed from a viewer whose ligature or line-wrapped hyphen differs from what the extractor produces. That was reported later, over a corpus, against a file nobody had open. It is now refused at the moment of writing. ([#31](https://github.com/elliottower/reproducible-science/pull/31))
- **[citations] `citations projects` reports which project names nothing answers to, and `citations tags` groups records against a declared vocabulary.** Ninety records named `evaluation-scope` hours after that repository was renamed and nothing reported it, because `cited_by` is a free-text key no check compared against the projects that exist. Tags are declared on a paper in `papers.yaml` and reach records through `cited_by`, so a work a paper cites tomorrow carries them without anything being re-run. ([#38](https://github.com/elliottower/reproducible-science/pull/38))
- **[citations] A record can name the citation key a new bibliography should use.** `cited_by` records what each paper actually writes and those diverge honestly, since a key is part of a paper's own source. Naming the divergence without naming a winner left the reader to pick one, which is how the divergence started. ([#41](https://github.com/elliottower/reproducible-science/pull/41))
- - **[citations] `citations add` writes an entry into a `.bib` and refuses a key the file
    already has.** Appending by hand put a duplicate key in a paper's bibliography twice in one
    session. BibTeX's answer to a repeated key is non-fatal -- it reports `Repeated entry`,
    keeps the copy defined first, skips the second and writes a `.bbl` without it -- so the
    entry just added never reaches the reference list and the failure surfaces as `Citation
    undefined` warnings that name nothing. `add` takes the entry from a file, from standard
    input, or fetched by `--doi` or `--arxiv`; a fetched entry is shown before it is written and
    carries every author the registry lists, never `and others`. A repeated key exits non-zero,
    prints both entries side by side and writes nothing, with case folded because BibTeX folds
    it. The write is read back before it is reported, and the original bytes go back if the file
    does not parse as what it parsed as before plus one entry. `citations lint --bib <file>`
    asks the same question of a file already written and needs neither papis nor a library.
- A `not found` says where the passage stopped matching, and what the source reads there.

  `not found` is an accusation against the manuscript: the source was read and the passage is not
  in it. It is usually wrong, and the cause is usually one character the document's text layer
  dropped -- a minus sign, an en dash, a hyphen falling on a line break where `fold`'s
  de-hyphenation removes a real one. Finding that meant a binary search for the longest prefix of
  the quotation the document still contains, done by hand, three times in one corpus.

  `divergence(quote, text)` does that search, and the report shows both sides at the point they
  part:

  ```text
  the first 155 characters are in the source and the rest is not
        quoted: ...tionality, e.g. vec('king') - vec('man') + vec('woman') = vec(
        source: ...tionality, e.g. vec('king') vec('man') + vec('woman') = vec('q
  ```

  with the repair named: split the quotation into adjacent fragments either side of the missing
  character, never truncate it to the part that matches, because a truncated quotation resolves
  and says something its source does not.

  Reported only where the prefix is substantial -- forty characters, or half the quotation. A
  shorter one matched by coincidence, and pointing at where it ran out sends a reader to a passage
  the quotation was never taken from. `packages/citations/README.md` collects the four causes.

### prereg

No significant changes.

### results-cli

#### Added

- **[results-cli] `results seal` accepts a directory and records it as a tree.** A dataset is a directory, so sealing one meant naming every file it contained, and a file added afterwards was simply absent from the record with nothing to notice. The seal looked complete and was not. A tree digest is order-independent and covers every path, and `verify` re-derives it the way it was recorded. ([#37](https://github.com/elliottower/reproducible-science/pull/37))
- **[results-cli] `results verify` says when the ledger is not in history.** `citations` reports a record that is not committed, because a pin nobody else can read is not evidence anyone can appeal to; `results` makes the same promise about its ledger and said nothing. Reported after the chain verifies, never blocking. ([#45](https://github.com/elliottower/reproducible-science/pull/45))

### reproducible-science

#### Fixed

- **[repro] `repro verify` no longer prints a blank line under a regeneration section that said
  nothing.** The separator was printed whenever a manifest declared a regeneration, and the
  ordinary state — not requested, since regeneration runs only under `--regenerate` — is the one
  state the section says nothing about. ([#26](https://github.com/elliottower/reproducible-science/pull/26))
- **[reproducible-science] `repro check` finds a paper's claims where papers keep them, and tells `citations` where they are.** A project holding sixty-one pinned quotations at `paper/prior_art/claims` was told no tool applied to it, because detection looked only at the repository root. A project with `claims/` at its root fared worse: the check ran `citations verify` with no claims directory, which reports nothing to check and exits 2, so it was reported as FAILED. ([#44](https://github.com/elliottower/reproducible-science/pull/44))
- **[reproducible-science] The cross-tool report names the claim it is about.** `results` records a claim's text under `claim`; this read `claim_id` and then `id`, neither of which it has ever written, so every claim printed as `?`. The tests wrote `claim_id` themselves, so the reader agreed with the fixtures and neither had to agree with the writer.

#### Changed

- **[reproducible-science] A tool is detected by what it can act on, not by a directory name.** `claims` is an ordinary word: a Python package and a knowledge-graph registry were both read as citations projects and then failed for holding no quotations. `prereg check` looks for a file named `PREREG.md`, while detection looked for a directory named `preregs`, so a directory of hand-named plans was reported as a project whose registrations were broken. An empty directory no longer counts as use. ([#45](https://github.com/elliottower/reproducible-science/pull/45))

#### Added

- **[repro] `repro demo` writes a worked example and runs the real workflow over it.** The first
  five minutes previously required reading the specification to find out what a manifest is for.
  `repro demo` scaffolds a self-contained project — twelve paired measurements, a stdlib analysis
  seeded so the same numbers come out on every machine, a manuscript stating one of them, and a
  `pin.py` that writes the manifest — then drives `results init`/`seal`/`run`/`claim` and
  `repro verify` over it, printing each command and what it actually returned.

  It then breaks the project twice, because a walkthrough where everything passes shows nothing
  about what the report keeps apart. A word no assertion reads is edited: every assertion still
  holds, the run fails on the pin alone, and the two decisions over that file come back marked
  non-authoritative. The manifest is re-pinned, the number the manuscript reports is changed, and
  the manifest re-pinned again — so the pin is clean and the comparison is the only thing left to
  fail. Both edits are restored, and the directory is left verifying, with a README naming three
  more failures worth producing by hand.

  Offline throughout, and it refuses a directory that already holds files unless `--force` is
  given, which removes only the files the demo itself writes. ([#26](https://github.com/elliottower/reproducible-science/pull/26))
- **[reproducible-science] `repro` runs the four tools, and `repro check` runs the ones a project uses in one pass.** Each tool keeps its own command; the delegation is a spelling. What only exists here is one pass over a project, one report and one exit code across every tool it actually uses, in place of four commands each with its own idea of a clean run. A tool the project does not use is reported as unused rather than as passing. ([#35](https://github.com/elliottower/reproducible-science/pull/35))

### provenance-core

#### Fixed

- `gitref` now runs git against the directory the caller names. Git resolves its repository from
  the environment before the working directory, so `cwd` alone never named one: under any git
  hook, which exports `GIT_DIR`, `commit(path)` and `is_dirty(path)` answered for whatever
  repository invoked the process. `repro.provenance.of_tree` is built on those calls, so a
  provenance record written from a hook named the wrong repository's commit and dirty state.

  Only the variables that relocate git are dropped -- `GIT_DIR`, `GIT_WORK_TREE`,
  `GIT_INDEX_FILE` and the rest of `gitref.REDIRECTS`. `GIT_SSH_COMMAND`, `GIT_COMMITTER_DATE`
  and the other variables that configure git once it knows where it is are untouched, and a
  caller passing no `cwd` still inherits everything. `gitref.clean_env()` exposes the same
  environment to callers that run git themselves.

  `results.timeline.freeze_timestamp` used `git -C`, which is a directory change and is outranked
  the same way; it now goes through `gitref`. ([#20](https://github.com/elliottower/reproducible-science/pull/20))

## 0.3.1 — 2026-08-26

Four corrections to `citations`, all of them defects introduced by the `extract_cmd` support
that shipped hours earlier in 0.3.0. Each was found by running the new code over real claim
sets, and each made a source unverifiable rather than merely awkward.

### Fixed

- **[citations] A source declaring that it needs no extractor was refused as a program named
  `none`.** `paperclip.source_block` writes `extract_cmd: none` for a pinned text artifact,
  because naming an extractor would claim a step that never ran; `verify` then read that as a
  command, refused it, and advised `--allow-extractor none` — running a program that does not
  exist. Every source written by `citations resolve --via paperclip` and `citations
  import-paperclip` came back `unchecked` in 0.3.0. The declaration is now recognized, and
  matched on its first word so the reason an author writes beside it (`none -- Markdown is read
  directly`) is read as the declaration rather than as a command. ([#24](https://github.com/elliottower/reproducible-science/pull/24))
- **[citations] A passage separated by U+2010 HYPHEN read as absent from a document containing
  it.** `fold` normalized the em dash, the en dash and the minus sign but not U+2010, which is
  visually identical to the ASCII hyphen and is what publishers emit: a source reading
  `patients‐in‐waiting` did not match a quotation typed with the ASCII hyphen, and the result was
  `not found` — an accusation against the manuscript — for a quotation that is verbatim correct. ([#24](https://github.com/elliottower/reproducible-science/pull/24))
- **[citations] An extractor that wrote to the file it was given damaged the artifact silently.**
  A declared `extract_cmd` is an arbitrary program handed a path, and nothing stopped it writing
  where it read: a renderer whose output filename matched its input overwrote the bytes the pin
  names, and the pin then failed against a file the checker itself had damaged. `verify` reads
  and never writes, so the artifact's digest is now taken before and after a declared command
  runs and a change is reported as a defect in the command. ([#24](https://github.com/elliottower/reproducible-science/pull/24))
- **[citations] A declared command that printed nothing reported `no text extracted`,** which is
  what a document holding no text also reports — the two facts the three-outcome model exists to
  keep apart, given one message. An empty stdout from a command that exited 0 now says so, and
  where the command is `pdftotext` without a trailing `-` it names that: `pdftotext FILE` writes
  `FILE.txt` and prints nothing, which is how ten sources in one claim set read as textless. #
  Changelog Every package in this workspace carries the same version and is released on the same
  day, so one file covers all four. Entries are scoped with a `[package]` prefix; unprefixed
  entries apply to the workspace as a whole. ([#24](https://github.com/elliottower/reproducible-science/pull/24))

## 0.3.0 — 2026-08-26

Corrections come first. Two of them changed what the tools reported: a confirmatory claim was
ordered against an exposure by comparing timestamp *strings*, so the answer depended on the
committer's time zone, and a provenance record written from inside a git hook named the wrong
repository entirely. A third, under Changed, is not a defect but will move results: a claims
file's `extract_cmd` was accepted and ignored, and is now run.

### Fixed

- **A release could ship packages pinned to different sibling series, and neither `bump` nor
  `check` could see it.** `scripts/versions.py` located the dependency array with a pattern
  ending at a line-initial `]`. That matched neither of the two forms the manifests actually use
  reliably: in `prereg`, a single-line array with no later array to close on, it did not match at
  all, so `bump 0.3.0` moved every package's version and left `prereg` requiring
  `provenance-core>=0.2,<0.3`; in `citations`, it ran past the array's own bracket to the one
  closing `classifiers`. `check` read the same way and reported lockstep. The array's end is now
  found by balancing brackets, and the wheel install that caught it is covered by a test. ([#23](https://github.com/elliottower/reproducible-science/pull/23))
- **[results] A freeze and an exposure were compared as strings, so the ordering depended on the
  committer's time zone.** `--frozen-at` resolved a commit through git's `%cI`, which carries a
  local UTC offset, and compared it with the ledger's UTC timestamp using `<` on the two strings
  — comparing the offsets rather than the instants. It passed on a machine four hours behind UTC,
  where the local hour is numerically smaller, and failed on a runner in UTC, where the ordering
  fell to whether `+` or `Z` sorts before `.`. Both are now parsed to instants before comparison.
  A claim recorded as confirmatory on a machine east of UTC should be re-checked. ([#5](https://github.com/elliottower/reproducible-science/pull/5))
- **[citations] Cleaning a BibTeX field deleted the argument of every markup command except
  `\emph`.** Braces were stripped before control sequences, so `\texttt{inspect\_ai}` became
  `\textttinspect\_ai` and the command pattern then matched through the start of the argument. A
  record naming the exact package versions an evaluation ran on was written out as *Python
  packages _ai 0.3.260 and _cyber 0.1.0*. Control sequences are now resolved first, and the
  whitespace after a command is kept where the result is displayed — removing it turned
  `Smith\etal Jones` into `SmithJones`. ([#8](https://github.com/elliottower/reproducible-science/pull/8))
- **[provenance-core] `gitref` ran git against the repository the environment named, not the
  one the caller did.** Git resolves its repository from
  the environment before the working directory, so `cwd` alone never named one: under any git
  hook, which exports `GIT_DIR`, `commit(path)` and `is_dirty(path)` answered for whatever
  repository invoked the process. `repro.provenance.of_tree` is built on those calls, so a
  provenance record written from a hook named the wrong repository's commit and dirty state.

  Only the variables that relocate git are dropped -- `GIT_DIR`, `GIT_WORK_TREE`,
  `GIT_INDEX_FILE` and the rest of `gitref.REDIRECTS`. `GIT_SSH_COMMAND`, `GIT_COMMITTER_DATE`
  and the other variables that configure git once it knows where it is are untouched, and a
  caller passing no `cwd` still inherits everything. `gitref.clean_env()` exposes the same
  environment to callers that run git themselves.

  `results.timeline.freeze_timestamp` used `git -C`, which is a directory change and is outranked
  the same way; it now goes through `gitref`. ([#20](https://github.com/elliottower/reproducible-science/pull/20))
- Test helpers across `prereg` and `results` ran git with an inherited environment, which
  wrecked the checkout they ran in. Under
  `pre-commit`, which exports `GIT_INDEX_FILE` while it stashes, their `git add -A` staged into
  the *outer* worktree's index and left every tracked file there staged as deleted -- a wrecked
  checkout produced by a passing test, with `pytest -n auto` workers racing on the one index.
  They now build their environment with `gitref.clean_env()`.

### Changed

- **[citations] A claims file that declares `extract_cmd` now behaves differently, and existing
  ones may need editing.** The field was accepted and ignored: every source was read by
  `pdftotext -layout` or, for a `TEXT_SUFFIXES` file, straight off disk. It is now run. A
  repository that declared a command which is not a per-source extractor will see its
  quotations move — a batch regeneration script that prints a summary and ignores the path
  yields `not found` for every passage, and a command outside the default allowlist yields
  `unchecked` until `--allow-extractor` names it. Both were found in real claim sets on the
  upgrade. Check `citations verify` before and after: a source whose bytes on disk are already
  the text being quoted should declare no `extract_cmd` at all, or `none`. ([#16](https://github.com/elliottower/reproducible-science/pull/16))

### Added

- **[results] `results coverage` reads a manuscript and says which of its numbers are bound.**
  Given a paper and a sealed run, it enumerates every numeric token, sorts each into traceable
  (table cells, measurements, parameters, equation content), untraceable (bibliographic and
  structural furniture), or reported-separately (figure axes, dense lines, orphans, bounds,
  extraction failures), and reports how many of the traceable ones a claim already binds. The
  third group is never folded into the other two: a limit of the scanner is not a property of
  the article. ([#3](https://github.com/elliottower/reproducible-science/pull/3))
- **[results] A plan frozen before the results were seen protects a confirmatory claim.**
  `results claim --confirmatory` refused whenever its run postdated an `outcomes seen` event,
  which treats exposure as decisive. Exposure is evidence that contamination was possible;
  propagation is what threatens a confirmatory reading, and a plan already committed cannot be
  reached by an exposure that follows it. `--frozen-at <commit>` names a commit containing the
  frozen plan; where its commit date precedes the first exposure the claim records as
  confirmatory with `after_outcomes_seen` false, and `verify` lists it separately rather than
  silently among the rest. ([#4](https://github.com/elliottower/reproducible-science/pull/4))
- **[citations] Full text through Paperclip, pinned by digest.** `citations resolve --via paperclip <doi>` fetches a source's full text from [Paperclip](https://paperclip.gxl.ai), writes it to `sources/paperclip/` and pins those bytes by sha256; `citations import-paperclip <repo>` does the same for every paper in a Paperclip paper repo and carries its committed claims across as statements. Verification stays offline against the pinned copy, so Paperclip never decides whether a quotation matches. An identifier with no open-access full text, a document that arrives incomplete, and a missing `citations[paperclip]` extra all leave the source unpinned, so their quotations read `unchecked` rather than `not found`. ([#10](https://github.com/elliottower/reproducible-science/pull/10))
- **[citations] A PDF is readable without poppler, and every result names what read it.**
  `verify` shelled out to `pdftotext -layout` and returned `unchecked` where the binary was
  absent, so `pip install citations` could not check a PDF at all. Where poppler is missing or
  fails on a document, the chain now falls through to pypdf or pdfplumber and records the
  substitution as a fallback with its reason, so a result never rests silently on an extractor
  other than the one it names. A source declaring `extract_cmd` does not enter the chain: its
  author named the program that produces the text, so it runs or the check is `unchecked`.
  `citations verify --triangulate` asks every installed reader instead of one and reports
  disagreement as `indeterminate`, a fourth outcome that leaves the question open rather than
  asserting the passage is absent — extractors disagreeing is a fact about the readers, and
  `not found` is an accusation against the manuscript. ([#14](https://github.com/elliottower/reproducible-science/pull/14))
- **[citations] A claims file's `extract_cmd` is read, and the report says what ran.** The
  field was declared on the model and documented in the claim-file example while
  `verify.extract` hardcoded `pdftotext -layout`, so a `.tex` manuscript reached a PDF reader
  and graded `unchecked` for every sentence in it. A source declaring `extract_cmd` is now
  read by the command it names: the source path replaces `{}` or is appended, and what the
  command prints to stdout is what the quotations resolve against. Every result carries the
  extractor and a sha256 of the text it produced, since a pin establishes that the bytes did
  not change and nothing about how they were read. The command is never handed to a shell —
  the declared string is split into a program and arguments — and only `pdftotext` and `detex`
  run unasked; anything else needs `citations verify --allow-extractor NAME`, written by
  whoever runs the check rather than by whoever wrote the file. A refused command and an
  uninstalled one are both `unchecked` and say which they are; neither makes the passage
  absent. ([#16](https://github.com/elliottower/reproducible-science/pull/16))
- **[repro] A `correspondence` assertion compares two artifacts, and a `prose` locator addresses
  a value in a document.** Every other kind compares an artifact against a literal written in the
  manifest, so a claim a document makes about the code beside it required transcribing one side
  into `reported`, where nothing checks it: rewriting each such field to the measured value
  passes a manifest whose documents are still wrong. A correspondence reads both sides and
  compares them, privileging neither — when they disagree the decision reports both values and
  names neither as wrong. A side that does not extract makes the comparison impossible rather
  than false, so a gap on one side reports as `not_found` and never as `mismatch`.

  The `prose` locator addresses the value between two literal anchors in a document's extracted
  text. No pattern searches for a number: the author declares where the value sits, which is why
  it is an address rather than a recovery. `form: cardinal_word` reads an English cardinal
  written out; without it, a spelled-out number is refused as `number_as_word` rather than
  reported as missing. ([#17](https://github.com/elliottower/reproducible-science/pull/17))
- **[citations] A fetched document records whether its length was checked** against the extent Paperclip
  declared for it, on `Document.extent_verified` and in the `paperclip:` block a claims file
  carries. Where `tail -n 1` declares no last line the completeness check cannot run, and
  `lines` is then counted from what arrived rather than confirmed against what the source said
  it should be; the two cases were previously indistinguishable in the record.

  The field defaults to false, so anything that does not set it reads as unverified rather than
  claiming a check nothing performed. ([#18](https://github.com/elliottower/reproducible-science/pull/18))
- **[citations] `citations coverage` asks the question `verify` cannot: is every quotation in
  the manuscript pinned at all?** `verify` reads the claims files and takes no manuscript, so a quotation added to
  the paper and never pinned has no record, is checked by nothing, and leaves the report clean.

  ```console
  citations coverage paper/draft.tex --claims claims [--strict]
  citations coverage paper/draft.tex --claims claims --attribute
  ```

  Outcomes are `covered`, `uncovered` and `unresolvable`, reported separately rather than as a
  pass or a fail: a quotation too short to distinguish from noise, or one whose neighbouring
  source would not open, is undecided and not a defect in the manuscript. `--strict` fails on the
  undecided ones too, matching `verify`.

  `--attribute` additionally checks each quotation against the artifact of a source cited near it,
  which catches a passage credited to the wrong paper. It never reports a misattribution when any
  neighbouring source could not be read: the passage may belong to the one that would not open. ([#22](https://github.com/elliottower/reproducible-science/pull/22))
- **[repro] Every decision records the extraction toolchain and the digest of what it
  produced.** `backend_version` is a protocol string naming a backend's interface, so a
  `pdftotext` upgrade that resolved a ligature differently changed an extracted passage while
  the artifact's digest held and the report read `backend_version: "1"` on both sides of it.
  A decision now carries `tool` and `tool_version` — the binary's version as it prints it, or
  the installed distribution's for the format adapters — and `extraction_digest`, the sha256
  of the whole extracted text for a quotation and of the extracted value for a number. The
  version says why a reading changed; the digest catches a change from any cause, including a
  rebuilt binary reporting the same version. A version or digest that was sought and not
  obtained is recorded as `unknown`, so it stays distinguishable from one never sought. The
  fields are provenance: no outcome moves, and whether a changed toolchain should break a pin
  is left to policy.

## 0.2.0 — 2026-08-24

First release from the monorepo. The four packages previously released separately from their
own repositories; they now share one version, one lockfile and one release.

Several entries below are corrections to results the tools reported. They are listed first
because a verifier that reports a clean run it did not earn is worse than one that fails.

### Fixed

- **[citations] A quotation matched a source that contradicted it.** The fallback used when a
  verbatim match fails stripped every non-alphanumeric character, so `p < 0.05` resolved
  against a source reading `p = 0.05`, and `-0.42` against `0.42`. It now removes whitespace
  and nothing else, which is what a PDF extractor actually mangles.
- **[citations] A source edited after being pinned still passed.** Every quotation was checked
  against the file on disk and nothing compared it to the recorded digest, so a changed source
  produced a clean run. A broken pin now fails the run and is reported before the quotation
  results, because it changes how they should be read.
- **[citations] `--strict` did not fail on unresolved quotations.** A deleted source, an
  unpinned one, an unparseable claims file and a missing `pdftotext` all left a build green
  while nothing had been verified.
- **[citations] BibTeX entries were split with a regex** that dropped or merged entries
  containing nested braces. Entries are now separated by counting braces.
- **[results] The ledger could be extended after being tampered with.** `append_event` built
  on a chain already reported as edited and re-anchored over the evidence, so a damaged
  ledger verified clean from the next ordinary command onward. It now refuses.
- **[results] Truncating the ledger and re-anchoring was a two-command clean bill of health.**
  `reanchor` now refuses a chain reported as truncated, which is the cheapest tampering there
  is: no line has to be forged, so the hash chain stays intact and only the count disagrees.
- **[results] `verify --files` reported a deleted sealed file as `ok`**, and reported a path
  sealed under several different hashes as `ok` when the file matched any one of them.
- **[prereg] `freeze` proceeded when there was no commit to name.** `git()` returns empty on
  any non-zero exit, so a missing binary, a locked index and a directory outside a repository
  all read as success, and a freeze recorded a commit-shaped string in place of a commit.
- **[prereg] The log was editable after freezing.** The plan hash deliberately stops at the
  log, which left the only record of what changed after registration freely deletable while
  `check` still reported the plan unchanged. Entries are now chained, with an anchor
  recording the length so a removal from the end is visible.
- **[prereg] `check` passed at a repository root when a plan below it was never frozen**, so
  whether an unfrozen registration passed CI depended on which directory it ran from.
- **[repro] A structured array element resolved as a single value.** A two-field record
  stringified as `(0.91, 0.02)` and was reported as one extracted value, so a manuscript
  reporting `0.91` could verify against a record rather than a number.
- **[repro] A passage found on the wrong page reported as verified.** The page was recorded as
  a warning, and no policy reads decision warnings, so the assertion was unenforceable.
- **[repro] Duplicate artifact and claim ids silently kept the last declaration**, which could
  drop a broken pin from the report entirely and leave the strict policy passing with no
  violations at all.
- **[repro] Duplicate keys in JSON resolved to whichever came last**, so one artifact could
  hold two values for one quantity and address one of them with nothing said about the other.

### Added

- **[repro] Conformance fixtures now pin the reason and the artifact validity**, not only the
  outcome. Four cases share the outcome `unchecked` and three share `not_found`; without the
  reason, a defect in the tool and a fact about the manuscript were indistinguishable.
- **[repro] A `broken_pin` conformance case**, which the fixture set named in its skip list
  but never contained.
- **Coverage is measured and gated at 70%.** Most suites drive a CLI in a real subprocess,
  which coverage does not follow by default, so the CLI modules reported 0–18% while their
  tests passed.
- **Dependency floors are resolved in CI** (`--resolution lowest-direct`), which found two
  declared minimums that could not be installed at all.
- **Lockstep versioning is enforced** by `make versions`: every package carries one version
  and pins its siblings to that series.

### Changed

- **Restructured as a uv workspace.** One lockfile, four packages, one release.
- **Python 3.11 is now required.**
- **[citations] [repro] Raised `pyyaml` to `>=6.0.2` and `pydantic` to `>=2.9`.** The previous
  floors resolved to versions that fail to build on current Python.
