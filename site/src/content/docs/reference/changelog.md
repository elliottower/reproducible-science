---
title: Changelog
description: Changelog — Reproducible Science
---

<!-- Generated from CHANGELOG.md. Edit that file, not this one. -->

## 0.6.0 — 2026-10-14

### citations

No significant changes.

### claims-cli

#### Changed

- **A check record now names its version `reproducible.science/claim-check/0.1-experimental`, and 0.6 reads records under either name.** `repro export record` and `claims export record` write the new string where 0.5.6 wrote `repro.check/0.1-experimental`; the format is otherwise the same, field for field. Every release in the 0.6 series reads a record under the old string as it reads one under the new, through `claims.record.validate`, `read_outcome` and the RO-Crate and SARIF exporters, and the next minor release reads only the new one. A program that compares the `record` field with `repro.check/0.1-experimental` has to accept the new string too. The JSON Schema is now `docs/schemas/claim-check-0.1-experimental.schema.json`, published at <https://reproducible.science/schemas/claim-check-0.1-experimental.schema.json>, and its `record` accepts both strings; `docs/schemas/repro.check-0.1-experimental.schema.json` stays where it was, marked superseded. The checker name, the SARIF driver and its upload category, the RO-Crate profile URL, `schema_version: repro/1` and `.repro/` are unchanged.

#### Added

- **An artifact copied from another repository can say where it came from, and `claims origins` checks that the pin is the bytes there.** `artifacts[].origin: {repository, commit, path}` names one file at one full 40-character commit; a branch, a short id, an absolute path or a path with `..` is refused when the manifest is read. The field is left out of a manifest's serialization where it is absent, so a manifest that declares none has the manifest digest and claim digests it had, and `claims verify` never reads it. `claims origins` (also `repro origins`) reads `<commit>:<path>` from a clone given with `--repo REPOSITORY=PATH`, or from a repository named by a local path, with `git cat-file`, so committed bytes and never a working tree; with `--fetch`, a GitHub repository with no clone is read from `raw.githubusercontent.com` at the commit, and without it nothing touches the network. Each origin is `same`, `differs` (both digests printed), `absent`, `unknown_commit` or `not_checked`, with the reason, and a file on disk that is not the pinned bytes is said beside it. It exits 0 where every origin is `same`, 1 where one differs or is absent, 2 where one could not be checked and none failed. The check record carries the declared origin on a file entry that has one, and the RO-Crate export carries it on the `File` as `isBasedOn`.
- **`claims-cli` is the part of Reproducible Science that checks what a manuscript states against its files, installable by itself.** `pip install claims-cli` installs the command `claims` and the package `claims`, with `citations` and `provenance-core` and nothing else of ours: `claims verify`, `claims stale`, `claims why`, `claims numbers`, `claims export` and `claims manifest init` are the commands `repro` has under those names, the same functions reading the same `repro.yaml` and printing the same output. It runs no command a manifest names and drives no other tool; `repro reproduce`, `repro check`, `repro audit` and `repro ci` stay in `reproducible-science`, which depends on this. Where a message tells the user what to type, `claims` names its own command (`claims manifest init`), and names `repro reproduce` with the distribution that provides it. The optional readers are extras of this distribution: `arrays`, `hdf5`, `netcdf`, `parquet`, `rds`, `sheets`, `stata-spss`. Installed without `reproducible-science`, a decision names `claims-cli` as the tool that read the artifact and carries its version, and a hint for a missing reader says `pip install "claims-cli[sheets]"`; installed with it, both are what they were.

### prereg

#### Added

- **`prereg.inplace` holds what `prereg check` decides about a plan frozen in place, read from its text.** `in_place(text)` returns the state `check` reports (`unchanged`, `changed`, `uncovered`, `log altered` or `not frozen`) with the digests and problems behind it, and `check` prints from it, with output and exit codes as before. `entries_appended(earlier, now)` counts the log entries `now` holds beyond `earlier` where that, and the `**Log:**` line `prereg log` recounts, is all that separates them and `check` finds `now` unchanged; it answers 0 for any other difference. `results verify --files` asks it of a sealed plan.

### results-cli

#### Changed

- **`results verify --files` passes a path whose file matches its latest record, a sealed plan whose log grew, and a seal of the ledger's own files, and names each.** A path recorded under more than one hash was `RESEALED` and failed whichever hash the file matched, so a ledger that ever sealed a file twice could not pass again. It is now `RESEALED` and passes where the file matches the hash of the path's latest record, and `REVERTED` and fails where it matches an earlier one; a file matching none is `CHANGED`, as before. A plan `prereg freeze` froze in place that `prereg check` finds unchanged, and that differs from its latest seal only by the entries `prereg log` appended and the `**Log:**` line it recounts, is `APPENDED` and passes; the sealed bytes are read from git history, and where no commit holds them the plan stays `CHANGED`. The rule is `prereg.inplace.entries_appended`, which `prereg check` now decides with too, so `results-cli` depends on `prereg`. A recorded path under `.results/` or a lock sidecar is `IGNORED` and passes, and `results seal` and `results run` refuse such a path, and a directory holding `.results/`, writing nothing. `--json` gives the new states as `resealed`, `reverted`, `appended` and `ignored`, with `hashes`, `matches`, `entries` and `note` where they apply. `CHANGED`, `MISSING`, `NOT A TREE` and `NOT A FILE` fail as before, and the chain checks are unchanged.

### reproducible-science

#### Changed

- **The code that checks a manifest now lives in `claims-cli`, and `repro` is unchanged for anyone who uses it.** `reproducible-science` depends on `claims-cli` and every command keeps its name, its output and its exit code: against a project of 38 claims, the text and the JSON of `repro verify`, `repro stale`, `repro numbers` and `repro why` are byte for byte what they were. Every import keeps working and reads the same object, `from repro import load, verify`, `repro.models`, `repro.verify`, `repro.provenance` and the rest, private names included, since each of those modules now hands back the one in `claims`. A monkeypatch or an assignment through an old path, `repro.verify._exponent = …`, changes that module and not the code in `claims.verify`, which keeps its own; a patch meant to reach the checking code targets `claims.*`. What a full install writes does not move: a decision still names `reproducible-science` and its version, the SARIF driver, the record version, `.repro/` and the `adduce.rules` entry point are as they were, and a workflow written by `repro ci init` still pins `reproducible-science`. `reproducible-science[sheets]` and the other extras install what they did, by asking `claims-cli` for the extra of the same name. An editable install made before this change has to be rebuilt once, because the package it imports from is a new one.
- **`repro ci results`, `repro badges` and the mod's band read the file states `results verify --files` now gives.** `reverted` fails with `changed`, `missing`, `not a tree` and `not a file`, is counted on the `recorded files` row and is listed by path. `resealed`, `appended` and `ignored` pass, and the summary counts each on a row of its own (`11 resealed, matching their latest record`) and lists none of them. The `results` badge is red where the check fails with every recorded file in a state that passes, which is a timestamp contradicting the chain, and amber where it fails over a file in a state that fails; its message stays `<n>/<m> runs sealed`. The band counts a `REVERTED` file as changed, and counts no `RESEALED`, `APPENDED` or `IGNORED` file.

#### Added

- **The Claude Code mod's band above the prompt has a row for re-runs of the declared commands.** Where `repro.yaml` declares commands under `regenerations`, a fifth row reads `repro: 7/7 reproduced, last 13 Oct`, or `repro: 5/7 reproduced, 2 stale since 13 Oct  →  repro reproduce` where a command's files are no longer the ones a recorded re-run was made over, or `repro: 0/7 reproduced  →  repro reproduce` where none has been re-run. The counts are commands as `repro stale --format json` reports them, the date is the day the latest re-run compared against started, and `in CI` follows it where that re-run's entry carries a `witness`. A manifest with no `regenerations` draws no row and the row above it is unchanged. The mod's tests now run in CI, in a `mod tests` job that installs a pinned Claude Code.
- **`repro badges` prints one README badge per check, each reading a count from a run on this machine.** The five badges read `prereg | 1 plan frozen`, `results | 19/19 runs sealed`, `claims | 76/76 verified`, `citations | 199/199 verified` (or `199 pinned` where no source could be read) and `reproduced | 7/7`, green where everything counted holds, amber where something was not established, and red where the matching `repro ci` check fails; the `results` badge is red only where the ledger's chain does not verify, and amber where `results verify --files` fails over recorded files. Each count is what that check counts: `prereg`, `results` and `citations` read the JSON the tool writes with `--json`, `claims` and `reproduced` read `repro verify` and `repro stale`, and runs sealed are counted from the ledger as the mod's band counts them. The badges are static shields.io images, so they draw for a private repository. A check with no record has no badge and is named on standard error; `--all` draws it gray as `none declared`. `--readme` writes the badges into `README.md` between two marker lines and replaces only that block on a second run, and `--check` exits 1 where the block is not what the project gives now, for a pre-commit hook.

### provenance-core

#### Added

- **`provenance_core.chain` holds the hash chain the `results` ledger is written with.** The writer and reader of a JSONL file whose every line carries its position and the hash of the line before it, with a head file recording the length and the last hash, were in `results.ledger`, and `repro verify` imported them from there to keep its record of checks. They are now `provenance_core.chain`: `append_event`, `verify`, `verify_chain`, `reanchor`, `read_ledger`, `read_anchor`, `write_anchor`, `anchor_path`, `last_hash`, `line_hashes`, `canonical`, `ChainStatus`, `ChainError`, `ANCHOR` and `CANON_VERSION`. `results.ledger` still has every one under the same name, as the same object, and writes the same bytes; `repro` imports them from `provenance_core` and no longer imports `results`. `ChainError` is no longer a subclass of `results.ledger.ResultsError`, and the `results` command catches both, so what it prints and its exit code are as before.

## 0.5.6 — 2026-10-13

**Upgrading from 0.5.5.** Five changes can alter what a project that passed under 0.5.5 now sees. Each is described in full below.

- Under the `strict` policy, a `quote` assertion that declares a `page` nothing could check is an error (rule `evidence.page_unchecked`): the artifact is text, LaTeX, a workbook or a `.docx`, or the passage matched only with spacing ignored. It is a warning under `exploratory` and `publication`, and an error for a confirmatory claim under `publication`. A `page` on a LaTeX artifact was a `wrong_page` mismatch for every page and is now this.
- A stored value exactly halfway between two printed values verifies as either: a file holding `4.25` verifies a manuscript printing `4.2` and one printing `4.3`, where `4.3` was a mismatch.
- A number in a JSON or YAML artifact is compared as the digits the file wrote. Against a printed value only the three cases that were compared wrongly change. A `correspondence` between two such files now counts their trailing zeros as precision, so `0.910` against `0.914` is a mismatch where it verified.
- `repro verify` in a git repository appends to a record of checks in the git directory, `repro/checks.jsonl` under the path `git rev-parse --absolute-git-dir` names. The working tree is left as it was, and what the command prints and exits with is unchanged.
- `citations verify` gives the warning `truncated` to a passage that begins inside a word or a number, and `page unchecked` to a recorded page it could not check. Neither changes a verdict or an exit code.

### citations

#### Fixed

- **A quotation that begins in the middle of a word or a number is flagged `truncated`, as one that ends there already was.** The token boundary was checked only where a passage ends, so `113 quotations` resolved inside a source saying `2113 quotations` with no warning, and `ample size` inside `sample size`. An occurrence now begins inside a token where a letter or digit precedes its first letter or digit, and for a passage opening on a digit also where a decimal point or a grouping comma ties it to a digit before (`113` in `0.113` and in `2,113`) or a sign precedes it (`0.42` in `-0.42`). A bracket, a quotation mark, other punctuation, white space, and a hyphen after a word (`sub-sample`, `10-12`) are boundaries. The verdict is the one a cut at the end gets: where every occurrence begins or ends inside a token the quotation is still `found` and carries `truncated`, and where one occurrence lands cleanly the others are not counted, so a passage that was `ambiguous` only because a longer number ends with it is now `found`. A passage matched with spacing ignored (`normalized`) is judged on neither end, as before, since that match discards the white space a boundary is read from.
- **A recorded `page` that nothing checked is reported as `page unchecked`, and a page on a LaTeX source is no longer called wrong.** `is_paginated` answered yes for `.tex` and `.latex`, so `detex` was asked for page N, could not give one, and every quotation with a `page` came back `found` with the `page` warning, `not on page N`, whatever N was. LaTeX is read as one text and is not paginated; `is_paginated` is now true only where a PDF reader reads the source. A page recorded on a source with no pages (text, LaTeX, a workbook, a `.docx`), or on a passage that matched only with spacing ignored, was dropped with nothing said, so `page: 9999` passed as `page: 1` did; each now carries `page unchecked`, the warning a declared `extract_cmd` already got, and `citations verify` counts it under `warnings`. A claims file that records pages against extracted `.txt` sources will show one such warning per quotation. No verdict and no exit code changes, with or without `--strict`. The README's `truncated` row says a passage may begin as well as stop inside a word or number.
- A file holding text is read as text when its suffix names no reader. A run log called `output`, a `.log` and an `.Rout` reached the PDF reader, which answered `Couldn't read xref table`, and every quotation and every number in the file was `unchecked`. A file with a `.pdf` suffix is still read as a PDF.
- Text folding removes a hyphen at a line break only between two letters, where a renderer split a word. Every dash at a line end was deleted with the break: a rule of dashes in printed output lost its last dash and ran into the next line, so an anchor or a quotation had to be written with one dash fewer, and `10-` over `12` folded to `1012`. A quotation or an anchor written around the old behaviour, with the dash left out, no longer matches at that spot.

#### Added

- **`citations pin --url URL` pins a quotation against a web page.** The page is obtained through [`retrieved`](https://github.com/elliottower/retrieved): the most recent retrieval of that URL in the `retrieved` library is read where there is one, and the page is captured through `retrieved`'s denylist, pacing and fetch where there is none; `--recapture` fetches it again. The claims file, which need not exist, is written with the URL, the sha256 of the bytes, the retrieval time as `retrieved_at`, and `retrieved: store/<sha256>`, a path inside the library, so the file names no directory of the machine that wrote it and the page is never copied into the project. An HTML page is checked as the text it shows, through the new built-in extractor `html-text`, which drops tags, decodes character entities, leaves out `<script>` and `<style>`, and writes a table row with ` | ` between its cells; the claims file names it with `extractor_version` and `derived_sha256`, so `verify` reads the page the same way. Other text is read as served and a PDF by the PDF readers. A local `.html` file that declares nothing is read with its markup as before, and can name `extractor: html-text`. The library is `$RETRIEVED_HOME`, else the nearest `.retrieved/` at or above the directory holding `claims/`, else a new `.retrieved/` there. A URL `retrieved` refuses, a server error and a failed request exit 1 with the reason and write nothing. A claims file pins one retrieval: `--url` on a file that pins another retrieval or another source is refused. `citations verify` reads the page from the library and reports `unchecked`, naming the store, where the library does not hold it; `citations fetch` keeps a new download only where it matches the pin, and otherwise says the page may have changed since the retrieval time. `retrieved` is installed by the new `web` extra, `pip install "citations[web]"`, which takes `retrieved` 0.1 or 0.2; without it `pin --url` names the install and every other command is unchanged.
- **`citations verify --json PATH` and `citations fetch --json PATH` also write their counts to a file, as JSON.** The text printed and the exit codes are unchanged. `verify` writes the number of `quotes`, `counts` per outcome (`found`, `not found`, `ambiguous`, `indeterminate`, `unchecked`), and, with `--claims`, the number of `sources` read and of `absent_sources`: sources with no file at the path the claims file names and none in the library matching the pin, whose quotations are all `unchecked`. It also writes `broken_pins`, `unpinned_sources` and `skipped_files`. `fetch` writes the number of `sources` and `counts` per outcome, in the words its report uses.

### prereg

#### Changed

- **A run recorded as holding no outcome puts the freeze floor at `no results seen`, not `results not opened`.** The floor still rises to `results not opened` with one run recorded without `results run --holds`, and to `results seen` with an `outcomes seen` access event, whatever the runs were recorded as holding. A `holds` value this version does not know is read as no label, so an older `prereg` reading a newer ledger is never more lenient than it was. The ledger's summary, in a refusal and in an amendment, counts the two kinds apart: `3 runs recorded, 2 of them recorded as holding no outcome`. A run declared so afterwards with `results label` counts the same, and the summary says how many were: `1 run recorded, 1 of them recorded as holding no outcome (1 declared after the run was recorded)`.

#### Added

- **`prereg check --json PATH` also writes what the check found to a file, as JSON.** The text printed and the exit code are unchanged. The file holds `plans`, one object per plan checked: its `path`, whether it is `frozen`, the `sha256` it was frozen with, `check` as `unchanged`, `changed` or `not frozen` for the plan together with its amendments and its log, the number of `amendments` that have a freeze record, the number of `amendment_drafts` that do not, and the number of `log_entries`. A plan that was never frozen has `frozen: false`, so a reader of the file can tell a draft from a frozen plan with a draft amendment, which both print `not frozen`. `commit_pinned` holds each registration frozen by a commit line with its `status` and `commit`.

### results-cli

#### Added

- **`results run --holds` records that a run's outputs hold no outcome.** A panel or feasibility query whose counts a paper reports has to go through `results run` and be claimed, and it has to happen before the plan it defines can be written, so every such plan was frozen as though results existed. `--holds "metadata only"` and `--holds "structure seen"` write a `holds` field into the run event. It is written with the run and by no later command, so the declaration sits in the chain before anything that reads it. Any other value is refused and nothing is recorded: a run whose outputs hold outcomes is recorded without the flag, which is what a run meant before the field existed, and ledgers written before it read exactly as they did. A run recorded without the flag by oversight is declared afterwards with `results label <run-id> --holds ... --note ...`, which appends a `label` event and leaves the run event as it was; it names one run, needs a note saying why, and refuses a run that already says what it holds.
- **`results verify --json PATH` also writes what it found to a file, as JSON.** The text printed and the exit code are unchanged. The file holds the `chain` status (`intact`, `truncated`, `extended`, `edited`, `reordered`, `corrupt`, `no_anchor` or `absent`) with its `problems`, the number of `events`, whether `--files` was given as `files_checked`, and under `files` each recorded path with its `state`: `ok`, `changed`, `missing`, `resealed`, `not a tree` or `not a file`. Where the chain does not verify no file is compared and `files` is empty.

### reproducible-science

#### Fixed

- **A `page` on a LaTeX artifact is `page_unchecked`, where it was a `wrong_page` mismatch for every page.** `citations` no longer treats a `.tex` source as paginated, so a `quote` assertion with a `page` against one is `verified` with the warning `page_unchecked`, as it is against a text file. A quotation that is not found no longer carries a page warning beside its mismatch.
- **A manifest with two regenerations of one id, or two that write one artifact, no longer loads.** `artifacts` and `claims` were checked for a repeated id and `regenerations` was not, and where two records named the same output `repro reproduce` took the last declared as that file's producer and never consulted the other, so a downstream record's `on the recorded output of` line could leave out a producer that had not reproduced. Both are now a `ManifestError` that names the two records, `regenerations 'figures' and 'again' both write artifact 'figures': one artifact has one producer`, and `repro verify` and `repro reproduce` exit 2 on it as on any manifest that does not load.
- **A number in a JSON or YAML artifact is read as the digits the file wrote.** Both loaders hand a number with a fraction or an exponent over as a binary float, and the float was printed back before the comparison: `0.910` became `0.91`, `1e-7` became `1e-07`, and three kinds of value were compared wrongly. A value of more than seventeen significant digits was compared as its nearest double, so a manuscript printing all twenty digits of `0.12345678901234567890` was a `mismatch` against the file it was copied from. `9007199254740993.0` was read as `9007199254740992.0`, which verified the wrong integer and refused the right one. `1e400` was infinity and `value_not_numeric`, and `1e-400` was zero. The text of the number is now kept and read as an exact decimal, and it is what `repro why` and a re-run's record show; `repro verify` prints the same digits, trailing zeros included, with an exponent in the form `1E-7`. Integers were already exact. Against a printed value nothing else changes: the precision is the manuscript's, so `0.910` in a file still verifies a printed `0.91`. A `correspondence` compares at the coarser of the two precisions as written, so a tree file's trailing zeros now count there as a CSV cell's always did, and `0.910` against `0.914` in two JSON files is a `mismatch` where it was `verified` at two places. The extraction digest of a value whose text changed, `0.910` for `0.91`, changes with it. `repro manifest init` proposes a number as the file writes it. `docs/SPEC.md` §3.9 says what the value as stored is for each format; a format that stores numbers in binary has no trailing zeros to recover.
- **A quotation that occurs more than once in its artifact can say which occurrence it means.** `docs/SPEC.md` §3.1, the `quotation_ambiguous` reason and its docstring all gave the fix as a `prefix` or `suffix` in the record, and a `quote` assertion had neither field: a manifest carrying one was refused as `Extra inputs are not permitted`, so a passage written twice could not be verified at all. A `quote` assertion now takes `prefix` and `suffix`, the text immediately before and immediately after the passage, with the meaning they have in a `citations` record (the W3C Web Annotation `TextQuoteSelector`). Both are kept as written, surrounding whitespace included, and handed to `citations` unchanged. They are consulted only where the passage occurs more than once: the assertion is `verified` where exactly one occurrence carries them, and stays `quotation_ambiguous`, with a detail saying the two single out no occurrence, where none or several do. Both default to empty, and a passage that occurs once is checked as before with or without them. A report's `manifest_digest` is taken over the whole manifest as loaded, the two new fields included, so it differs from the one an earlier release printed for a manifest holding a `quote` assertion.
- **A quotation whose declared `page` was not checked says so.** A `quote` assertion with a `page` was `verified` with nothing said about the page in two cases: against an artifact that is not read page by page, such as a text file, where `page: 9999` passed as `page: 1` did, and against a paginated source where the passage matched only with spacing ignored. The decision now carries the warning `page_unchecked` and a detail, `page 3 was not checked: the artifact is not read page by page`, and `repro verify` prints both on the assertion's line. The passage was found, so the assertion stays `verified`. The page is a declared check that did not run, so a policy grades it as it grades `unchecked` for that claim, under the rule `evidence.page_unchecked`: a warning under `exploratory` and `publication`, an error for a confirmatory claim under `publication`, and an error under `strict`, where a manifest with a `page` on a text source passed before and now fails. `citations`' own `page unchecked` warning, which it gives for a source that declares an extractor, was not mapped and is, and a test holds the two lists of warnings equal.
- **The specification has sections for `repro stale`, `repro why` and `repro numbers`.** `docs/SPEC.md` described none of the three. §7.7 gives each staleness state and cause and exactly what is compared with what: a regeneration against the re-runs in `.repro/reproductions.jsonl` that were started and reproduced, by its command, the digest of each declared input and the digest of its output. §7.8 gives what an account holds for one claim and every kind of `not established` line. §7.9 gives which text is read, what a number is, the four standings, the definition of bound, `set_aside`, and the eleven rules in the order they are applied. §7 names the registration authorities and their ranks. A test fails when a state, cause, kind, standing, rule or authority is added to the code and not to the specification. The `Ordering` docstring said eight conditions stop an ordering check; there are nine.
- **The specification says what the code does.** `docs/SPEC.md` gave the normalization a quotation is matched under as NFKC; the text is decomposed to NFKD and its combining marks are dropped, so an accented name matches its unaccented form, and the `citations` README now says the same. §4.1 lists every `Reason` and every warning with the outcome each flattens to, where it listed sixteen of twenty-three reasons and four of five warnings, and a test fails when a value is added to either and not to the specification. It also gains the `artifact_absent` validity, the `value` evidence kind, the wrong-page and unsupported-format rows of §4, and what each policy profile does with an `error`, a broken pin and an absent artifact; §3.5 no longer calls the ordering check unimplemented, and §7.5 says where a SARIF result's `kind` does follow the policy. The pre-commit example in the README pinned `rev: v0.4.0`; `scripts/versions.py` now checks and writes it with the copy in `.pre-commit-hooks.yaml`.
- **`repro reproduce` names a declared conversion, and `repro numbers` binds the count an `aggregate` states.** A number that changed on a re-run was printed as the file stores it beside what the paper prints, so an assertion declaring `conversion: percent` read `0.044 then, 0.042 now, paper prints 4.4`, two units on one line with nothing saying so. The line is now `0.044 (4.4 as a percentage) then, 0.042 (4.2 as a percentage) now, paper prints 4.4`, and each reading in `.repro/reproductions.jsonl` carries `conversion`, `pinned_converted` and `fresh_converted`. The verdict was already right, since a re-run is compared by the function `repro verify` uses, and a reading with no conversion is printed and recorded as before. `repro numbers` binds a number by the `reported` value, which is the printed one, so a number bound through an assertion that declares a conversion was and is `bound`; that is now tested. It did leave the "ten" of "mean over ten seeds" unbound beside the mean it bound, and an `aggregate` now binds its `count` as well as the statistic it reports. `repro stale` compares digests and prints no stored value, so it needed no change.
- `repro init .` sets up the directory it is run in, as `repro init` does. The dot was read as a project name, so a `CLAUDE.md` headed `# .` and `data/`, `scripts/` and `figures/` folders were written into an existing project.

#### Changed

- **The export record's model is `repro.record.ExportRecord`, and an `aggregate` has a check type of its own.** The tree held two classes named `CheckRecord`: one entry of the stored history in `.repro/checks.jsonl` (`repro.models.CheckRecord`) and one check written for another program (`repro.record.CheckRecord`). The second is renamed `ExportRecord`, with no alias left behind; the record's version, `repro.check/0.1-experimental`, and its schema file keep their names, and the schema's `title` follows the class. An `aggregate` assertion is now `check_type: aggregate-comparison`, since `value-comparison` says a printed value was compared with the value at an address and an aggregate compares it with a statistic over several; `comparison` carries the declared `count` beside the `statistic` and what it `computed`. `repro.record.validate` also refuses a comparison under a declared conversion that lacks the converted value, an aggregate without its statistic, its count, every member's value or what was computed, and a match on a tie that prints neither of the tie's two values.
- The `repro` skill says a claim's `text` is the manuscript's sentence or the question as asked, word for word, with the author's own label in `id`.

#### Added

- **An `aggregate` assertion checks a printed value against a statistic over every run it names.** A sentence reporting a mean over ten seeds could be bound only with a `metric` on one file, which passes whichever of the ten runs that file is and reads none of the others. `kind: aggregate` takes `name`, `reported`, a `statistic` from a closed set (`mean`, `median`, `min`, `max`, `sum`, `count`), `members`, each an artifact and a locator, and a required `count` that must equal the number of members. A manifest stating `count: 10` and listing nine members does not load, and neither does one listing a member twice, so a run dropped from the list cannot leave a mean over the rest. The statistic is computed exactly, over rationals, and compared by the rule a single value is held to: members holding `0.264` and `0.099` have a mean of exactly `0.1815`, a tie at three places, so `0.181` and `0.182` both verify and the decision records the tie, where the same mean in floating point is no tie. `mode`, `tolerance`, `conversion` and `places` apply as for a `metric`, with a conversion applied to each member before the statistic and refused with `count`. Every member must hold a number. A member whose file is missing leaves the assertion `unchecked`, one whose address does not resolve or holds no number makes it `not_found`, the detail names each such member, `member 4 of 10 (seed-3): /accuracy does not resolve in seed-3.json`, and the statistic of the remaining members is never compared. `repro verify` prints `accuracy: mean of 10 = 0.9137`; `repro why` lists each member's pin and stored value and then `the mean of the 10 values: 0.9137` above the value the manuscript prints; `repro stale` treats every member's file as read by the claim; and the SARIF result is located at each file. In `--format json` a decision carries `members`, each with its artifact digest, locator digest and extracted value, with `statistic` and `computed`. The set has no standard deviation. The existing kinds, and their output, are unchanged.
- **An assertion may declare how many decimal places a value is reported to, and a value exactly halfway between two printed values verifies as either.** The precision of a comparison is read off `reported` as written, and that stays the default. `metric`, `table` and `value` evidence now take an optional `places`, the author's statement of that precision. Where it is declared, `reported` must be written to exactly that many decimal places and the stored value, after any `conversion`, must round to it: `"4.20"` under `places: 1` and `"3.1"` under `places: 2` are each a `mismatch` with the new reason `places_mismatch`, whatever the file holds, so no printed digit is left unread. `places` goes with `printed_precision` only, and a manifest declaring it with `absolute` or `relative` does not load. The comparison rounds half to even, as it did. At an exact tie, a stored `4.25` printed to one place or a stored `0.0425` printed as a percentage, half-up rounding prints `4.3` and half-to-even prints `4.2`, so a manuscript printing either now verifies where `4.3` was a mismatch before, and a printed value that is neither neighbor is still a mismatch. A tie is decided on the digits, with no float and no tolerance: `4.2500001` is not one, and only `4.3` verifies against it. A decision at a tie carries `tie`, with `lower`, `upper` and `printed`; `repro verify` prints `[exact tie: 4.2 or 4.3]` beside the assertion; and `repro why` prints `an exact tie between 4.2 and 4.3` above the printed value, and `declared to 1 decimal place` beside it where `places` is declared. A `correspondence` at a tie agrees with either neighbor and records it the same way. An assertion that declares no `places` and meets no tie is compared, reported and serialized as before.
- **An assertion may declare that the file holds a fraction and the manuscript prints a percentage.** A results file holding `0.042` and a manuscript printing `4.2` could not be bound: `repro verify` reported a mismatch, and the alternatives were to write `4.2` into a second file or to leave the number unchecked. `metric`, `table` and `value` evidence, and each side of a `correspondence`, now take an optional `conversion` from a closed set of two names: `percent`, where the stored fraction times 100 is what is printed, and `fraction`, where the stored percentage divided by 100 is. No assertion takes a multiplier or an expression, and a manifest naming any other conversion does not load. The stored value is converted exactly, by moving its decimal point, and only then compared at the precision the manuscript prints, so `0.0424` agrees with a printed `4.2` and `0.0426` does not; under `absolute` and `relative` the `tolerance` is in the printed unit. `repro verify` shows both values, `/attrition = 0.0424 (4.24 as a percentage)`, and `repro why` prints `holds 0.0424, 4.24 as a percentage` above the value the manuscript prints. In `--format json` a decision carries `extracted`, the value as stored, `conversion` and `converted`, a side of a correspondence carries the same three, and each file `repro why` lists carries `conversion` and `converted`. An assertion that declares no conversion is compared and reported as before, and a manifest that declares none serializes without the field, so its manifest digest does not move.
- **An entry in the record of re-runs says where the re-run happened, where the environment said.** A re-run on the author's machine and one a CI service ran left the same entry in `.repro/reproductions.jsonl`. Under GitHub Actions, where `GITHUB_ACTIONS` is the string `true`, `repro reproduce` now writes a `witness` beside `environment`: `kind` (`github_actions`), `repository`, `workflow`, `run_id`, `run_attempt`, `sha`, `ref` and `runner_os`, each copied from the `GITHUB_*` or `RUNNER_OS` variable, with a variable that was not set left out. Every other run writes no `witness` key, so a local entry is the entry it was and an existing log loads unchanged. The variables are whatever the process was given: no request is made and nothing is checked against GitHub, and the run's page and log, at `https://github.com/<repository>/actions/runs/<run_id>`, are what a reader checks the entry against. `repro reproduce` prints `witnessed in GitHub Actions run 123456 of owner/repo, as the environment said` after `recorded in`; `repro why` prints `re-run of <time> reproduced in GitHub Actions run 123456 of owner/repo`; a finding in `repro stale` or `repro why` that names a re-run ends `; that re-run was in GitHub Actions run 123456 of owner/repo`; and in `--format json` each regeneration and each finding carries `witness`, null where the re-run has none. A re-run with no witness is printed as before.
- **`repro ci` runs each check as one line of a GitHub Actions workflow, and `repro ci init` writes the workflows.** `repro ci prereg` runs `prereg check`, `repro ci results` runs `results verify --files`, `repro ci citations` runs `citations verify --claims <dir>`, each found and pointed as `repro check` finds and points it; `repro ci claims` runs what `repro verify` runs and, where the manifest declares a command, reports what `repro stale` finds without grading it; `repro ci reruns` reads the record of re-runs as `repro stale` does and runs nothing: it passes where every declared command has a recorded re-run that reproduced, made over the command and inputs as they are now, and fails a command that is stale, never rerun or undetermined under any policy, and with `--run` it runs the commands in the job as `repro reproduce` does. Each prints what those commands print and appends a Markdown summary to the file `GITHUB_STEP_SUMMARY` names, or `--summary PATH`, which GitHub shows on the page of the run. Every count in a summary carries its denominator: `75 of 76 assertions verified, 1 mismatch`, `1 of 1 frozen plan unchanged since the freeze`, `1 of 2 recorded files match the hash recorded, 1 changed`, `1 found, 0 not found, 1 unchecked of 2 quotations`. An assertion or quotation that is `unchecked` or `not found` is counted under that word, warnings are counted beside the outcomes and change none, the claims summary carries what `repro numbers` counts in the manuscript's text, which grades nothing, a plan never frozen is counted apart and called a draft, each list stops at 20 lines and says how many more there are, and each summary ends on what its check does not show. The counts of the three tools are read from the JSON each now writes with `--json`. `prereg`, `results` and `citations` exit 0 where the check passed, 1 where it failed, and 2 where it could not be made or there is nothing to read, as `repro audit` reads the same command, with one difference: a citations run in which some quotations were found, none was not found and the rest were unchecked passes, and its summary opens on how many were not checked. A run that read no source exits 2. `repro ci citations --fetch-sources` runs `citations fetch` first, takes no exit code from it, and counts what was fetched. `repro ci claims` takes `--policy` and exits as `repro verify` does, and `repro ci reruns --run` takes it and exits as `repro reproduce` does; a manifest that declares no command does not fail `claims`. `repro ci init` writes a workflow under `.github/workflows/` for each of prereg, results, claims and citations the repository keeps a record for, says which it skipped and why, and writes `reruns.yml`, a workflow named `reproduced`, where the manifest declares a command and the record holds a re-run; `--reruns` requires that workflow and `--run-reruns` writes the one that runs the commands. Each workflow has `reproducible-science` pinned to the installed version, each action pinned by commit, `contents: read`, on a push to the default branch and on every pull request. Each workflow is named for its check, because GitHub's badge is per workflow and prints that name beside `passing`; `--name CHECK=TEXT` renames one and `--prefix` changes the file names. It prints two badge lines per workflow written, GitHub's own and one drawn by shields.io with the check's icon on a dark label, which works only for a public repository, with the owner and repository read from the `origin` remote; `--readme` puts GitHub's on one line under the first heading of `README.md`, once, and `--readme --branded` puts the other. A workflow it wrote is replaced only with `--force`, a file of that name it did not write is never replaced, and outside a git repository or with no record to check it exits 2 and writes nothing. `repro verify`, `repro stale`, `repro reproduce` and `repro check` report as before. Every summary opens on what its check compares and a link to its section of the documentation. The reruns summary says where the record places each re-run it relied on: how many were recorded in a GitHub Actions run, with the run's page linked, and how many were recorded with no witness; a re-run made with `--run` says which run it was made in, and the claims summary names the run of the last recorded re-run where the record holds one.
- **`repro export record` writes one record per checked assertion, as JSON Lines.** Each line states what was observed and no verdict: the checker and its version, the manifest and its digest, the claim and where the manifest declares it, each file read with its pinned digest, its digest on disk and its `validity`, the address as a tagged object, the value stored there, the value the manuscript prints (`printed`), the comparison mode and tolerance, and the outcome. A declared conversion is named and the converted value sits beside the stored one, declared decimal places and a tie travel with the comparison, and an `aggregate` has one file read per member with the statistic and what it computed. An assertion is identified by its claim's id, its kind, its name and its `position` among the claim's assertions of that kind and name. `check_type` names the proposition that was checked (`value-comparison`, `passage-presence` or `correspondence`), since two tools can use one word for different checks. `outcome` is one of `match`, `mismatch`, `not-found`, `not-checked` and `error`, each defined by its preconditions in SPEC 7.10, and `native_outcome` and `native_reason` carry the words `repro verify` prints. Where a declared command writes a file the assertion reads, an `execution` block adds the state `repro stale` gives and each command upstream with its latest recorded re-run. `repro.record.validate` refuses a record no check could have produced, such as a `mismatch` without both values or a stored value on a check that did not run, and a word, check type or address kind a reader does not know is kept and never read as a `match`. The assertions are evaluated by the functions `repro verify` uses. The command executes nothing, writes only the output it is asked for (`-o FILE`, or standard output) and exits 0 whatever the outcomes. Experimental: the format is `repro.check/0.1-experimental`, each record names it, and the JSON Schema generated from the model is `docs/schemas/repro.check-0.1-experimental.schema.json`. `repro verify` prints and exits as before.
- **`repro export ro-crate` writes the check records as an RO-Crate 1.3 metadata document.** Each file a record names is a `File` with the `sha256` of its bytes on disk, its media type, the digest the manifest pins and its `validity`; the manifest is a `File`; each claim is a schema.org `Claim`; each checked assertion is a `CheckAction` whose `instrument` is the checker and whose `object` is the claim; and each file read is a `PropertyValue` holding the stored value, the value under a declared conversion where there is one, and the address as canonical JSON, with one for each member of an aggregate. A command under `regenerations` is described once, with its argv, declared inputs and declared output, and its latest recorded re-run is a `CreateAction` as Process Run Crate 0.6 describes one, with `instrument`, `object`, `result`, `startTime`, `endTime` and `actionStatus`; a check refers to the commands upstream of what it reads and does not restate them. Conformance to Process Run Crate is declared only where a re-run is recorded. What RO-Crate has no term for (the address inside a file, the printed value, the check type, the outcome) comes from a profile of this tool's own, `https://reproducible.science/ro-crate/claim-check/0.1/`, version `0.1-experimental`, whose page defines each term. The document is written from the records and nothing else, and `repro.export.rocrate.from_ro_crate` reads it back into them, so nothing a record holds is lost; a file no record names is not in the crate. A `match` this version does not understand is written `not-checked`. A record carries no license, so the crate says in words that none is stated. `-o DIR` writes `DIR/ro-crate-metadata.json`, a path ending in `.json` is written as that file, and with no `-o` the document goes to standard output. No date is taken when the document is written, so the same records give the same bytes. A check record also gains `checker.url`, where the checker is described. Experimental: this is one tool's export format, and its terms may change before `1.0`.
- **`repro export sarif` writes a SARIF 2.1.0 log from the check records, for GitHub code scanning.** A `mismatch` is a result at `kind: fail`, `level: error`, a `not-found` one at `level: warning`, and an `error` a result and a notification that marks the run as failed. An assertion that was `not-checked` is never a result, since it is neither a finding nor a pass: it is a notification at `level: warning` on the invocation, counted by reason in the run's properties. A `match` is written only with `--include-matches`, as `kind: pass`; GitHub does not read `kind` and shows each as a warning alert, so the flag is for other viewers. Each result is shown at one line: that of the sentence, where the claim quotes one from a text file that holds the passage exactly once, and otherwise the assertion's line in `repro.yaml`; the files it reads are related locations and a line is never estimated. `partialFingerprints` carries a digest over the claim's id, the assertion's kind, name and position and the address or passage it declares, also as `primaryLocationLineHash`, the only one GitHub reads, so an alert follows its assertion when a sentence moves. The log is a lossy projection: the whole record is in each result's property bag under `repro/checkRecord`, and the README lists the fields SARIF carries nowhere else. A log of more than 5,000 results, which GitHub truncates, is written whole with a warning. The command executes nothing and exits 0 whatever the outcomes. `repro verify --format sarif` is unchanged.
- **`repro numbers` counts every number the manuscript prints and says which a declared assertion accounts for.** `repro verify` reports on the claims a manifest declares, and the author chose which to declare. `repro numbers` reads the text the claims read their sentences from, each artifact a `quote` reads beside an assertion of another kind or a prose address reads, or the ones named with `--text`, and gives every number in it one standing. It is `bound` where the occurrence lies in the passage of a `quote` whose claim carries that value as `reported`, digit for digit at the printed precision, or is the value a prose address selects. It is `set aside by rule` where a named rule reads the digits as something other than a quantity: `link`, `date`, `document identifier`, `name`, `version or section`, `citation`, `label`, `list marker`, `ordinal`, `year`, `the word one`. It is `set aside with a reason` where the manifest lists its passage under the new `set_aside`, whose entries each name an `artifact`, the passage `text` and a required `reason`. Otherwise it is `unbound`, printed with its line and the words around it. The same digits reported by a claim about another passage bind nothing, and are marked `reported elsewhere` where the value has two digits or a decimal point; a match on one digit is counted and not marked. The summary carries its denominator and the four counts add up to it, `8 numbers in 1 text: 1 bound, 3 set aside by rule, 1 set aside with a reason, 3 unbound`, with a count per rule and per `set_aside` entry, and a line saying how many of the unbound are numerals and how many are number words. `--format json` prints every occurrence with its standing. It executes nothing, writes nothing and exits 0 whatever it counts, 2 with no manifest or no text to read, and `repro verify`, `repro stale` and `repro why` report as before.
- **`repro stale` says which claims read a file that is no longer what a recorded re-run produced.** `repro verify` passes a number that sits unchanged in its file after the data or the script behind that file has been edited, since the output is still the pinned one. `repro stale` executes nothing and writes nothing: it compares each command under `regenerations` with the re-runs `repro reproduce` appended to `.repro/reproductions.jsonl`, and a produced file is `current` where a re-run that reproduced ran today's command over the inputs now on disk and its output is the output now on disk, for that command and every command upstream. Otherwise it is `stale`, with the cause named once at the command where the difference is (`input changed` with both digests, `command changed`, `output changed`) and `upstream stale` with a distance on everything downstream, or `never rerun`. A file no command writes is `no producer`, counted and never graded, and a missing file or a cycle between commands is `undetermined`. So is a command whose re-run reproduced and whose later re-run over the same inputs did not: the cause is `later rerun did not reproduce`, with the later re-run's date and what it wrote. The record of re-runs is the reference and the manifest's own digests are not, so rebuilding a manifest from the files on disk does not clear a stale file; a regeneration whose recorded input digest differs from that artifact's pin is noted as `record disagrees with pin`. The summary always carries its denominator and the number of assertions that read a file with no producer. `--format json` prints the report as a graph of claims, artifacts and regenerations with their states, edges and findings. `--policy` grades as it does elsewhere: stale is a warning under `exploratory` and `publication` and an error under `strict`, and never rerun and undetermined are ignored, a warning and an error. Exit 0 where the policy passed, 1 where it failed, 2 with no manifest or no regeneration declared.
- **`repro verify --set-aside-record` gets a project out from under a record of checks that does not verify.** A damaged local record was appended to no further, and every later `repro verify` said so on standard error with no way on but moving the file by hand. The flag renames the record and its head file to `checks.jsonl.set-aside-<UTC time>` and `ledger.head.set-aside-<UTC time>`, deleting nothing, and starts a new chain whose first entry carries `set_aside`: the name the old record now has, how many entries it held, the SHA-256 of its last entry that verified, and what its chain was reported as. With `--record` it also sets aside a tracked record that does not verify or can no longer follow the local one, and the check that follows copies the tracked record afresh. It never runs unasked and is refused where every record verifies. `repro why` names each record set aside under `record of checks`, with `set_aside` on the JSON account, and the line a damaged record puts on standard error now names the flag. An entry written before this carries no `set_aside` key and reads as it did; the record's format, its field names and where it is kept are unchanged. Two tests cover what was not covered: separate `repro verify` processes started together over one repository, round after round, write one entry per change with consecutive `seq`, and a checkout whose git directory lies under another repository's `.git/modules/` records there and not in the superproject's record.
- **`repro verify` keeps a record of what each assertion said when it was checked, and `repro why` shows it.** After a check does not verify, the `reported` value, the address or the claim's text can be edited until it does, and the report of the last run shows none of that. Every `repro verify` in a git repository now appends to a local record, `repro/checks.jsonl` in the git directory `git rev-parse --absolute-git-dir` names, one entry for every assertion whose `reported` value or passage, address, claim text, artifact digest or outcome differs from the last entry recorded for it. The working tree is left as it was, so the hooks, CI and the status line are unaffected, and the record belongs to the clone as git's reflog does. `repro verify --record` also brings a tracked record, `.repro/checks.jsonl` with its head file `.repro/ledger.head`, up to the local one entry for entry, for a project whose history should travel: ask for it in the CI job that commits it, or before a release. Outside a git repository nothing is recorded unless `--record` asks. Entries are chained as the `results` ledger's are, each carrying its position and the SHA-256 of the entry before it, and written by that ledger's locked append. `repro why <claim-id>` ends an assertion's lines with the states recorded for it where there is more than one, `checked <when>: reported 0.92 at /acc, results 28943e35cdd3: mismatch` and then `since <when>: reported 0.91 at /acc, results 28943e35cdd3: verified (after mismatch: reported changed)`, shows an assertion edited since the last check as `now`, and under a claim that took the address of one renamed after a check that did not verify says `a claim named <old-id> was last checked <when> at this address: mismatch, and is no longer declared`. It reports a record whose chain does not verify with the number of the entry, marks the entries from there on `[unverifiable]`, and says where a tracked record diverges from the local one. What `repro verify` prints on standard output and the code it exits with are unchanged; a record that cannot be written, or will not be appended to because it does not verify, is one line on standard error. The chain shows an edit or a deletion inside a record and not a record cut back together with its head file; committing the tracked record is what makes that visible to someone with the repository's history. `--format json` carries `history`, `now` and `formerly` on each assertion and `records` and `no_local_record` on the account.
- **`repro why <claim-id>` says what the record establishes for one claim, and what it does not.** Under `established` it prints what is computed when the command runs: whether each file an assertion reads matches its pinned digest, the value at the declared address beside the value the manuscript prints with the outcome `repro verify` gives (`mismatch` included), and for each file the claim rests on, the files it reads and every file upstream of one, the command that writes it and the files that command reads, the recorded re-run it was compared with, its state as `repro stale` finds it and the cause where it is not `current`. Under `not established` each line names what the record does not cover: a file no command is recorded for, whose bytes are taken as given, a command with no re-run that reproduced or on a cycle, a file that is absent or whose bytes are not the pinned ones, and an assertion that is `unchecked` or `not found`, with its reason. An account then closes on what the design does not check, each line where it applies: the inputs a command declares are the author's list, the address is the author's choice, and a verified assertion says the declared value or passage is in the file. The summary carries its denominators, `1 assertion: 1 verified; 1 of 1 reads a file with a recorded producer, 1 stale`. `--format json` prints the account as one document, with the counts of the summary under `outcomes` and `states`. With no claim id the command lists the ids, and an id the manifest does not declare exits 2 and names the nearest ones. It executes nothing, writes nothing and otherwise exits 0, and `repro verify` and `repro stale` report as before.
- **`repro why` lists the warnings on each assertion.** A warning qualifies an outcome and `repro verify` prints it in brackets beside the assertion, `[short,truncated]`; `repro why` showed the outcome alone, so a quotation cut mid-number and a declared page nothing checked both read as plainly `verified`. Under each assertion there is now one line a warning, named as `repro verify` names it, `warning: truncated`, and for `page_unchecked` the reason follows: `warning: page_unchecked: page 3 was not checked: the artifact is not read page by page`. The JSON account carries them as `warnings` on each assertion. The summary line is unchanged.

### provenance-core

No significant changes.

## 0.5.5 — 2026-10-13

### citations

No significant changes.

### prereg

No significant changes.

### results-cli

No significant changes.

### reproducible-science

#### Changed

- The worked example of a number in a printed table, in the `repro` skill, the starter manifest and the specification, uses an invented table. The conformance fixtures for the `prose` locator carry the same table.

### provenance-core

No significant changes.

## 0.5.4 — 2026-10-13

### citations

No significant changes.

### prereg

#### Fixed

- **The `prereg` plugin recognises a frozen file by the rule the mod uses.** A corrupt or unreadable freeze record let the edit through, and a `**Plan sha256:**` line made any `.md`, `.markdown` or `.txt` file frozen while a file with a freeze record and another suffix was not. `frozen_file_before_edit.py` now denies an `Edit`, `Write` or `MultiEdit` to a file of any name wherever `.prereg/<name>.json` exists beside it, whatever the record holds, and applies the `**Plan sha256:**` rule only to a file named `PREREG.md`. A `PREREG.md` over 2 MB carrying that line was allowed and is now refused: the hook reads a plan of any size. A relative path was read against the directory the hook process ran in; it is now read against the `cwd` of the hook's input, the session's working directory, and a leading `~/` is the home directory. The mod's reason for refusing a plan frozen in place now reads as the plugin's does, so the two refuse in the same words in both cases, and a test compares them. `frozen_plan_changed.py` is unchanged.

#### Changed

- **A draft's `Superseded by` line reads the same from any directory, may name a plan the tool froze, and a withdrawal carries the commit that declared it.** `prereg check` looked a successor up among the documents at or below the directory it ran in, so `exp/DRAFT.md` naming `../PREREGISTRATION.md` was `superseded` from the repository's top level and `pending`, exit 2, from `exp/`. The path is now looked up in the whole repository, read from the draft's own directory, and the draft has one status wherever the check runs. A run in a subfolder lists the documents at or below it, and a successor above or beside it settles the draft; where the document that ends the chain passes it is not listed, and where it is `pending`, `CHANGED` or of an `unknown commit` the run lists it too, once, by its path from the top of the repository, and exits 2 or 1 as a run at the top does. A path that is absolute or leaves the repository leaves the draft `pending` and says so. A draft may name a `PREREG.md` frozen with `prereg freeze`, which used to read as "not a registration checked here": the plan is checked as `prereg check` checks any plan, the draft is `superseded` only where that check passes, and a plan that is not frozen or was changed after its freeze leaves the draft `pending` with the reason. Neither header line is read on a `PREREG.md` itself. A `withdrawn` document's report gains a line naming the commit that added its `**Withdrawn:**` line and that commit's date, followed across renames, or saying the line is not yet committed; the status and the exit code are as they were.

#### Added

- **`prereg check` tells a draft that was replaced, and a plan that was dropped, from a plan awaiting its freeze.** A registration frozen by a commit line whose line holds a placeholder is `pending`, exits 2 and counts against the project for good. That is right for a plan that has not been frozen yet and wrong twice over elsewhere: a plan revised three times before its freeze counted as four, and a plan that was abandoned could only leave the report by having its commit line deleted. A `**Superseded by:** <path>` line in a draft's header, read from the draft's own directory, now lists the draft as `superseded` and follows the chain to the document that ends it, which keeps its own result, so the plan is counted once and a chain ending on an unfrozen or edited document still exits 2 or 1. A `**Withdrawn:** <reason>` line lists a dropped plan as `withdrawn`, with the reason and the words that it is the document's statement and was not checked. A draft naming a file the check does not list, a chain that returns to itself, a `Superseded by` line naming nothing, and a `Withdrawn` line left empty or holding a placeholder such as `N/A` or `TBD` each leave the document `pending` and say why. Neither line excuses a document that names a commit: its header is compared text, so adding either line after the freeze is `CHANGED`. The `repro` mod leaves superseded and withdrawn documents out of the `prereg: n/m frozen` count.

### results-cli

No significant changes.

### reproducible-science

#### Fixed

- **A `prose` locator reads a number printed against the text that follows it.** The value was the whole run of non-whitespace characters after `before`, and `after` had to begin past it, so a cell of a printed table, `| 3| 0.459| 0.124|`, was read as `0.459|` and reported `value_not_numeric` whatever `after` said, and `93.1%` and a number closing a sentence could not be bound either. The value is now the whole run where `after` begins past it, and otherwise the run cut at the first place inside it where `after` begins, so `before: "| 3|", after: "|"` reads `0.459` and `after: "."` reads `3.14.` as `3.14`. With `after` omitted the run is still read whole. An anchor never splits a number: `after` may not begin, and `before` may not end, inside digits joined by a decimal point, a grouping comma or underscore, or an exponent, so `after: "9"` on `0.459` reads nothing where a cut would read `0.45`. A `before` ending inside a number, `before: "0.4"`, read the rest of it, `59`, and is now `passage_absent` with the number named in the detail. Digits attached to a preceding letter, as in `v0.5` or `H10`, are a name and not a number, so `before: "v0."` reads `5` as it did. A sign belongs to its number unless a digit or a letter precedes it: `before: "x=-"` over `x=-0.42` read `0.42` and now reads nothing, and `before: "10-"` over `10-12` reads `12` as it did. Four conformance fixtures cover a printed table, and declare the three stages as well as the outcome.
- **The plugin recognises a frozen file by the rule the mod uses.** A corrupt or unreadable freeze record let the edit through, and a `**Plan sha256:**` line made any `.md`, `.markdown` or `.txt` file frozen while a file with a freeze record and another suffix was not. `frozen_file_before_edit.py` now denies an `Edit`, `Write` or `MultiEdit` to a file of any name wherever `.prereg/<name>.json` exists beside it, whatever the record holds, and applies the `**Plan sha256:**` rule only to a file named `PREREG.md`. A `PREREG.md` over 2 MB carrying that line was allowed and is now refused: the hook reads a plan of any size. A relative path was read against the directory the hook process ran in; it is now read against the `cwd` of the hook's input, the session's working directory, and a leading `~/` is the home directory. The mod's reason for refusing a plan frozen in place now reads as the plugin's does, so the two refuse in the same words in both cases, and a test compares them. `frozen_plan_changed.py` is unchanged.

#### Changed

- **The `repro` skill and the starter `repro.yaml` list everything a manifest can declare.** Both described `metric` and `quote` and nothing else. The skill now has a row and an example for each of the five evidence kinds and the seven locators, with the fields each takes and the file formats it reads, a section on binding a number in a printed table or running text with a `prose` locator, and one on when a `quote` is the fallback and what it does not establish. The comment `repro manifest init` and `repro init` write at the top of `repro.yaml` carries the same list in short form. A test fails when a kind or locator the engine defines is missing from either.
- **`repro audit` counts a plan `prereg check` lists as `withdrawn` among what was not measured.** A withdrawal is the document's statement about itself, which the check lists and does not verify, so a repository whose only finding is a withdrawn plan is reported as could-not-check by `repro audit`, exit 2, where `prereg check` on its own exits 0. A draft listed as `superseded` is not counted: the document at the end of its chain is listed with its own result, and that result is what is read.

### provenance-core

No significant changes.

## 0.5.3 — 2026-10-11

### citations

#### Fixed

- **The plugin's skill lists the five results `citations verify` reports.** It listed three, `found`, `not found` and `unchecked`, and left out `indeterminate` and `ambiguous`. It now says that only `not found` fails a run and that `--strict` fails on the other three unresolved results as well; the comment beside `citations verify --strict` named two of them.
- **`citations add --doi` and `--arxiv` derive a key with no space in it for a family name of more than one word.** `Sanchez-Stern` gave `sanchez stern2019generating` and `de la Cruz` gave `de la cruz2019generating`, which BibTeX cannot read as a key; the entry failed its read-back, the file was restored, and the message blamed a change to the file between the check and the write. The derived key now writes the family name as one word, `sanchezstern2019generating`. A `--key` holding whitespace, a comma, a brace or another character a key cannot hold is refused before anything is written, with a message naming the characters.

#### Changed

- **[citations] The skill says to pin the passage behind a claim a manuscript paraphrases, not only one it quotes.** "Before writing any sentence that quotes a paper" was the only stated trigger, and it reads as a licence to skip the tool entirely: a manuscript that quotes no one can still make thirty claims about what thirty papers say, and each can be wrong in every way a misquotation can. `--says` and `--whose` already exist for exactly this. The skill now says when a pin is owed — a definition applied in your own setting, an identity attributed to someone, a dataset's own description your eligibility rule depends on, a method you say another paper used, a number quoted rather than computed — and names the reading that causes the trouble.

#### Added

- **The plugin's skill has a section on pinning a source and a quotation.** It says to download the source and keep the file, to pin a quotation with `citations pin` before writing the sentence that quotes it, and to give the bibliography entry a DOI or an arXiv id so its record is not keyed by a title hash. It says what `unchecked` means and that a draft with unchecked quotations has not been verified, lists the usual reasons a quotation does not resolve, and says what to record for a source behind a challenge page or a paywall.

### prereg

#### Fixed

- **The plugin's README and the package README name `prereg-style` and `osf-registration`.** Both described one skill where the plugin ships three.
- **`prereg freeze --osf --attach` uploads its files.** It asked OSF for the draft node's storage provider by the provider's own address, which OSF answers with 404 for a draft node, so the draft was created and logged and no file was attached. The upload link is now read from the draft node's list of storage providers. An upload OSF answers without a sha256 is an error and is not logged as attached.

#### Changed

- **The `prereg` plugin refuses an edit to a frozen plan or a frozen amendment.** A new `PreToolUse` hook, `frozen_file_before_edit.py`, denies an `Edit`, `Write` or `MultiEdit` to a file with a freeze record (`.prereg/<name>.json` beside it) or to a plan carrying a `**Plan sha256:**` line, and tells the model to record a note with `prereg log` or a change with `prereg amend`. An amendment still in draft and an unfrozen plan are edited as before. `frozen_plan_changed.py` still runs after an edit and reports a frozen file changed by another route, such as a shell command.

#### Added

- **The plugin ships two more skills, `osf-registration` and `prereg-style`.** `osf-registration` covers putting a frozen plan on OSF: writing the plan so it maps onto OSF's Preregistration form, a dry run with `osf.build_draft`, `prereg freeze --osf` with its metadata flags, checking the draft against the plan, the step a person has to take, and how to confirm and log the approval that follows. `prereg-style` is one author's opinionated style for writing a plan, and says so at the top: none of it is required by the tool. Both are in the `prereg` plugin and in the `reproducible-science` bundle.
- **[prereg] `check --manuscript FILE` fails a frozen plan whose hypotheses the manuscript never mentions.** Every existing check asks whether a plan was altered; none asked whether it was reported. A plan can be frozen, unedited, hash-matching, its log intact, and carry a hypothesis that reaches no paper, and the tool stays silent. Hypothesis labels are read from the plan above the log, in both the template's `**H1.**` form and the `## H1:` heading form, and are matched against the manuscript on word boundaries so `H10` does not report `H1` as present. A plan written for work the manuscript will not carry declares that once, with `**Manuscript:** none`, rather than standing as a permanent false alarm. The flag is opt-in because the tool cannot know which manuscript a plan belongs to.
- **`prereg register --confirm <draft id>` registers one plan with nobody at the terminal, where `PREREG_UNATTENDED_REGISTER=1` is set.** The typed phrase is skipped only when both are given: the flag has to equal the id of the draft the plan's log recorded, and the variable has to be exactly `1`. The flag without the variable, or with another draft's id, is refused before the token is read or anything is sent. `--all` is refused with it, and so is a directory with several plans below. What the terminal would have shown is printed, and the log entry ends `unattended, confirmed by --confirm`. Without `--confirm` nothing changes: the phrase is asked for on the terminal, and the variable alone does nothing. `link` still needs the phrase.
- **`prereg status` reads from OSF whether the plan's registration is pending approval, approved and public, approved and embargoed, or withdrawn, and `prereg register` now says how a pending one gets approved.** `status` sends one GET per registration and asks for no phrase. For a pending registration both commands print the two ways it ends: an admin opens OSF's email "Pending Registration - Admin Notification" ("Pending Embargo - Admin Notification" for an embargo) and clicks the first link, which approves, where the second cancels and cannot be undone; or OSF approves it by itself after 48 hours. `status --log --access LEVEL` records the approval in the plan's log the first time it is seen, as `osf registration <id> observed approved, public`. `status` exits 0 for a registration in effect, 2 for one pending or not yet made, and 1 for one withdrawn or not readable; run where no plan governs, it reports every plan below. `prereg` does not approve a first registration: OSF's API has no request for it.

### results-cli

#### Added

- **`results annotate <file>... --kind <namespace:type> --ref <reference>` records that named files correspond to something outside the ledger.** The event holds each file's sha256, the target's kind and reference, and the status `linked, not checked`: the tool fetches nothing and compares nothing. `--kind` is any `namespace:type` in lowercase, such as `wandb:artifact`, `doi:dataset` or `osf:node`, and a malformed kind writes nothing. `--digest <algorithm:hex>` records the digest the outside system reports, and `--by`, `--note` and `--location` are optional; no session information is recorded. `results verify` lists every annotation, and with `--files` marks a file `STALE` where it is no longer the bytes the link was stated of and `MISSING` where it is gone; neither changes the exit code.
- **`results review <file>...` records that someone examined named files, and what they found.** The event holds each file's sha256, a scope, a procedure, a verdict of `pass`, `fail`, `partial` or `uncertain`, and the reviewer; all four flags are required, and a verdict outside the four writes nothing. `--model` records the model the caller names, and inside Claude Code the harness, its version and the session identifier are read from the environment. `results verify` lists every review, and with `--files` marks a subject `STALE` where the file is no longer the bytes reviewed and `MISSING` where it is gone; neither changes the exit code. The record is self-reported and unsigned, and the readout says so.

### reproducible-science

#### Fixed

- **The plugin READMEs list the skills each plugin ships.** The bundle's README said "Three skills" and "Three commands" where it ships a skill for each of the four tools, `prereg-style`, `osf-registration`, and four commands; it now names each skill with one line on what it is for, and states no count of them. The bundled `citations` skill listed three of the five results `citations verify` reports and described `--strict` as failing on a failure only; both are corrected.
- **The status row counts a `MISSING` line as a changed sealed file only under `file hashes:`.** `results verify --files` prints the same word for a subject of a review or an annotation that is gone, four spaces deep, and the row counted each as `1 changed` and pinned `1 sealed file changed`.

#### Changed

- **The plugin refuses an edit to a frozen plan or a frozen amendment, as the mod does.** A new `PreToolUse` hook, `frozen_file_before_edit.py`, denies an `Edit`, `Write` or `MultiEdit` to a file with a freeze record (`.prereg/<name>.json` beside it) or to a plan carrying a `**Plan sha256:**` line, and tells the model to record a note with `prereg log` or a change with `prereg amend`. An amendment still in draft, an unfrozen plan and every other file are edited as before. It ships in the `reproducible-science` bundle and in the `prereg` plugin. `frozen_plan_changed.py` still runs after an edit and reports a frozen file changed by another route, such as a shell command. Every other hook still reports and never blocks, and the new hook exits 0 and allows the edit on any failure of its own.

#### Added

- **The plugin's `citations` and `repro` skills say how a source is pinned and where other people's files are kept.** The `citations` skill gains a section on pinning: download the source and keep the file, pin a quotation with `citations pin` before writing the sentence that quotes it, give the bibliography entry a DOI or an arXiv id so its record is not keyed by a title hash, read `unchecked` as no measurement, the usual reasons a quotation does not resolve, and what to record for a source behind a challenge page or a paywall. The `repro` skill gains a section on third-party files: each is kept in an ignored folder and pinned by sha256 with its address, and a freeze commit holds the plan, the code and the tests.
- **`repro init` writes ignore rules for the lock and temp sidecars and for a `sources/` folder.** Both forms do it: with a name, in the new project's directory, and with none, at the top of the project it is run in. The rules are `*.provenance-lock`, `*.provenance-tmp` and `sources/`, each group under a one-line comment. A project with no `.gitignore` gets one; an existing `.gitignore` keeps every line and gains only the rules it lacks, and a rule anchored another way, such as `/sources/`, counts as present. The output names what was added, as `added to .gitignore: sources/`, and a second run adds nothing. Where git already tracks a file under `sources/`, the folder rule is not added, because it would hide each new file the project puts there; the sidecar rules still are, and the output says `left sources/ out of .gitignore: git tracks N file(s) there.`

### provenance-core

No significant changes.

## 0.5.2 — 2026-10-08

### citations

#### Changed

- **A `citations` command that reads no source no longer loads the PDF and spreadsheet libraries.** Importing the package imported the checker, and the checker imports `pdfplumber`, `pypdf` and `openpyxl`, so `citations lint`, `citations add` and every other subcommand waited most of a second for libraries only `verify` and `coverage` call. The package now imports a public name the first time it is asked for, and the command starts in `citations.entry`, which loads the subcommand asked for. Every name importable from `citations` is still importable, and `citations.cli:main` still runs the whole command. `citations lint --claims DIR --json` on a one-source project went from a median of 1.34 s to 0.48 s.

#### Added

- **A `not found` quotation whose every word is in the source says so.** A quotation made of two or more stretches of the source, in the source's order, with source text left out between them and nothing marking the gap, is still `not found` and still fails. Its result now carries `reason = "omission"` and one gap for each place text was left out, with the position in the quotation, the source text left out there and its length, and `passage`, the source from the first piece to the last; the report prints the left-out text and the passage with it marked, names the two repairs (quote the passage as the source reads, or mark the gap with an ellipsis in a manuscript), and the `not found` row counts these separately. Every piece must match exactly under the existing folding and be at least 20 characters, and a cut may fall only between whole tokens of the source, at white space the source itself has, so a number, a signed number or a hyphenated word cut short, punctuation left out, pieces in another order and a short fragment are a plain `not found` as before.
- **`citations lint --claims` and `citations verify` report a pinned source the last commit still holds.** `git rm --cached` takes a file out of the index and out of no commit, so until the removal is committed the text is still in `HEAD`. `lint --claims` lists such a source as `in HEAD`, whether or not the file is on disk, and its `--json` rows carry `index` and `head` for every source listed. `verify` names the sources it read that the last commit holds and git no longer tracks. Both remain warnings: no verdict and no exit code changes.
- **`citations lint --claims` takes no directory.** Given none, it reads `claims` in the working directory, or the nearest `claims` above it inside the same repository; outside a repository it reads the working directory alone. A named directory is read as before.
- **`citations pin --occurrence N` pins one occurrence of a passage the source repeats.** A passage occurring more than once is refused as `ambiguous`, and the remedy was a `prefix` and `suffix` written into the claims file by hand. `--occurrence N` counts from 1 in the source's order and writes the anchors that single that occurrence out, widened through the source until the anchored passage occurs once and checked before anything is written, so the entry resolves under `verify --strict`. Anchors that would pass 1,000 characters a side are refused. Without the flag a repeated passage is still refused, and the refusal names the flag.
- **`citations pin` says when the source it read is tracked by git, or covered by no ignore rule.** One line after the quotation is written, with the same remedy `verify` names. It refuses nothing and does not edit `.gitignore`. An ignored source, and a source outside any repository, get no line.
- **`citations restore` writes the source's passage for a quotation that leaves text out, as a separate record.** It applies only to an omission whose shortest passage is the only one the quotation can have been taken from, every other way of fitting it spanning a longer passage that contains it, and which leaves out at most `--max-omitted-tokens` tokens, 1 by default; the limit never changes which passage is restored. The source must be pinned. The claims file it is given is never edited; the derived claim goes in `<name>.restored.yaml` beside it, with the original quotation, the bounded passage in the source's own characters, the source and text digests, the offsets of the passage and of each omitted stretch, how many ways the quotation fits, the rule and its limits, and the software version. `verify` counts restored quotations on a line of their own.
- **`citations verify` and `citations lint --claims DIR` report a pinned source that git tracks.** A claims file pins its source by a sha256, so no check needs the source committed, and a committed one is somebody else's text published with the repository. `verify` prints how many sources it read from a tracked file and names the first ten, each with the claims file that pins it; `lint --claims` lists every one, and prints them as JSON with `--json`. The finding is a warning: it changes no verdict and no exit code, with or without `--strict`, and `lint --claims` exits 0 whatever it finds. The report names the remedy, which is to untrack the file and add an ignore rule, the record's sha256 and url being what `citations fetch` restores it from. Outside a repository, and on a machine without git, nothing is reported.

### prereg

#### Changed

- **`prereg freeze` is refused where git holds a pinned source.** This changes what a freeze does: one that succeeded before can now exit 1. A freeze names a commit, and a source text in that commit can only be removed later by rewriting history, which changes the commit's identifier. Where `citations` is on `PATH`, a freeze first runs `citations lint --claims --json` beside the plan; where the index or the last commit holds a source the project's claims files pin, it prints the count, the first ten by path, and the way out of each case, writes nothing (no record, no log entry, no timestamp request, no lock file, nothing sent to OSF), and exits 1. A source is listed as `tracked` (in the index and the last commit), `staged` (in the index alone), or `in HEAD` (untracked with `git rm --cached`, or deleted, with the removal not yet committed). The ways out are to untrack the files, add an ignore rule, commit and freeze again, or to pass the new `--allow-tracked-sources`, with which the freeze goes ahead and names the sources after its report. A plan, an amendment and a forced re-freeze of a plan frozen in place are treated alike. Only an answer refuses: with no `citations` installed, a version that cannot be asked this way, no claims directory, a timeout, or nothing held, the freeze goes ahead as before. Nothing of `citations` is imported.

### results-cli

No significant changes.

### reproducible-science

#### Changed

- `repro audit` counts `*.restored.yaml` files, which `citations restore` writes, apart from the claims files the authors declared: `claim_records`, `claims` and `quotations` leave them out, and `restored_claim_records` and `restored_quotations` are reported where there are any.

#### Added

- **`repro audit` reports how many sources the audited repository commits.** Where `citations verify` read a source that git tracks, the step's `found` ends with `N sources tracked by git`, in the table and in the record. No outcome and no exit code changes.

### provenance-core

No significant changes.

## 0.5.1 — 2026-10-07

### citations

#### Changed

- `citations verify` keeps the text `pdftotext` extracts between runs and reads several sources at a time. An entry is filed under the sha256 of the source's bytes, the extractor's version and its arguments, so a changed source or a different poppler is extracted again, and the report counts the readings taken from the cache. `--no-cache` or `CITATIONS_NO_CACHE=1` reads every source and keeps nothing. Normalizing the extracted text and listing a source's folder are also faster. Checking 947 quotations in 29 PDFs took 20.6 seconds before, 8.1 on a first run and 2.7 on a second.

### prereg

No significant changes.

### results-cli

No significant changes.

### reproducible-science

#### Fixed

- `repro verify` reads each artifact once in a run. A manifest with many claims over one table parsed the table, and extracted the document's text, once for every claim, and scanned every row for each; under a profiler, checking 1,000 numbers bound to one CSV took 17.5 seconds and now takes 1.4. A second verification in the same process still reads every file again. The manifest itself is read with libyaml's loader where PyYAML has it.

### provenance-core

No significant changes.

## 0.5.0 — 2026-10-06

### citations

#### Fixed

- **[citations] A `prefix` or `suffix` written without its separating space singles out its occurrence.** A YAML plain scalar cannot begin or end with a space, so `suffix: in August` reached the check welded to the passage, matched nothing, and the passage stayed `ambiguous` with advice to widen an anchor that was already wide enough. The anchors are now tried as written and then with a space at each seam.
- **[citations] A run that read none of its sources is no longer a pass.** `Report.ok` documented that a run measuring nothing is not one and implemented it only for a claims set with no quotations, so a project whose every source went `unchecked` — a `pdftotext` `extract_cmd` declared without `{} -`, an extractor not installed, a reference directory that moved — exited 0 under a closing line beginning "nothing failed". Measured on this project's own corpus: 35 quotations, no source read, reported as 35 verified. A run resolving even one quotation is unaffected; `--strict` remains what refuses a partially unresolved one, and is now named in the summary when there is something for it to refuse.
- **[citations] A source declaring `extract_cmd: cat {}` is read off disk instead of refused.** `cat` given only the source names no rendering, just the file's bytes, which `citations` already reads itself for a text file. It was treated as a program outside the default allowlist, so on one public site 23 quotations against a plain-text source were `unchecked` and asked for `--allow-extractor cat`. The declaration is now read in process, runs no program and needs no consent, and the result names the reading `text`. `cat` with anything beyond the source, such as `cat -n {}` or a second path, is still a command and is still refused without consent.
- **[citations] `citations audit` reads a field that shares a line with the next one.** The field pattern required a newline before the following `name =`, so an entry writing `volume = {103}, number = {2}, pages = {483--490}, year = {2016},` on one line — which BibTeX permits and reference managers emit — gave `volume` a value swallowing every field after it. The entry then disagreed with the record its own DOI resolves to, on a value nobody had typed wrong, and the real defects in the same report were harder to see for it. Found on a manuscript where two of three flagged entries were this and the third was a genuine dropped author.
- - **[citations] A stroked letter resolves to the letter rather than being deleted.** NFKD leaves
    `ł`, `đ`, `ħ`, `ŧ`, `ð` and `þ` whole, so the fold's character class removed them and
    Kozłowski became `koz owski` -- one name in two tokens, matching nothing. Every author with
    one of those letters in their surname was a disagreement to `citations audit` and unfindable
    to `citations resolve`.

#### Added

- **[citations] `citations fetch` downloads the sources a claims directory pins.** A public repository carries each source's sha256 and not the source, so a reader who cloned one had every pin and no file, and `verify` answered `unchecked` for every quotation. `fetch` tries the arXiv PDF, the URL the claims file records, and the open-access locations Europe PMC and OpenAlex list for the DOI, and installs a download only when its sha256 is the pinned one; bytes that differ are reported as `differs` and never written. Measured on claims directories with no source on disk: 12 of 16 arXiv-hosted sources came back byte-identical and 1,920 of 2,515 quotations resolved; for a biomedical study, 27 of 94 sources and 58 of 175 quotations. A source that records no `url`, `doi` or arXiv id is reported as `no location`, and `citations pin` names that gap when a quotation is pinned against one. ([#79](https://github.com/elliottower/reproducible-science/pull/79))
- **[citations] A workbook, a `.docx` and an article's XML are pinned as the publisher's file and read by a named, versioned extractor.** `citations` read PDFs and plain text, so such a source could be pinned only as a text a script had made from it, and a reader's download never matched the pin; pinned directly, a workbook or a `.docx` reached the PDF readers and was `unchecked`, and an `.xml` was matched with its markup in place. `sheet-rows` (`.xlsx`, `.xls`, `.csv`), `docx-text` and `jats-text` now run in process and are recorded on each result as `name@version`; `openpyxl`, `xlrd` and `python-docx` are optional extras (`citations[sheets]`, `citations[docx]`), and a reader that is not installed or a version this build does not ship is `unchecked` with the reason. A source block can name `extractor`, `extractor_version`, `sheet`, `empty_cells` and `derived_sha256`, the digest of the extracted text, which `citations pin` records with the first quotation. `verify` fails a source whose extractor no longer produces that text, and `fetch` checks the original and then the extracted text, reporting `differs`, `text differs` and `text unchecked` as separate outcomes. Measured on 72 Europe PMC and NCBI articles holding 314 quotations pinned against tag-stripped text: 194 resolved in the XML as served and 308 resolve through `jats-text`; pinned that way, `fetch` installed 72 of 72 originals on an empty checkout and `verify` found 308 of 308. On 22 publisher workbooks, 1,164 of 1,437 quotations pinned against hand-made text resolved unchanged through `sheet-rows`, 264 were ambiguous across sheets and 9 were not found. ([#82](https://github.com/elliottower/reproducible-science/pull/82))
- **[citations] `citations audit` searches by title for an entry with no DOI and no PMID, and compares it with the record it finds.** Such an entry was counted under `no id` and nothing read its authors, year or title back, so the entries least likely to be right were the entries no check reached. The search asks Semantic Scholar, Crossref, OpenAlex and arXiv in turn and accepts a candidate under the rule `citations resolve` already uses: title similarity of at least 0.87, the first author's surname among the candidate's authors, and the year within one. A DOI found that way is fetched from Crossref or DataCite and compared like any other, an arXiv id is read as the DataCite DOI `10.48550/arXiv.<id>`, and the report lists each identifier found so it can be added to the entry. An OpenAlex record with no DOI is reported as `found` with nothing compared. An entry no service has a record for is `not found`, which does not fail the audit under `--strict`, because a book, a report and a thesis land in that row as well as an invented reference. An entry every service refused is `unresolved`, never `not found`. Search answers are cached with the registry payloads, a refusal is not cached, and `--no-search` restores the earlier report. `--json` carries `found_kind`, `found_id`, `found_by` and `searched` on each entry.
- **[citations] `citations verify --claims` reads a source from the library when the path its claims file names is empty.** A public repository carries each source's sha256 and not the source, so a clone had every pin and no file, and every quotation was `unchecked ... file not found` even on a machine whose library held the document. `verify` now looks in the library's `pdfs/` for a file under the record's own filename and reads it only if its bytes hash to the pinned sha256. A claims file with no pin is never read from the library and its reason says a pin is needed; a library file under that name with other bytes is not read and the reason gives both digests. The report counts the sources read from the library and names the directory. `verify` writes nothing and downloads nothing, a source present at the named path is read from there as before, and `--strict` and the exit codes are unchanged. Measured on fresh clones against one library: 175 of 175 quotations in a 94-source biomedical claims directory resolved where 175 had been `unchecked`, and 1 of 1 in a second; a third, whose 7 sources the library does not hold, stayed at 18 `unchecked`.
- - **[citations] `citations lint --authors` reads a bibliography's author lists back against the
    registry each entry's own identifier names.** Two agents in one session attributed
    "Mediational E-values" (Epidemiology 30(6):835-837, 2019) to VanderWeele and Chiba while
    quoting the paper's DOI, 10.1097/EDE.0000000000001064, whose authors Crossref gives as Smith,
    Louisa H. and VanderWeele, Tyler J. A VanderWeele and Chiba paper exists on another subject in
    another journal, so the entry was two real papers written as one and every field named
    something that exists -- which is why reading the reference list does not catch it. The
    identifier was right both times and nothing read the names. The check reports four kinds of
    finding from one comparison: a name belonging to another paper, a list that stops early with
    no marker, `and others` or `et al.` written into a `.bib`, and the registry's names in another
    sequence. It compares family names folded, with both spellings of an accent and with surname
    particles stripped as well as kept, so Krzyżosiak against Krzyzosiak is not a finding. Entries
    with no identifier are skipped and counted rather than passed, findings exit non-zero under
    `--json` as well as in the report, and resolved lists are cached beside the bibliography so a
    second run needs no network.
- - **[citations] `citations lint --bib` reports an author list written as family names with no
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

### prereg

#### Fixed

- **[prereg] `prereg check` says whether a log grew or shrank.** Every mismatch between the log and the count recorded beside the plan hash was reported as an entry removed from the end, including a log holding one entry more than recorded. A longer log now names the added entries, says when one carries no chain value and so was written by hand, and says that `prereg log` brings the record up to date. `check` no longer prints "The plan was edited after freezing" beneath a log problem when the plan hash matches. ([#88](https://github.com/elliottower/reproducible-science/pull/88))
- **[prereg] An `OSF_TOKEN` in a `.env` that is a named pipe is found.** The lookup accepted only a regular file, and `is_file()` is false for a pipe, so a `.env` exposed by a secret manager (a 1Password-managed environment is one) was passed over as if absent. A pipe is now read in a thread and abandoned after 60 seconds with an error saying the secret source did not deliver, so a dismissed approval prompt cannot hang the command. The token is read only when a request is about to be made, after the typed confirmation, so a cancelled command never triggers the approval prompt.
- **[prereg] `prereg check` reads the plans below a governing plan as well.** Run where a `PREREG.md` already governed the directory, it checked that plan and stopped, so a second plan kept in a subfolder was never read: an edit to it passed, and the count of plans was one. It now checks the governing plan and every plan below the working directory, and prints the same summary line it prints at a root with no plan of its own. A directory with one plan and none below reports as before.
- **[prereg] `prereg freeze --osf` no longer rejects a plan made by `prereg new`.** The four `- File upload` headings map to no text question on purpose, because OSF answers them with files, and the push then counted them as headings it did not recognize and refused the plan as one that "would be missing" sections. Every plan the template produces carries all four, so no template plan could be pushed. A heading the mapping does not know at all is still refused.
- **[prereg] `prereg freeze --osf` reads the response keys from where OSF keeps them.** The schema fetch read `attributes.schema.blocks`, which carries each question's text and no response key, so the map came back empty and every section with content was refused as unmapped: no plan with an answer in it could be pushed. The keys are on the schema's `schema_blocks`, joined to their question by `schema_block_group_key`, which is how OSF's own validator joins them. Four OSF questions are multiple choice (Foreknowledge, Study type, Intention for causal interpretation, Blinding of experimental treatments); OSF rejects prose there, so each line under those headings has to name one of the question's options, by its full text or a prefix no other option shares, and the push now refuses before anything is written when one does not, listing the options. `N/A` leaves the question unanswered, and a section still holding the template's italic prompt is no longer sent as its own answer. An OSF error now carries OSF's explanation rather than ending in a traceback.

#### Changed

- **[prereg] `prereg freeze --osf` pushes a draft without asking, and fills its Metadata page; `prereg register --all` registers every plan below after one phrase.** A draft is private and deletable, so the push, its uploads and its metadata run unattended, and an agent can prepare every draft of a study; only `register` and `link`, which cannot be undone, ask for a typed phrase. New `freeze` flags fill OSF's Metadata page: `--subject` (repeatable; OSF will not register a draft with none, and the push warns), `--description`, `--tag`, `--category`, `--copyright-holder` with `--license` (CC-BY 4.0 by default), and `--title-prefix`; a subject, license or category OSF does not have is refused before anything is frozen. `register --all` checks every plan first and asks once, with a phrase naming the list; a plan already registered is skipped so an interrupted batch can be rerun. `register` no longer takes a server error as a failed registration: OSF has answered 502 while creating one, so after any error but a 400 it looks for the registration before retrying, and logs one found that way as `found after OSF error 502`. The token is read as `OSF_TOKEN` or `OSF_PAT`.
- **[prereg] `prereg freeze` writes nothing into the plan, and always attempts the outside timestamp.** A freeze takes one sha256 over the whole file and records it, with the commit, the time and the access level, in `.prereg/PREREG.md.json` beside the plan; the plan is set read-only and `prereg check` reports any byte that differs as `CHANGED`, with no exempt lines. The freeze adds `-text` rules for the plan, its amendments and its log to the nearest `.gitattributes`, so a checkout that converts line endings leaves them as frozen. With a results ledger at or above the plan, the access level recorded is at least the ledger's floor: the highest access level it records, and `results not opened` once it records a run. `prereg new` no longer writes a `**Status:**` line or a `## Log` section, and a draft still carrying either is refused at the freeze. `prereg log` on a plan not yet frozen is refused. A frozen plan cannot be frozen again, with or without `--force`. `--no-timestamp` is removed: a freeze that reaches no calendar, or has none configured, still freezes, says the timestamp is owed, and `prereg check` says so on every run until `prereg timestamp` makes it. `prereg freeze --osf` and `prereg register` log the draft, the attachments and the registration beside the plan; `prereg freeze --osf --access LEVEL` on a plan already frozen pushes its draft and leaves the freeze as it is. A plan frozen by an earlier version, with its freeze record and log inside the file, is not converted: `check`, `log`, `timestamp`, `register`, `link` and `freeze --force` read and write it under the rule it was frozen by, and `prereg log` on one prints a line saying that plans frozen from now on keep their log beside them.

#### Added

- **[prereg] `prereg amend` records a change to a frozen plan as a file of its own, `prereg log` keeps the log beside the plan, and `prereg check --staged` is the check a pre-commit hook runs.** `prereg amend` creates `PREREG_AMENDMENT_N.md` beside the plan with four required fields: the plan or amendment it amends, by sha256 digest (`--parent FILE` names an amendment); the sections replaced or added; the reason; and what had been seen. Where a results ledger sits at or above the plan, the access level is filled from the ledger's floor (the highest level it records, and `results not opened` once it records a run), with the number of runs recorded, and `prereg freeze PREREG_AMENDMENT_N.md` refuses an amendment that states a lower level. An amendment is frozen as a plan is, and its date is its freeze. `prereg log` writes to `PREREG.log`: each entry has the time, the note and the access level, the first entry carries the plan's digest and each later entry the digest of the entry before it, and `PREREG.log.head` records the number of entries and the digest of the last, so an entry removed from the end is reported and nothing is appended over it. `prereg check` lists the plan, then its amendments by freeze time, then the log, each frozen file with its freeze date and access level: `CHANGED` for a file that differs from its freeze, `MISSING` for one that is gone, `orphaned` for an amendment whose parent digest matches no frozen file present, `written after results were seen` under an amendment frozen at `results seen`, and `LOG ALTERED` for a log whose chain does not verify; each of `CHANGED`, `MISSING`, `orphaned` and `LOG ALTERED` exits 1. `prereg timestamp` stamps, completes and checks the timestamp of the plan and of each frozen amendment. `prereg check --staged` exits 1 and names each path when the git index holds a change to a frozen file, an amendment, a committed freeze record, a log that no longer begins with its committed entries, a log anchor whose count went down, the plan section of a plan frozen in place, or a document frozen by a commit line. No hook is installed; the README gives a two-line one.
- **[prereg] `prereg check` checks registrations frozen by a commit line.** A markdown document that records its own freeze commit, as `**Commit SHA:** b96d10a`, `**Freeze SHA:**`, `**Freeze commit:**` or a commit under a heading of one of those names, is compared with the file at that commit, with the commit line left out of both sides. A bold `**Status:**` line before the first heading after the title is part of the freeze record: it is left out of the comparison, and a status that differs from the frozen one is reported under the document without counting as an edit. Each document is listed under its own heading as `unchanged`, `appended` with the number of lines added after the frozen text, `CHANGED` with the lines added and removed and the first difference, `pending` where the line holds a placeholder, or `unknown commit` where the repository does not hold the commit or the file is not in it. A changed document exits 1; `pending` and `unknown commit` exit 2 and are counted in the summary. A repository with no `PREREG.md` and no such document reports as before.
- **[prereg] `prereg freeze` dates the plan outside the repository with OpenTimestamps, and `prereg timestamp` completes and checks the date.** A freeze is a digest recorded in the repository, and whoever holds the repository can rewrite its history, delete it and push it again; every check that reads the repository passes afterwards. The freeze now also sends the digest, with a random nonce so no calendar learns it, to four public OpenTimestamps calendars, and keeps the proof beside the plan as `PREREG.md.ots`. Within hours the calendars commit it into a Bitcoin block, and `prereg timestamp` completes the proof and reports the block's date, checked against two block explorers. `prereg check` reports the proof with no network and fails on a proof of another digest. A freeze that cannot reach two calendars still freezes and says so. An empty `PROVENANCE_CALENDARS` names no calendar, which keeps a test suite off the network.
- **[prereg] `prereg register` and `prereg link` take a frozen plan through OSF registration, and `prereg freeze --osf --attach PATH` registers a shared file with it.** `--attach` uploads a file, such as a `CONTEXT.md` several plans point at, into the draft's storage, which OSF archives into the registration; the log records each file's sha256, and the push fails if OSF reports a different hash for what it received. `register` submits the draft the log recorded at the freeze and requires `--embargo YYYY-MM-DD` or `--immediate`, with no default, because an immediate registration is public. It refuses a plan changed since its freeze, a draft made from an earlier freeze and a draft already registered. `link --anonymous` creates a view-only link that hides the contributors, for double-blind review; the log records the link's id and not its key. Every write to OSF shows what it will send and asks for a phrase naming it on `/dev/tty`, never stdin, and a process with no terminal is refused before any request. `freeze --osf` now finishes every check that can refuse, the confirmation included, before it writes the freeze. Updates to a registration are made in OSF's web interface and are not part of this command.

### results-cli

#### Changed

- **[results-cli] `results init` writes a `.results/.gitignore` that ignores only the lock files.** The ledger and its anchor are then committed with the project by default. `results verify` reported an untracked ledger as a record nobody else can check, and nothing made tracking it the default. A committed ledger is public with the repository, so a run's `note` is written as a commit message would be. A project whose own `.gitignore` lists `.results/` is unaffected until that line is removed. ([#80](https://github.com/elliottower/reproducible-science/pull/80))

#### Added

- **[results-cli] `results timestamp` dates the ledger's head with OpenTimestamps, and `results verify` reports a chain rewritten after it was stamped.** The anchor file catches truncation and a hand-edited line, and not the ledger and its anchor rewritten together, since whoever can write one can write the other. A proof of the head, kept under `.results/timestamps/` and named by the length and head it covers, dates every earlier event through the chain. `results verify` reads the proofs with no network and fails with `TIMESTAMP CONTRADICTS THE CHAIN` when a proof's head no longer matches the chain at its length, which is the rewrite the anchor alone cannot see. A damaged chain is refused rather than stamped.

### reproducible-science

#### Fixed

- **[reproducible-science] A quotation occurring more than once is reported as ambiguous.** `citations` returns `ambiguous` for a passage found twice, and 0.4.2 had no mapping for it, so `repro verify` reported `evidence.error ... KeyError: 'ambiguous'`. It is now `extraction=invalid` with reason `quotation_ambiguous`, flattening to `not_found`, the stages an ambiguous row selector takes. It is kept apart from `passage_ambiguous`, which says a document states two different numbers: a passage written twice contradicts nothing, and the fix is a `prefix` or `suffix` in the record. ([#88](https://github.com/elliottower/reproducible-science/pull/88))

#### Changed

- **[reproducible-science] The `repro` mod says when a project has no manifest.** A project with no `repro.yaml` at or above its top was drawn with three rows and no `repro` row, which read the same as a project with nothing to check. It now gets the fourth row as `repro: no manifest`, as a project with no ledger reads `results: no ledger`.
- **[reproducible-science] The plugin hooks, the mod and the freeze cross-check read a plan frozen whole.** `prereg freeze` now records a freeze in `.prereg/<name>.json` beside the file and writes nothing into it. The hook that speaks before an analysis runs under an unfrozen plan stays silent where that record exists; the hook that reports a frozen plan changed compares a plan or an amendment with the digest in its record; the cross-check of the freeze a claim names reads the commit from the record as well as from a status line; and the mod refuses an `Edit` or `Write` to any file with a freeze record, amendments included, while an amendment still in draft is edited freely. The mod's `prereg` field no longer counts the log line of `prereg check` as a plan.
- **[reproducible-science] `repro verify --regenerate` is removed; `repro reproduce` replaces it.** `repro verify` no longer executes anything, and its report no longer carries `regenerations`. The old flag compared the regenerated output's bytes and reported `diverged` for any difference, including a re-run that wrote every number the manuscript prints into a file ordered differently. The `regenerations` key in `repro.yaml` keeps its name and shape, so a manifest written for the flag runs under the new command unchanged. In the library, `verify()` loses its `regenerate` parameter, `Policy.regeneration_diverged` becomes `regeneration_changed` and `regeneration_failed`, and re-runs are assessed with `Policy.assess_reproduction`.

#### Added

- **[reproducible-science] `repro`, a Claude Code mod for research sessions.** The plugin's hooks speak only in a project that already keeps a ledger or a plan, and cannot refuse anything. The mod refuses an edit to a frozen `PREREG.md`, notes a manuscript edited or an analysis run with no ledger behind it, puts the three gates and the state of the project's records in the system prompt, shows that state in a row above the prompt with one field per tool, pins a warning under the prompt when a frozen plan was edited, the ledger does not verify or runs were recorded with nothing sealed, and adds `/repro-status`. It follows the project whose files a session touches, whatever folder the session started in. Installed separately (`/plugin install repro@reproducible-science`): it uses the function-hooks API, which is early access. ([#81](https://github.com/elliottower/reproducible-science/pull/81))
- **[reproducible-science] `repro verify` reads values from Excel workbooks, Parquet, Feather and Arrow, Stata, SPSS, R data frames, HDF5 and NetCDF.** These formats were `format_unsupported`. A new `sheet` locator addresses a workbook by sheet, column and key predicate. A `table` locator addresses Parquet, Feather, Arrow, `.dta`, `.sav` and an `.rds` data frame through the same row resolution as delimited text, so a predicate matching two rows is ambiguous in every format. An `array` locator addresses an HDF5 dataset or a NetCDF variable by path and index, and NetCDF values are unpacked and a fill value is absent. Each reader is an optional extra (`sheets`, `parquet`, `stata-spss`, `rds`, `hdf5`, `netcdf`). Without one the check is `unchecked` and names the extra, and a file that is not what its suffix says is `unchecked` as unreadable. An `.rds` is parsed by `rdata` without starting R, and pickles are refused by name because reading one runs code. ([#90](https://github.com/elliottower/reproducible-science/pull/90))
- **[reproducible-science] The `repro` mod shows what `repro verify` found, and each row says what it counted.** A project with a `repro.yaml` at or above its top gets a fourth row above the prompt: `repro: 56/56 checks verified`, one check per assertion. A pinned file that changed is named beside the count, so checks read from a file that is not the declared one are never shown as plainly verified. A project with no manifest keeps three rows. The `results` row is now `6/6 runs sealed, 17 claims bound`: the runs recorded after inputs were sealed over all runs, so a run recorded over nothing sealed lowers the first number, and runs whose id begins `smoke_`, `prefreeze_`, `test_` or `dryrun_` are test runs and are left out. The `citations` row reads `63/63 quotes found`. The warning line names a manuscript number that disagrees with its artifact (`1 number mismatched`), with quotations worded apart; a pinned quotation that is not in its source after `/repro-verify` (`1 quotation not found`), counted from the `not found` line of `citations verify` so an unchecked quotation is not reported as missing; and a number bound to a test run (`1 claim on test runs`). A manifest under another name or below the top of the project is not found.
- **[reproducible-science] The `repro` mod's rows name the next command.** A row whose tool has a step still to take shows the command directly after it: `citations: none pinned  →  citations pin`, `repro: no manifest  →  repro manifest init`, an unfrozen draft at `prereg freeze`, a ledger with no runs at `results seal`. A project with nothing set up shows one hint, `repro init`. A row with something to report carries no hint.
- **[reproducible-science] `repro audit` runs the four tools over a clone of somebody else's repository.** `repro audit <url-or-path> [--commit SHA]` clones the repository into a cache directory at that commit (default: the remote's HEAD) and runs `prereg check`, `results verify --files`, `citations verify`, `citations audit` on each tracked `.bib` file and `repro verify` over the clone. It prints one row per check and writes `<name>_audit.json` and `<name>_audit.log`: the commit and tree audited, the installed version of each tool, counts read from the repository's own files, and each step's command, exit code and output. A check that could not be made (a source not on this machine, a registry that did not answer) and a check with nothing to read are reported apart from one that failed, and the command exits 1 for a failure, 2 when a check could not be made or nothing was established, and 0 otherwise. Nothing is written into the audited repository, `--offline` skips the steps that reach a registry, and `--target` takes a YAML file that pins a commit and tree, names unusual paths, or adds steps.
- **[reproducible-science] `repro init` with no name sets up an existing project.** Run inside a project, it works at the git root, or in the working directory outside a repository, and creates whichever of four records are missing: a plan (`prereg new .`), a results ledger (`results init`), a citations library with a `claims/` directory (`citations init`), and a starter `repro.yaml`. It prints one line per record, `created` or `already present`, and the next step for each record it created. A record that exists is never edited, so a second run changes no file. A plan written by hand as `prereg*.md` counts as present, and no library is made where `$CITATIONS_HOME`, a `.citations/` above or the per-user library already governs the project. `repro init <name>` scaffolds a new directory as before and now also writes a starter `repro.yaml` in it.
- **[reproducible-science] `repro manifest init` writes a starter `repro.yaml` for an existing project.** Run at or below the top of a project, it writes the manifest at the git root, or in the working directory outside a repository, and refuses to overwrite one. It pins the files named on the command line by sha256, each with an id, a path relative to the manifest and a media type. With no file named it pins the data files the adapters read at the shallowest level of `results/`, `paper/artifacts/`, `outputs/` and `data/` that holds any, at most 20, and a manuscript when exactly one of `paper`, `manuscript` or `main` with a `.tex`, `.md` or `.txt` suffix exists, and it prints the list as a guess to edit. It writes two example claims, a `metric` for the first number in a pinned JSON or YAML file and a `quote` for a line of a pinned text source, each checked by the engine before it is written, so the manifest passes `repro verify` as written. An example with nothing to point at is written as a YAML comment. A manifest with no claim declared still fails `repro verify` with `report.empty`. `repro verify` in a project with no manifest names this command.
- **[reproducible-science] `repro reproduce` runs a manifest's declared commands again and checks that the manuscript's numbers still hold.** Each record under `regenerations` runs in a directory holding only its declared inputs, and every claim that reads its output is checked against the file it wrote, by the comparison `repro verify` uses and at the precision the manuscript prints. A record has one of five outcomes: `reproduced` (every number still holds, whether or not the bytes match), `changed` (a number is now different, printed with its old value, its new value and the value the manuscript prints), `unchecked` (the output was written and a number could not be read from it), `failed` (the command did not finish, or finished and wrote nothing) and `not_rerun` (skipped with `--skip` or `--only`, or an input is not the one the record names). A record that reads the output of one that did not reproduce runs over the pinned copy and names it. Each invocation appends what it observed to `.repro/reproductions.jsonl`: the environment, the command, exit code and duration, the digest of every input and output, the files written and not declared, and both values of every number. No host, user or absolute path is recorded. The command exits 1 when a number changed or a command failed.

### provenance-core

No significant changes.

## 0.4.2 — 2026-08-29

### citations

#### Fixed

- The plugin's hook never ran. `hooks.json` listed its event at the top level, where the loader
  reads only `hooks` and `modules`, so the plugin reported `failed to load` and no hook was ever
  registered — from the file's first commit through 0.4.1. The events now sit under `hooks`.
  Anyone who installed this plugin expecting drift to be reported on every edit was not getting it.

### prereg

#### Fixed

- The plugin's hook never ran. `hooks.json` listed its event at the top level, where the loader
  reads only `hooks` and `modules`, so the plugin reported `failed to load` and no hook was ever
  registered — from the file's first commit through 0.4.1. The events now sit under `hooks`.
  Anyone who installed this plugin expecting drift to be reported on every edit was not getting it.

### results-cli

#### Fixed

- The plugin's hook never ran. `hooks.json` listed its event at the top level, where the loader
  reads only `hooks` and `modules`, so the plugin reported `failed to load` and no hook was ever
  registered — from the file's first commit through 0.4.1. The events now sit under `hooks`.
  Anyone who installed this plugin expecting drift to be reported on every edit was not getting it.

### reproducible-science

#### Fixed

- The plugin's two hooks never ran. `hooks.json` listed `PostToolUse` and `PreToolUse` at the top
  level, where the loader reads only `hooks` and `modules`, so the plugin reported `failed to load`
  and neither hook was ever registered — from the file's first commit through 0.4.1. The events now
  sit under `hooks`, and all four plugins in this workspace had the same defect.

  The suite passed throughout, because `test_plugin_hooks.py` parsed `hooks.json` itself and asked
  the runtime nothing. A test now asserts the top-level shape for all four plugins and fails on the
  shape that shipped.

### provenance-core

No significant changes.

## 0.4.1 — 2026-08-29

### citations

#### Fixed

- A quotation pinned to a `.py` source was graded `unchecked` rather than resolved. `.py` was
  absent from `TEXT_SUFFIXES`, so the file went to `pdftotext`, which answered `Syntax Error:
  Couldn't read xref table` and left every quotation in it unchecked — reported as a source the
  reader could not open, when nothing there needed a PDF reader at all. Python sources are now
  read directly off disk, and any claim quoting one should be re-verified. ([#54](https://github.com/elliottower/reproducible-science/pull/54))

### prereg

No significant changes.

### results-cli

No significant changes.

### reproducible-science

#### Added

- A `PreToolUse` hook that says a registered plan was never frozen, before the analysis runs
  instead of after it. `frozen_plan_changed.py` notices a plan edited after its freeze; nothing
  noticed a plan carrying no freeze at all, so the mechanism engaged only for authors who had
  already opted in. The new hook reads the command about to run, and where that command invokes
  an analysis under a directory holding a `PREREG.md` with no `**Plan sha256:**` line, it says
  so. It never denies the call and stays silent when there is no plan, when the plan is frozen,
  and when the command is not a run. ([#53](https://github.com/elliottower/reproducible-science/pull/53))

### provenance-core

No significant changes.

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
