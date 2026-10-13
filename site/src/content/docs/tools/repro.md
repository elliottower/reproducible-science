---
title: Repro
description: Repro — Reproducible Science
---

<!-- Generated from packages/repro/README.md. Edit that file, not this one. -->

[![pypi](https://img.shields.io/pypi/v/reproducible-science)](https://pypi.org/project/reproducible-science/)
[![python](https://img.shields.io/pypi/pyversions/reproducible-science)](https://pypi.org/project/reproducible-science/)
[![license](https://img.shields.io/pypi/l/reproducible-science)](https://github.com/elliottower/reproducible-science/blob/main/LICENSE)
[![docs](https://img.shields.io/badge/docs-live-blue)](https://reproducible.science/)

**[Run it in your browser](#run-it)** — every command on this page, in a live notebook at the bottom. No install.

Check whether a paper's claims match its artifacts.

Part of [reproducible-science](https://github.com/elliottower/reproducible-science) alongside `citations`, `results` and `prereg` — see the [documentation](https://reproducible.science/tools/repro/).

## Install

```bash
pip install reproducible-science
```

This installs `repro` and its three dependencies: [`prereg`](https://pypi.org/project/prereg/), [`citations`](https://pypi.org/project/citations/), [`results-cli`](https://pypi.org/project/results-cli/).

## Try it

```bash
repro demo
```

Writes `repro-demo/` and runs the real workflow over it: seal the inputs, record the run, bind the claim, verify the evidence. It then edits the manuscript twice and re-runs `repro verify`, so the first thing you watch the tool do is catch something. The two edits fail differently — a file that is not the file that was declared, and a number that contradicts the run — and the report says which. Both are restored, and the directory is left verifying, with a README naming three more failures to produce by hand.

Offline, deterministic, and under a second per command.

## Quick start

```bash
repro init my_experiment
```

```text
initializing /home/you/work/my_experiment
  wrote /home/you/work/my_experiment/CLAUDE.md
  wrote /home/you/work/my_experiment/repro.yaml
  wrote .gitignore: *.provenance-lock, *.provenance-tmp, sources/
done.
```

`init` spawns `prereg new`, `results init` and `citations init`, whose own output it does not
relay; the lines above are everything it prints itself.

This creates:

```text
my_experiment/
    CLAUDE.md           tells Claude Code about the tools
    repro.yaml          the manifest, with nothing pinned yet and two example claims as comments
    .gitignore          ignores the tools' lock and temp sidecars, and sources/
    my_experiment/
        PREREG.md       the plan (OSF headings)
        results/        run outputs
        tests/          tests for the analysis
    .results/           ledger.jsonl and ledger.head
    .citations/         citation library, itself a git repository
    claims/             claim files for citation verification
    data/               raw data
    scripts/            analysis scripts
    figures/            output figures
```

## Set up a project that already exists

```bash
cd my_project
repro init
```

```text
/home/you/work/my_project

  plan         already present  PREREG.md
  ledger       created          .results/
  citations    created          .citations/, claims/
  manifest     created          repro.yaml (artifacts pinned: 3, example claims: 2)

  wrote .gitignore: *.provenance-lock, *.provenance-tmp, sources/

next:
  ledger       `results seal <inputs>` before a run, `results run <outputs>` after it
  citations    `citations pin` writes a quotation into claims/ once it resolves
  manifest     edit the claims in repro.yaml, then `repro verify`
```

With no name, `init` works at the top of the project it is run in (the git root, or the working directory outside a repository). It creates whichever of the four records are missing and never edits one that exists, so a second run creates nothing and says everything is already set up.

| record | present when | created by |
|---|---|---|
| plan | a `PREREG.md` at the top or up to three levels below it, or any `prereg*.md` at the top | `prereg new .`, which also makes `tests/`, `results/` and a `.gitignore` where there is none |
| ledger | `.results/` | `results init` |
| citations | a library governs the project and it has a `claims/` directory | `citations init` for the library, and an empty `claims/` |
| manifest | `repro.yaml` | `repro manifest init` with no file named |

A library governs the project when `citations` finds one: `$CITATIONS_HOME`, a `.citations/` here or above, or the per-user library. Where one does, none is made here, because a project-local library would replace the shared one for this project. Inside a git repository `.citations/` is a directory the repository tracks. Outside one, `citations init` gives it a repository of its own.

Both forms of `init` then see that the project's `.gitignore` holds three rules, and report what they added:

```gitignore
# Sidecars a locked or interrupted write leaves beside a file. They hold nothing.
*.provenance-lock
*.provenance-tmp

# Third-party sources: papers, full texts, datasets. Pinned by sha256, never committed.
sources/
```

A project with no `.gitignore` gets one holding those lines. An existing `.gitignore` keeps every line it has and gains only the rules it lacks, at its end; a rule written another way, such as `/sources/`, counts as present. The `sources/` rule is left out where git already tracks a file under `sources/`, because the project keeps its own files there and the rule would hide each new one; the output says so, as `left sources/ out of .gitignore: git tracks 2 file(s) there.`, and the sidecar rules are still added. A second run adds nothing, and prints no `.gitignore` line unless that rule was left out. `sources/` is where the examples in the `citations` documentation keep the files a claims file pins, and no command creates it here.

## Write a manifest

`repro verify` reads `repro.yaml`, the manifest that pins a project's files and declares what the manuscript claims about them. In a project that has none:

```bash
cd my_experiment
repro manifest init
```

```text
wrote /home/you/work/my_experiment/repro.yaml
  pinned 2 artifacts, found by looking under results/, paper/artifacts/, outputs/, data/ and for one manuscript
    metrics  results/metrics.json
    paper    paper.md
  That list is a guess. Remove an entry under `artifacts`, or add one with its
  `shasum -a 256`; or delete repro.yaml and name the files:
      repro manifest init <file> ...
  example claims, to edit: example-number, example-quote

next: repro verify
```

It writes `repro.yaml` at the top of the project (the git root, or the working directory outside a repository) and never overwrites one. Each artifact is a file pinned by sha256. Name the files to pin, or name none and it looks for data files the adapters read (the formats in the table below) at the shallowest level of `results/`, `paper/artifacts/`, `outputs/` and `data/` that holds any, at most 20, and for a manuscript when exactly one of `paper`, `manuscript` or `main` with a `.tex`, `.md` or `.txt` suffix exists at the top or under `paper/` or `manuscript/`. Hidden directories, virtual environments, `node_modules`, directories of more than 1000 entries and files over 50 MB are passed over.

The two example claims show the commonest shapes: a `metric`, a number at a JSON Pointer in a pinned JSON or YAML file, and a `quote`, a passage in a pinned text source. Each is read out of the pinned files and checked before it is written, so the manifest verifies as written. An example with nothing in the project to point at is written as a YAML comment. A manifest with no claim declared fails `repro verify` with `report.empty`, because a run that checked nothing is not a pass; declare one claim and it reports on that claim and on every pin.

## Verify everything at once

```bash
repro verify
```

Reads `repro.yaml` and checks every declared evidence assertion against the artifact it names. It spawns nothing: `prereg`, `results` and `citations` are separate commands.

## Run it again

```bash
repro reproduce
```

Runs each command declared under `regenerations` in `repro.yaml`, in a directory holding only its declared inputs, and checks every claim that reads its output against the file it wrote. A record is `reproduced` when every number the manuscript prints from it still holds, whether or not the bytes match.

| outcome | what happened |
|---|---|
| `reproduced` | re-ran, and every number the manuscript prints from it still holds |
| `changed` | re-ran, and at least one number is now different |
| `unchecked` | re-ran and wrote its output, but a number could not be read from it |
| `failed` | the command did not finish, or finished and wrote nothing |
| `not re-run` | never executed: skipped, or an input is not the one that was pinned |

`--skip ID` leaves a record out, such as a long training run, and `--only ID` runs the ones named. A record that reads the output of one that did not reproduce still runs, over the pinned copy, and says so. Each invocation appends what it observed to `.repro/reproductions.jsonl`.

This executes what the manifest names. `repro verify` never does.

## After an edit

```bash
repro stale
```

`repro verify` passes a number that sits unchanged in its file after the data or the script that file was computed from has been edited: the output is still the pinned one. `repro stale` compares each command declared under `regenerations` with the re-runs `repro reproduce` recorded in `.repro/reproductions.jsonl`, and says for every claim whether the files it reads are still the ones a re-run was made over. It executes nothing and writes nothing.

| state | what it means |
|---|---|
| `current` | a recorded re-run that reproduced ran this command over the inputs now on disk, its output is the one now on disk, and the same holds for every command upstream |
| `stale` | re-runs are recorded and none matches the files now on disk, here or upstream |
| `never rerun` | a command writes the file, and no re-run of it that reproduced is recorded |
| `no producer` | no declared command writes the file, so there is nothing upstream to compare |

A stale file is reported with its cause, at the command where the difference is: `input changed`, with the input, the digest the re-run read and the digest on disk, `command changed`, or `output changed`. Everything downstream is `upstream stale`, with the nearest stale command and how many steps up it is, so one edit is one finding however many claims rest on it. A missing file and a cycle between commands are `undetermined`, and so is a command whose re-run reproduced and whose later re-run over the same inputs did not (`later rerun did not reproduce`): the record holds two runs that disagree.

Freshness is relative to the recorded re-runs, never to the digests a manifest carries for its own regenerations: a manifest rebuilt from the files on disk agrees with them whether or not a command ran. Commit `.repro/reproductions.jsonl`, because a clone without it reports every produced file `never rerun`. `current` means consistent with a recorded re-run. Whether the command would reproduce now is what `repro reproduce` establishes. An input the manifest does not declare is invisible here, and an edit to it changes no state.

The summary says what each count is a count of:

```text
  1 stale, 0 never rerun, 0 undetermined, 2 current of 3 assertions that read a file with a recorded producer
  4 assertions read 2 files no command is recorded for: nothing upstream to compare
  6 claims: 1 stale, 0 never rerun, 2 current, 0 partly outside the record, 3 outside the record, 0 undetermined
```

Under `--policy publication`, the default, a command that is stale, never rerun or undetermined is a warning. `exploratory` ignores the last two and `strict` fails on all three. A file with no producer is counted and never graded. `--format json` prints the report as a graph: claims, artifacts and regenerations, each with its state, the edges between them with the digests compared, and the findings. A pinned file that no longer matches its pin is a `BROKEN PIN`, which `repro verify` reports and this does not.

## For one claim

```bash
repro why responders
```

`repro why` prints, for one claim, each assertion as `repro verify` evaluates it now and each file the claim rests on as `repro stale` finds it, and then what the record does not cover. It executes nothing, writes nothing and exits 0 for any claim the manifest declares: `repro verify` and `repro stale` are the checks that fail. With no claim id it lists the ids.

Here a command `sum` writes `totals.json` from `counts.json` and `totals.py`, `repro reproduce` recorded one re-run of it, and `counts.json` was edited afterwards:

```text
repro.yaml

responders
  Thirty-five participants responded.

established
  assertion 1 of 1: metric responders
    totals (totals.json): matches its pinned digest ce260cfba0a8
    totals at /responders: holds 35
    the manuscript prints 35: verified
  chain
    totals (totals.json): stale
      written by sum: python3 totals.py
      which reads counts (counts.json), script (totals.py)
      re-run of 2026-10-13T19:44:16+00:00 reproduced, and its output is the bytes now on disk
      input changed: counts (counts.json): the re-run of 2026-10-13T19:44:16+00:00 read dfb342fd85a5, on disk b9109751e9cb
    counts (counts.json): no producer, 1 step up
      no command recorded
    script (totals.py): no producer, 1 step up
      no command recorded

not established
  counts.json: no command is recorded for it; its bytes are not the pinned ones and are taken as given
  totals.py: no command is recorded for it; its bytes are pinned and taken as given
  the inputs each command declares are the author's list; a file a command reads and does not declare is invisible
  the address is the author's choice; nothing checks that it holds the quantity the sentence means
  a verified assertion says the declared value or passage is in the file, not that the analysis is right

  1 assertion: 1 verified; 1 of 1 reads a file with a recorded producer, 1 stale
```

Every line under `established` is computed from the files and the record of re-runs when the command runs: the pin of each file an assertion reads, the value at the declared address, the value the manuscript prints with the outcome `repro verify` gives, and then each file in the chain with the command that writes it, the re-run it was compared with, its state and the cause where it is not `current`. A `mismatch` is listed there too.

Each line under `not established` names a file no command is recorded for, a command with no re-run that reproduced, or an assertion that was not checked. The last three lines are the same for every claim. `--format json` prints the same account as one document: the assertions, the chain with its edges and findings, and each `not_established` line with a `kind` and the file, command or assertion it names.

## Every number the text prints

```bash
repro numbers
```

`repro verify` reports on the claims a manifest declares, and the author chose which to declare. `repro numbers` reads the manuscript's text and counts every number in it, so the denominator is the text's. It executes nothing, writes nothing and exits 0 whatever it counts.

Here `paper.txt` is three lines, one claim quotes `Thirty-five participants responded` and reports `35` from `totals.json`, and the manifest sets one passage aside:

```text
repro.yaml

  paper (paper.txt)
    line 1     61%  thirty-five participants responded, 61% of the 57 invited
    line 1     57   responded, 61% of the 57 invited in 2025. responders
    line 2     4.2  responders were older by 4.2 years (table 2). the
    8 numbers: 1 bound, 3 set aside by rule, 1 set aside with a reason, 3 unbound

  set aside by rule: 1 name, 1 label, 1 year
  set aside with a reason: 1 in paper "took 12 minutes": how long the form takes, not a result
  8 numbers in 1 text: 1 bound, 3 set aside by rule, 1 set aside with a reason, 3 unbound
  3 unbound: 3 numerals, 0 number words
  0 of the 3 unbound print a value an assertion reports, outside the passage it reports it for; 0 more match on one digit and are not marked
```

Each number stands in exactly one place, so the four counts add up to the total:

| standing | what it means |
|---|---|
| `bound` | the occurrence lies in the passage of a `quote` whose claim also carries that value as `reported`, digit for digit at the printed precision (`2,364` and `2364` agree, `0.5` and `0.50` do not), or it is the value a prose address selects |
| `set aside with a reason` | it lies in a passage the manifest lists under `set_aside` |
| `set aside by rule` | a named rule reads the digits as something other than a quantity |
| `unbound` | printed, and nothing in the manifest accounts for it |

The same digits `reported` by a claim about another passage bind nothing. That occurrence is unbound, marked `(reported elsewhere)` on its line, and counted in the last line of the summary. It is marked where the value has two digits or more, or a decimal point. A single digit matches some reported value in most manifests, so a bare `4` is counted in the same line as matching on one digit and is not marked.

A cardinal written as a word is counted as any other number, because `thirty-eight claims are bound` is a claim. The summary says how many of the unbound are numerals and how many are number words.

The text read is each artifact a claim reads its own sentence from: one a `quote` reads in a claim that also offers an assertion of another kind, or one a prose address reads. A `quote` alone in its claim is a quotation from a source, and the source is not counted. `--text <artifact-id>`, repeatable, names the texts instead.

A number is digits with an optional sign, grouping commas, a decimal point and an exponent, as the prose address reads one, and a cardinal below one hundred written as one word. `10-12` is two numbers, `12,13` is two, and a percent sign stays with its number without being part of its value. Nothing is dropped. Digits that are not a quantity are counted under the first of these rules that holds:

| rule | what it sets aside |
|---|---|
| `link` | digits inside a URL |
| `date` | the three parts of a date written `2026-10-13` |
| `document identifier` | the number after `rfc`, `iso`, `iec`, `ieee`, `ansi`, `ecma`, `fips`, `pep`, `arxiv`, `doi`, `isbn`, `issn`, `pmid` or `pmcid`, as in `rfc 6901` and `arxiv 2609.22111`, and the digits of a DOI |
| `name` | digits with a letter immediately before them, `v15zw` and `sha256sum`, digits a hyphen or underscore joins to a part that holds a letter, `gpt-4` and `9750` in `i7-9750h`, and digits that open a run of letters and digits holding more digits, as a hexadecimal digest does |
| `version or section` | digits joined by two or more full stops, `0.5.5` |
| `citation` | whole numbers from 1 up, alone in square brackets: `[12]`, `[3, 7-9]` |
| `label` | the number after `section`, `figure`, `table`, `equation`, `appendix`, `chapter`, `page`, `algorithm`, `listing`, `theorem`, `lemma`, `proposition`, `corollary`, `definition`, `footnote`, `step` or `line`, or the usual abbreviation of one, and both ends of a range written `2-4` |
| `list marker` | a whole number of one or two digits alone in parentheses, `(1)` |
| `ordinal` | digits with `st`, `nd`, `rd` or `th` attached |
| `year` | four digits from 1800 to 2099 with no sign, separator, decimal point or percent sign |
| `the word one` | the word `one`, which is a pronoun more often than a count |

A binding or a `set_aside` entry takes precedence over a rule, so a year a claim reports is bound. An em or en dash before a number is punctuation: `accuracy—92` holds the number 92, joined to no name and carrying no sign.

The rules read characters and not meaning, and where telling two readings apart would take a judgment the rule is left as it is. A bare count of 1,950 printed `1950` is set aside as a year and `[12, 18]` as a citation. A status code, `exit 2`, is counted, because it is a statement the text makes about a program. A number inside a printed listing of code or of a manifest is counted, because the extracted text does not say where a listing starts. A page number alone on its line, which looks like a table cell, is counted. The JSON carries every occurrence with the rule that set it aside, so each rule can be audited.

To declare that a passage holds no claim, list it with the reason:

```yaml
set_aside:
- artifact: paper
  text: took 12 minutes
  reason: how long the form takes, not a result
```

`text` is matched as a quotation is, every number inside each place it occurs is set aside, and `reason` is required. An entry whose passage is not in the text is listed with a count of 0. `--format json` prints, per text, every number with the line it is on, its offset in the normalized text, the value read, its standing, and the rule, the claims that bind it or the reason.

## What it reads

A number is checked at an address the manifest declares, in the addressing the format already has:

| format | locator | address | extra |
|---|---|---|---|
| JSON, YAML | `tree` | RFC 6901 pointer, `/metrics/accuracy` | |
| CSV, TSV, PSV | `table` | column and a key predicate, `where: {model: resnet}` | |
| Parquet, Feather, Arrow | `table` | column and a key predicate | `parquet` |
| Stata `.dta`, SPSS `.sav` | `table` | column and a key predicate | `stata-spss` |
| R data frame `.rds` | `table` | column and a key predicate | `rds` |
| Excel `.xlsx`, `.xls` | `sheet` | sheet, column and a key predicate | `sheets` |
| SQLite | `sqlite` | table, column and a key predicate | |
| NumPy `.npy`, `.npz` | `array` | array name and index | `arrays` |
| HDF5 `.h5`, NetCDF `.nc` | `array` | dataset path and index, `/runs/accuracy` | `hdf5`, `netcdf` |
| PDF, text | `prose` | the literal text on either side of the value | |

```bash
pip install "reproducible-science[parquet,sheets]"
```

A predicate matching two rows is reported as ambiguous and never resolved to the first. Without the extra a format needs, its checks are `unchecked` and name the extra to install. A file that is not what its suffix says is `unchecked` as unreadable. A NetCDF value is the one a NetCDF reader reports, unpacked by its `scale_factor` and `add_offset`, and a fill value is absent.

Pickles (`.pkl`, `.joblib`, `.pt`) are never opened, because reading one runs code. An `.rds` is parsed by [`rdata`](https://pypi.org/project/rdata/), which starts no R process and evaluates nothing in the file.

## A fraction printed as a percentage

A file holds `0.0424` and the manuscript prints 4.2%. The assertion declares the conversion by name:

```yaml
- {kind: metric, artifact: results, name: attrition, reported: "4.2", pointer: /attrition, conversion: percent}
```

| conversion | the file stores | the manuscript prints |
|---|---|---|
| `percent` | a fraction, `0.042` | a percentage, `4.2` |
| `fraction` | a percentage, `4.2` | a fraction, `0.042` |

The stored value is converted exactly, by moving its decimal point, and then compared at the precision the manuscript prints: `0.0424` is 4.24 and agrees with `4.2`, and `0.0426` is 4.26 and does not. A `tolerance` is in the printed unit. `metric`, `table` and `value` take the field, and so does each side of a `correspondence`. The two names are the whole set. No assertion takes a multiplier or an expression, and a manifest naming any other conversion does not load.

`repro verify` and `repro why` show both values:

```text
  ok    attrition    metric   /attrition = 0.0424 (4.24 as a percentage)
```

```text
    results at /attrition: holds 0.0424, 4.24 as a percentage
    the manuscript prints 4.2: verified
```

In `--format json` a decision carries `extracted`, `conversion` and `converted`.

## Decimal places, and a value exactly halfway

The precision of a comparison is the precision of `reported` as written: `"3.20"` is compared at two decimal places and `"3.2"` at one, with the stored value rounded half to even. `places` states that precision a second time, where a table or a journal fixes it:

```yaml
- {kind: metric, artifact: results, name: effect, reported: "4.2", pointer: /effect, places: 1}
```

`reported` must then be written to exactly that many decimal places, and the stored value must round to it. A value printed as `4.20` in a table declared to one place does not verify, whatever the file holds, and neither does `3.1` declared to two:

```text
  MISS  effect-two   metric   effect: manuscript prints 4.20, which is 2 decimal p
```

```text
    results at /effect: holds 4.2051
    the manuscript prints 4.20, declared to 1 decimal place: mismatch (places mismatch)
```

`metric`, `table` and `value` take `places`, under `printed_precision` only: a manifest declaring it with `absolute` or `relative` does not load.

A stored value exactly halfway between two printed values has two correct roundings. `4.25` at one place is `4.3` in a spreadsheet, which rounds half away from zero, and `4.2` in Python or R, which round half to even. Either verifies, and the output says it was a tie:

```text
  ok    tie-up       metric   /attrition = 0.0425 (4.25 as a percentage), an exact  [exact tie: 4.2 or 4.3]
```

```text
    results at /attrition: holds 0.0425, 4.25 as a percentage
    an exact tie between 4.2 and 4.3: rounding half up prints one and half to even may print the other
    the manuscript prints 4.3: verified
```

A printed value that is neither neighbor is a mismatch, and a tie is exact: `4.2500001` is not one, and only `4.3` verifies against it. In `--format json` a decision at a tie carries `tie`, with `lower`, `upper` and `printed`.

## A number over several runs

Ten runs exist, and the manuscript reports their mean. A `metric` binds the sentence to one file, and passes whichever run that file is. An `aggregate` names every run and checks that the printed value is the stated statistic of all of them:

```yaml
- kind: aggregate
  name: accuracy
  reported: "0.914"
  statistic: mean
  count: 10
  members:
    - {artifact: seed-0, locator: {kind: tree, pointer: /accuracy}}
    - {artifact: seed-1, locator: {kind: tree, pointer: /accuracy}}
    # ... one member per run, ten in all
```

`statistic` is `mean`, `median`, `min`, `max`, `sum` or `count`. A member is an artifact and a locator from the table above, so the ten values may sit in ten files or at ten addresses in one. `count` is required and must equal the number of members: a manifest stating ten and listing nine does not load, and neither does one listing a member twice.

```text
  ok    accuracy     aggregate accuracy: mean of 10 = 0.9137
```

The best of the ten runs printed as their mean is a `mismatch`, `manuscript prints 0.921, mean of 10 is 0.9137`.

The statistic is computed exactly, over rationals, and rounded once to the precision the manuscript prints. Runs holding `0.264` and `0.099` have a mean of exactly `0.1815`, a tie at three places, so `0.181` and `0.182` both verify and the output says `[exact tie: 0.181 or 0.182]`; in floating point the same mean is a hair below the boundary. `mode`, `tolerance`, `conversion` and `places` apply as they do to a `metric`: `conversion: percent` converts each stored fraction before the mean is taken, and is refused with `count`. There is no standard deviation in the set.

Every member must hold a number. A member whose file is missing leaves the assertion `unchecked`, and one whose address does not resolve or holds no number makes it `not_found`, with the member named:

```text
  GONE  accuracy     aggregate member 4 of 10 (seed-3): /accuracy does not resolve
```

The statistic of the members that did resolve is never compared. `repro why` lists each member's pin and stored value and then the statistic, `repro stale` treats every member's file as read by the claim, and in `--format json` a decision carries `members`, `statistic` and `computed`. The assertion binds the printed value to the listed runs. Whether those are all the runs there were is the author's declaration.

## On every commit

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/elliottower/reproducible-science
    rev: v0.5.5
    hooks:
      - id: repro-verify
```

`repro-verify` reads the `repro.yaml` in the repository being committed to and fails when a
declared number no longer matches the artifact behind it. Use `repro-verify-strict` to fail on
a check that could not run as well as one that disagreed.

Verifying writes nothing. `test_read_only.py` asserts that a verification creates no files,
modifies none, and still writes nothing when it fails, which is what makes it safe to run
inside a commit: a verifier that could edit an artifact is one that could be made to edit an
artifact into agreeing with the claim.

This repository runs the hook on itself, against the `repro.yaml` at its root.

## Audit a repository you did not write

```bash
repro audit https://github.com/someone/study.git --commit 4f2a9c1
```

Clones the repository into a cache directory at that commit (default: the remote's HEAD), runs the four tools over the clone, and writes `study_audit.json` and `study_audit.log` in the current directory. Nothing is written into the audited repository, and a path to a local repository is cloned the same way.

| the clone keeps | check |
|---|---|
| a `PREREG.md`, or a registration frozen by a commit line | `prereg check` |
| `.results/ledger.jsonl` | `results verify --files` |
| a claims directory | `citations verify --claims <dir>` |
| each tracked `.bib` file | `citations audit --bib <file>` |
| `repro.yaml` | `repro verify` |

```text
command           exit  outcome          what it found                                 what it could not establish
prereg.check      0     passed           3 plans: 3 unchanged, 0 changed, 0 not        -
                                         frozen
results.verify    1     failed           chain intact: 153 events, anchored; 4         -
                                         file(s) changed or missing since they were
                                         recorded.
citations.verify  1     could not check  not found 0                                   unchecked 18 file not found
repro.verify      2     nothing to read  no repro.yaml here or above.                  -
```

Each row carries one of four outcomes. `failed` is a finding about the repository. `could not check` means a source is not on this machine or a registry did not answer, and `nothing to read` means the repository keeps no record of that kind. Neither is a pass. A step left out is listed as `not run` with the reason. The command exits 1 when a check failed, 2 when one could not be made or nothing was established, and 0 otherwise.

A quotation whose source the repository does not carry is read from the citations library when a file there matches the SHA-256 the record pins. `citations audit` reaches Crossref, DataCite and PubMed, and `--offline` skips it. An entry whose identifier did not fetch is counted as unresolved, never as agreeing or disagreeing.

Where `citations verify` read a source that git tracks, `what it found` ends with the count, as `1 source tracked by git`. The clone holds only what the repository commits, so the count is of source texts published with it. It changes no outcome and no exit code.

The record holds the commit and tree audited, the installed version of each tool, counts read from the repository's own files under `declared`, and each step's command, exit code and full output under `steps`. `--out` names where it is written and `--cache` where the clone goes.

`--target` takes a YAML file for a repository the defaults do not fit. It can pin `commit` and `tree`, name paths under `layout` (`claims`, `manifest`, `ledger`, `bibliographies`, and `globs` to count), and list `steps`. A step named like a default replaces it, and any other is added. A tree that differs from the pinned tree is recorded and the audit continues.

```yaml
repository: https://github.com/someone/study.git
commit: 4f2a9c1d0c0e4b7a9f3e2d1c0b9a8f7e6d5c4b3a
layout:
  claims: paper/quotes
steps:
  - name: results.coverage.manuscript
    argv: [results, coverage, paper/main.tex]
```

## The workflow

```bash
prereg freeze                         # lock the plan
results seal PREREG.md analysis.py    # hash inputs
results access "read metadata" --level "metadata only"

# run the computation

results run output.json --run-id exp_001
results claim "ICC = 0.42" --run-id exp_001 --confirmatory --location "Table 2"
repro manifest init output.json       # once: pin the files, write example claims to edit
repro verify                          # check everything
```

## What's included

| Tool | CLI | PyPI | What it does |
|------|-----|------|-------------|
| prereg | `prereg` | [`prereg`](https://pypi.org/project/prereg/) | Freeze a plan before running, record what changed after |
| citations | `citations` | [`citations`](https://pypi.org/project/citations/) | Verify quotations resolve in pinned source artifacts |
| results | `results` | [`results-cli`](https://pypi.org/project/results-cli/) | Seal inputs, record outputs, bind claims to runs, verify the chain |

## Inside adduce

[adduce](https://github.com/QHarshil/adduce) scores a repository for reproducibility across
categories. Installing the extra registers one rule with it, so a repository that declares a
`repro.yaml` has its evidence assertions checked as part of `adduce check`:

```bash
pip install "reproducible-science[adduce]"
adduce check .
```

The rule reports an aggregate — every assertion holding is a pass, some holding is partial, a
pinned artifact having changed is a failure naming it — and writes the full per-assertion
report to `.adduce/repro-report.json`, since one finding cannot carry thousands of outcomes.
A repository with no manifest is out of scope rather than failing, and a verifier that cannot
run reports `UNKNOWN`: a missing toolchain is not the repository's fault.

adduce is not a dependency of this package, and this package is not a dependency of adduce.

## Claude Code

This repository is a Claude Code plugin marketplace. One plugin carries all four tools:

```bash
/plugin marketplace add elliottower/reproducible-science
/plugin install reproducible-science@reproducible-science
```

It installs a skill for each tool, `prereg-style` and `osf-registration` beside them, four commands and five hooks. The hooks are the part a CLI
cannot do, because each fires at a moment rather than when you remember to run something:

| hook | fires when |
|---|---|
| frozen file before edit | an edit targets a frozen plan or a frozen amendment; the edit is refused |
| frozen plan changed | a preregistration no longer matches the digest it was frozen with |
| unverified quotation | a passage enters a manuscript that no claim file pins to a source |
| unbound number | a number enters a manuscript that no recorded claim names |

An edit to a frozen plan or a frozen amendment is refused, with the instruction to record a note
with `prereg log` or a change with `prereg amend`. Every other hook reports and never blocks. All
of them stay silent in a project that has not opted in: no ledger, no claims directory and no
frozen plan means nothing to check and nothing said.

The commands are `/prereg-check`, `/citations-check`, `/results-check` and `/repro-check`, named alike so
there is nothing to remember about which tool answers which question.

Each tool also ships on its own, for anyone who wants one of them:

```bash
/plugin install prereg@reproducible-science
/plugin install citations@reproducible-science
/plugin install results@reproducible-science
```

The plugin ships instructions and hooks, not binaries, so install the tools as well:

```bash
uv tool install reproducible-science   # or: pip install reproducible-science
```

MIT licensed.


## Run it in your browser

<div class="nb-embed" id="run-it" data-nb="end-to-end.ipynb">
  <button class="nb-start" type="button">Start the notebook</button>
  <p>Runs here, in this tab. Nothing is installed and nothing is uploaded.</p>
</div>
