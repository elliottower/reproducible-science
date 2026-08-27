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
