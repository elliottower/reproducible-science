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

This installs `repro` and its three dependencies: [`prereg`](https://pypi.org/project/prereg/), [`citations`](https://pypi.org/project/citations/), [`results-cli`](https://pypi.org/project/results-cli/). The code behind `repro verify`, `stale`, `why`, `numbers` and `export` is [`claims-cli`](https://pypi.org/project/claims-cli/), which this depends on and which installs by itself where nothing is to be run.

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
cd my_experiment
repro init
```

```text
/home/you/work/my_experiment

  plan         created          PREREG.md
  ledger       created          .results/
  citations    created          .citations/, claims/
  manifest     created          repro.draft.yaml, open-items.json (a draft; no repro.yaml written)

  scaffolded, nothing verified: 5 numbers left open, 1 with one candidate
    repro.draft.yaml   2 result files and paper.md pinned, a claim per number, no assertion
    open-items.json    an item per number, with the places the result files hold it

  added to .gitignore: sources/

next:
  plan         fill in PREREG.md, then `prereg freeze`
  ledger       `results seal <inputs>` before a run, `results run <outputs>` after it
  citations    `citations pin` writes a quotation into claims/ once it resolves
  manifest     fill open-items.json with an agent (the open-items skill, or the tools
               of `repro mcp`), review repro.draft.yaml, and rename it to repro.yaml
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

A project with no `.gitignore` gets one holding those lines. An existing `.gitignore` keeps every line it has and gains only the rules it lacks, at its end; a rule written another way, such as `/sources/`, counts as present. The `sources/` rule is left out where git already tracks a file under `sources/`, because the project keeps its own files there and the rule would hide each new one; the output says so, as `left sources/ out of .gitignore: git tracks 2 file(s) there.`, and the sidecar rules are still added. A second run adds nothing, and prints no `.gitignore` line unless that rule was left out. A `.gitignore` that is a symbolic link, dangling or not, is never written through, by `init` or by the `prereg new` it runs, and the output says `left .gitignore alone: it is a symbolic link, and nothing is written through one`. `sources/` is where the examples in the `citations` documentation keep the files a claims file pins, and no command creates it here.

### Claims scaffolded from the result files

The project above is the one under [Write a manifest](#write-a-manifest): `results/metrics.json`, `results/table.csv` and a `paper.md` that prints five numbers. Where a project has result files and a manuscript and no `repro.yaml`, `init` also drafts its claims, and verifies none of them. It writes two files at the top of the project, in the format the readers of CODECHECK, CORE-Bench and ClawBio files write (`claims from-codecheck`, `claims from-corebench`, `claims from-clawbio`):

| file | holds |
|---|---|
| `repro.draft.yaml` | the result files and the manuscript, pinned by sha256 under the ids `repro manifest init` gives them, and one claim per number, with the sentence holding the number as the claim's text, across line breaks, and no assertion |
| `open-items.json` | one item per claim, asking for the address of its value in a result file, with the candidates: every place the result files hold the number, each written as the inferred `value` assertion that would read it there |

The files are the ones `repro verify` finds with no manifest, and the comparison is the one it makes, at the precision printed. Which numbers become claims depends on the manuscript's format:

| manuscript | numbers scaffolded | line |
|---|---|---|
| `.md`, `.txt` | the numbers `repro verify` compares with no manifest: unbound, in digits, with two digits or a decimal point | the line of the text |
| `.tex` | the same rule, applied to the source with comments, the preamble, the arguments of commands such as `\label`, `\cite`, `\begin` and `\includegraphics`, and every command name removed, so a number in a `tabular` or in inline math such as `$0.4417$` is one | the line of the source |

An item is `unique` where exactly one candidate passes the guards the CORE-Bench reader applies: the value has at least three significant digits and is not an integer below 1000; where the words before the number name a key, column name or row label from the set the address belongs to, they name the address's own; and every split they name (test, train, validation) is among the address's words. The words read are those before the number in its own clause, at most eight: from the last comma, semicolon, colon, parenthesis or table cell before it, or from the number before it in the same sentence. In `Test accuracy was 0.874 and test loss was 0.931.` the words for 0.931 are `and test loss was`, so `/test/accuracy` holding 0.9312 does not pass. Where those words name no label of any candidate and no split, the whole sentence is read: in `Accuracy, measured on the held-out split, was 0.931.` the words before the number are `was`, the sentence names `Accuracy`, and `/test/loss` holding 0.9312 does not pass. A number in a table row is read with the row's label. A candidate in an index-like column or key never passes. `1 with one candidate` counts the unique items. Above, 0.931 is unique at `/scores/accuracy`; 480 matches one place and is an integer below 1000; 4.3% and 0.71 each match one place and have fewer than three significant digits; 0.55 matches none.

No candidate is written into the draft, so every claim stays open, and `repro verify repro.draft.yaml --policy strict` fails with `claim offers no evidence` until each is filled. An agent fills them with the `open-items` skill or the tools of `repro mcp`, writing each assertion with `basis: inferred`. An author then reviews the draft and renames it to `repro.yaml`. `init` writes no starter `repro.yaml` beside a draft, so there is one manifest to rename. Where there is nothing to scaffold, or with `--no-scaffold`, it writes the starter as `repro manifest init` does.

`init` never writes or edits `repro.yaml` for this. Where one exists it scaffolds nothing and says `claims: repro.yaml exists and was left alone, so nothing was scaffolded`. Where `repro.draft.yaml` or `open-items.json` is already there, it replaces neither, writes no starter, and names the file that is there, as `claims: open-items.json is already here and was not replaced; --force replaces repro.draft.yaml and open-items.json`. Nothing is written through a symbolic link: where either name is one, dangling or not, or resolves outside the project, `init` writes nothing, `--force` included. A result file that is a symbolic link is not read or pinned, and is listed under the block as `not checked: results/ext.json, a symbolic link, which is not followed`. `--no-scaffold` reads no result file and writes neither. `repro manifest init` writes `repro.yaml` alone, as before.

## Write a manifest

`repro verify` reads `repro.yaml`, the manifest that pins a project's files and declares what the manuscript claims about them. In a project that has none, `repro verify` reports what one could check, and writes nothing. For a project holding three files:

```text
results/metrics.json  {"model": "lasso", "scores": {"accuracy": 0.9312, "n": 480, "rate": 0.0426}}
results/table.csv     model,auc
                      lasso,0.71
```

```markdown
# Results

In 2024 we fit the lasso to 480 participants.
Held-out accuracy was 0.931, and the error rate was 4.3% (Table 2).
We ran 3 seeds; the AUC was 0.71, not 0.55.
```

```bash
repro verify
```

```text
no repro.yaml here or above.

found by looking under results/, paper/artifacts/, outputs/, data/ and for one manuscript:

  result files: 2
    JSON and YAML     results/metrics.json
    CSV, TSV and PSV  results/table.csv
  manuscript: paper.md

  candidate bindings, guessed: 4 of the 5 numbers compared agree with one of
  the 4 values read from 2 result files, at the precision printed.
  A guess says the digits agree, never that the sentence reports that value.
    guess  line 3    480    results/metrics.json /scores/n holds 480
                            ...fit the lasso to 480 participants. held-out accuracy was...
    guess  line 4    0.931  results/metrics.json /scores/accuracy holds 0.9312
                            ...participants. held-out accuracy was 0.931, and the error rate...
    guess  line 4    4.3%   results/metrics.json /scores/rate holds 0.0426, as a percentage
                            ...the error rate was 4.3% (table 2). we ran...
    guess  line 5    0.71   results/table.csv column auc, row 0 holds 0.71
                            ...seeds; the auc was 0.71, not 0.55....

  verified: 0. With no manifest no claim is declared, so nothing was checked, and
  nothing was written.

write one that pins this project's result files, with example claims to edit:

    repro manifest init
```

The files are the ones `repro manifest init` would pin, found as it finds them. The numbers the manuscript prints are the ones `repro numbers` would count as unbound, in digits, with two digits or a decimal point, so years, labels, citations and single digits are left out. Each is compared with every number a JSON or YAML file holds, in mappings and in lists, and every cell of a CSV, TSV, PSV or columnar table, by the comparison a numeric assertion makes at the precision printed. A number printed with a percent sign is also compared as a percentage. Nothing else is scaled: a number is compared as printed, without its unit or suffix, so `25.6M` is compared as 25.6 and does not match a stored 25557032. A column, a key repeated across the elements of a list, or any other key of a JSON or YAML mapping, is index-like where its whole name, ignoring case and separators, is `id`, `idx`, `index`, `step`, `global_step`, `epoch`, `iter`, `iteration`, `row` or `seed`, or it has no name; `step_size`, `gini_index`, `id_acc` and `row_count` are not. A column or a repeated key is index-like also where it holds at least ten whole numbers and at least three quarters of its consecutive pairs step by one nonzero amount, where every pair that breaks the step drops back to the first value or the least. That keeps a counter that starts again for each run of a long table or each element of an outer list, and leaves out a count with one irregular step. Guesses in an index-like column or key are listed last, each tagged `[index-like column]` or `[index-like key]`, and the headline counts them apart, as `and 4 more numbers agree only with index-like columns or keys`. Nothing is left out. One number agreeing with several rows of a column, or one key of several list elements, is one guess: a place whose value equals the number exactly where one does, then the other rows and what they hold, as `rows 0, 2 hold 0.708 and 0.712`. Guesses in JSON and YAML files are listed before guesses in tables. A long pointer is shortened in the middle in this output and kept whole in JSON. A column of whole numbers that steps exactly linearly, such as a dose series of 25 to 300 mg in steps of 25 or the n of a power table, cannot be told from a counter by its values, so it is demoted; its guesses still appear, last and tagged.

A guess is never counted as verified. At most 10,000 numbers are read from one file, and a delimited file is read no further than that. Notes name files by their path in the project, never an absolute one. At most 1,000,000 comparisons are made. A note says where either limit was reached, and the headline counts the numbers compared and how many were not. A file that cannot be read is a note. The command exits 2, as every command does with nothing to read: nothing was checked, which is neither a pass nor a failure.

`--format json` prints one document:

| key | holds |
|---|---|
| `schema_version` | `reproducible.science/survey/0.1-experimental` |
| `manifest` | `null` |
| `verified` | `0` |
| `survey.results` | the result files, relative to the project, under `tree`, `delimited`, `columnar`, `workbook`, `sqlite` or `array` |
| `survey.manuscript` | the manuscript's path, or `null` |
| `survey.notes` | what was passed over, could not be read, was skipped, or reached a limit |
| `survey.read_from`, `survey.values` | the files numbers were read from, and how many numbers |
| `survey.cut`, `survey.index_like` | files cut at the limit, and the index-like columns and keys (`results/log.json /history/*/step`) |
| `survey.compared`, `survey.not_compared` | numbers the manuscript prints that were compared, and that the limit left uncompared |
| `survey.candidates` | each guess: `printed`, `line`, `offset`, `context`, `path`, `locator` (`{kind: tree, pointer}` or `{kind: table_position, column, row}`), `stored`, `conversion`, `index_like`, and `also`: the other rows or list elements the same number agrees with, each a `locator` and `stored` |

`--format sarif` prints a run with no results, a warning notification in its invocation saying nothing was verified, and `schema_version`, `verified` and `survey` in the run's properties.

To write the manifest:

```bash
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

It changes nothing in the working tree. It does keep a record of what it checked. For every assertion whose `reported` value or passage, address, claim text, artifact digest or outcome differs from the last entry recorded for it, one entry is appended: what the assertion declared, the digest of each file it read, the outcome, and when. A check that finds every assertion as it was last recorded adds nothing, so the record grows with changes and not with runs. `repro why <claim-id>` reads it back.

| | local record | tracked record |
|---|---|---|
| where | `repro/checks.jsonl` in the repository's git directory, the one `git rev-parse --absolute-git-dir` names, so a linked worktree has its own | `.repro/checks.jsonl` in the working tree, beside the record of re-runs |
| written | by every `repro verify` in a git repository | by `repro verify --record`, which brings it up to the local record entry for entry |
| reaches | this clone only; it is never committed, as git's reflog is not | whoever has the repository, once committed with its head file `.repro/ledger.head` |

```bash
repro verify --record
```

Ask for the tracked record where the history should travel: in the project's own CI job that commits it, or before a release. A clone that finds a tracked record longer than its local one takes the entries it lacks, and goes on from there. Outside a git repository there is no local record, `repro verify` records nothing and says nothing of it, and `--record` appends to the tracked record directly. `repro audit` keeps no record in the clones it reads.

What the command prints on standard output and the code it exits with are the same whatever the record holds. Where a record cannot be written, one line on standard error says so and why, and the exit code is still the verification's:

```text
record not written: .git/repro/checks.jsonl: refusing to append to a chain reported as edited: entry 2 does not hash to what entry 3 recorded for the entry before it; `repro verify --set-aside-record` keeps it and starts anew
record not written: .repro/checks.jsonl: diverges from the local record at entry 2
```

Each entry carries its position and the SHA-256 of the entry before it, and a head file beside the record holds the number of entries and the hash of the last. These are the fields and the writer of the `results` ledger. An append holds a lock across reading the last entry and writing the next, so two checks at once write one entry after the other, and nothing is appended to a chain that does not verify. `repro why` reports an entry that was edited, removed from the middle or renumbered, with its number, shows the entries from there on as the record holds them, marked `[unverifiable]`, and says where a tracked record stops being the local one's beginning.

A record that does not verify is appended to no further until `repro verify --set-aside-record` is run, which renames it and its head file to `checks.jsonl.set-aside-<UTC time>` and `ledger.head.set-aside-<UTC time>`, deletes nothing, and starts a new chain whose first entry names the old record, the hash of its last entry that verified and what was found in it. It runs only when asked, is refused where every record verifies, and with `--record` sets aside a tracked record that can no longer follow the local one; `repro why` then names the record set aside under `record of checks`. A linked worktree and a submodule each have a git directory of their own and so a record of their own, and a check in one writes nothing to the other's or to the superproject's.

The limits are these. The chain shows an edit or a deletion inside a record. Entries cut from the end are found while the head file is as it was. A record and its head file cut back together, or deleted together and grown again, read as a shorter or a new record, and nothing inside the two files can show it. The local record has no witness outside its directory. Committing the tracked record with its head file is what makes a truncation visible, to anyone who has the repository's history and compares the heads in it. Nothing is signed or timestamped by a third party, and whoever can write the files and rewrite the history can rewrite the record. A broken record is reported and never changes what `repro verify` exits with, under any policy.

An assertion is followed across edits by its claim's id, its kind, its name, and its position among the claim's assertions of that kind and name. A claim given another id starts a new history. Where the last recorded state of an assertion of a claim that is no longer declared was not `verified`, `repro why` says so under any assertion that now reads the same artifact at the same address.

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

A number that changed is printed as stored then and now beside what the paper prints, and in the printed unit too where the assertion declares a `conversion`:

```text
  changed     rates  1 of 1 numbers changed
                attrition  0.044 (4.4 as a percentage) then, 0.042 (4.2 as a percentage) now, paper prints 4.4
```

`--skip ID` leaves a record out, such as a long training run, and `--only ID` runs the ones named. A record that reads the output of one that did not reproduce still runs, over the pinned copy, and says so. Each invocation appends what it observed to `.repro/reproductions.jsonl`.

Run under GitHub Actions, an entry also says where: a `witness` with `kind`, `repository`, `workflow`, `run_id`, `run_attempt`, `sha`, `ref` and `runner_os`, copied from the `GITHUB_*` and `RUNNER_OS` variables when `GITHUB_ACTIONS` is `true`, and absent from every other run. The command prints `witnessed in GitHub Actions run 123456 of owner/repo, as the environment said`, and `repro stale` and `repro why` name the run beside the re-run they compare with. The variables are whatever the process was given and nothing is checked against GitHub: the run's page and log, at `https://github.com/<repository>/actions/runs/<run_id>`, are what a reader checks the entry against.

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

Where an assertion has been checked in more than one state, its lines end with the record of those checks. Here the manifest reported `0.92`, `repro verify` found a mismatch, and `reported` was then edited to the value in the file:

```text
  assertion 1 of 1: metric accuracy
    results (results.json): matches its pinned digest 28943e35cdd3
    results at /acc: holds 0.91
    the manuscript prints 0.91: verified
    checked 2026-10-13T21:59:49.971111+00:00: reported 0.92 at /acc, results 28943e35cdd3: mismatch
    since 2026-10-13T21:59:53.664668+00:00: reported 0.91 at /acc, results 28943e35cdd3: verified (after mismatch: reported changed)
```

Each line is one state `repro verify` recorded: `checked` for an earlier one and `since` for the one that still holds, with what changed from the state before it, out of `claim text`, `reported` or `passage`, `address`, `conversion` and `file`, and the outcome that state had. An assertion edited since the last recorded check is shown as `now`, and says no check of it is recorded. An assertion recorded in one state that still holds prints nothing more, and neither does a repository with no record yet. A claim renamed after a check that did not verify leaves one line under the assertion that took its place, `a claim named accuracy was last checked 2026-10-13T21:58:52.102063+00:00 at this address: mismatch, and is no longer declared`. Outside a git repository the account says `no local record is kept here: not in a git repository`, under `record of checks`, where a record that does not verify is also named. The JSON carries every recorded state under `history`, the unrecorded one under `now`, a renamed claim's last state under `formerly`, and each record's state under `records`.

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

`text` is matched as a quotation is, every number inside each place it occurs is set aside, and `reason` is required. `reviewed: {who, when}` is optional and says who set the passage aside and when; [the pull-request bot](#a-bot-on-pull-requests) writes it, with `via: reproducible-science-pr-bot`. An entry whose passage is not in the text is listed with a count of 0. `--format json` prints, per text, every number with the line it is on, its offset in the normalized text, the value read, its standing, and the rule, the claims that bind it or the reason.

## A file copied from another repository

A results file is often copied into a manuscript's repository from the repository of the study that computed it. The pin says which bytes the manuscript reads and nothing of where they came from. An artifact may say, with `origin`:

```yaml
artifacts:
  - id: indices
    path: artifacts/indices.json
    digest: {algorithm: sha256, value: 3db72e39...}
    origin:
      repository: https://github.com/owner/study
      commit: d4d6909cd7a99bec2416c2fe561b1a04d5bf5802
      path: results/indices.json
```

`repository` is a URL or a local path, `commit` is the full 40-character id, and `path` is relative to that repository's root. A branch, a tag, a short id, an absolute path or a path with `..` is refused when the manifest is read, because each can come to name other bytes.

```bash
repro origins --repo https://github.com/owner/study=../study
```

For each artifact that declares an origin, `repro origins` reads the bytes of that path at that commit and compares their sha256 with the pinned digest. Here the copy was edited after it was taken:

```text
  DIFFERS        indices: https://github.com/owner/study d4d6909cd7a9:results/indices.json
                 the origin's bytes do not have the pinned digest (read from /home/you/work/study)
                 pinned    3db72e396caeafded64ab436f341936577b90ad3767a6edb59dea9045d20c5e0
                 at origin 2ec7fab1cf2458f30591cc157b23cc50380644ee085a46b9b23237650456e4c4

  1 origins: 0 same, 1 differs, 0 absent, 0 unknown commit, 0 not checked
```

| state | holds when |
|---|---|
| `same` | the bytes at the origin have the pinned digest |
| `differs` | they have another; both digests are printed |
| `absent` | the clone holds the commit, and the commit holds no file at the path |
| `unknown commit` | the clone holds no such commit |
| `not checked` | no bytes were obtained: no clone was given and `--fetch` was not, the repository is not on GitHub, the fetch failed, or the artifact has no pin |

A clone is named with `--repo REPOSITORY=PATH`, repeatable, or by an origin whose repository is a local path. It is read with `git cat-file`, so the committed bytes are compared and never the clone's working tree. With `--fetch`, a GitHub repository no clone is given for is read from `raw.githubusercontent.com` at the commit, with no credentials. A failed fetch is `not checked`, because GitHub answers a missing path, a missing commit and a private repository alike; a clone tells them apart. Without `--fetch` nothing touches the network. `--format json` prints the same report as one document, with the states written `unknown_commit` and `not_checked`.

It exits 0 where every origin is `same`, 1 where one differs or is absent, and 2 where one could not be checked and none failed, or where no artifact declares an origin. `same` is a statement about the pin and the origin: where the file on disk is not the pinned bytes, the command says so beside the state, and `repro verify` reports the broken pin. `repro verify` never reads an origin and stays offline. `repro export record` carries the declared origin on each file it read, and `repro export ro-crate` on the file's `File` entity as `isBasedOn`.

## For another program

```bash
repro export record              # JSON Lines on standard output
repro export record -o records.jsonl
```

`repro export record` checks every assertion as `repro verify` does and writes one JSON object per line, one per assertion. Each states what was observed: the checker and its version, the file read with its pinned digest and its digest on disk, the address, the value stored there, the value the manuscript prints, the comparison rule and the outcome. It executes nothing, writes only the output it is asked for, and exits 0 whatever the outcomes, since `repro verify` is the check that fails.

Experimental. Every record names its version, `reproducible.science/claim-check/0.1-experimental`, and a field may change before `1.0`. Releases in the 0.6 series also read a record under `repro.check/0.1-experimental`, the name 0.5.6 wrote; the next minor release reads only the new one. The JSON Schema is [`docs/schemas/claim-check-0.1-experimental.schema.json`](https://reproducible.science/schemas/claim-check-0.1-experimental.schema.json), and the [check record](https://reproducible.science/concepts/check-record/) page summarizes the format.

```json
{"record": "reproducible.science/claim-check/0.1-experimental", "checker": {"name": "repro", "version": "0.6.0", "url": "https://github.com/elliottower/reproducible-science"}, "checked_at": "2026-10-13T21:41:43Z", "manifest": {"path": "repro.yaml", "digest": "2ea85eb5..."}, "claim": {"id": "responders", "text": "Thirty-five participants responded.", "digest": "1ccb77d0...", "line": 12}, "assertion": {"kind": "metric", "name": "responders", "position": 0, "index": 0, "line": 15}, "check_type": "value-comparison", "reads": [{"artifact": "totals", "path": "totals.json", "media_type": "application/json", "validity": "authoritative", "pinned": "ce260cfb...", "on_disk": "ce260cfb...", "side": "", "address": {"kind": "tree", "contract": 1, "pointer": "/responders"}, "stored": "36"}], "printed": "35", "comparison": {"mode": "printed_precision", "tolerance": "0"}, "outcome": "mismatch", "native_outcome": "mismatch", "native_reason": "value_mismatch", "detail": "responders: manuscript prints 35, totals.json holds 36 at /responders", "stages": {"execution": "completed", "extraction": "extracted", "comparison": "mismatch"}, "reader": {"backend": "metric", "backend_version": "2", "tool": "reproducible-science", "tool_version": "0.6.0", "extraction_digest": "76a50887..."}, "warnings": []}
```

The digests above are shortened for the page; a record carries all 64 characters.

`check_type` says which proposition was checked, because two tools can report the same word for different checks: `value-comparison` for a `metric`, `table` or `value` assertion, `aggregate-comparison` for an `aggregate`, `passage-presence` for a `quote`, `correspondence` for two files compared with each other.

`outcome` is one of five words, and `native_outcome` carries the word `repro verify` prints beside it:

| `outcome` | holds when | `repro verify` prints |
|---|---|---|
| `match` | the file was read, the address resolved, a comparison ran, and the two agreed | `verified` |
| `mismatch` | the same, and the two differed | `mismatch` |
| `not-found` | the file was readable and the address did not resolve to one value | `not_found` |
| `not-checked` | no comparison occurred: a file, a reader or a format was missing | `unchecked` |
| `error` | the tool failed | `error` |

Whether the file is the pinned one is `validity` on each file read, apart from the outcome, as in the report. No field is a `true` or a `false`. Where a command under `regenerations` writes a file the assertion reads, the record adds an `execution` block: the state `repro stale` gives, and each command upstream with its inputs and its latest recorded re-run.

`repro.record.validate` reads a record back and refuses one no check could have produced, such as a `mismatch` with no stored value. A reader that meets a word, a check type or an address kind it does not know keeps it and never counts it as a `match`. A record is derived when the command runs, from the manifest and the files, and nothing is stored. An assertion is identified by its claim's id, its kind, its name and its `position` among the claim's assertions of that kind and name. The fields are defined in section 7.10 of [`docs/SPEC.md`](https://github.com/elliottower/reproducible-science/blob/main/docs/SPEC.md), with a JSON Schema beside it.

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
    rev: v0.6.1
    hooks:
      - id: repro-verify
```

`repro-verify` reads the `repro.yaml` in the repository being committed to and fails when a
declared number no longer matches the artifact behind it. Use `repro-verify-strict` to fail on
a check that could not run as well as one that disagreed.

Verifying writes nothing to the working tree. `test_read_only.py` asserts that a verification creates no files,
modifies none, and still writes nothing when it fails, which is what makes it safe to run
inside a commit: a verifier that could edit an artifact is one that could be made to edit an
artifact into agreeing with the claim.

This repository runs the hook on itself, against the `repro.yaml` at its root.

## In CI

```bash
cd my_project
repro ci init
```

```text
wrote /home/you/work/my_project/.github/workflows/claims.yml
  name: claims
  runs: uvx --from reproducible-science==0.5.6 repro ci claims
wrote /home/you/work/my_project/.github/workflows/reruns.yml
  name: reproduced
  runs: uvx --from reproducible-science==0.5.6 repro ci reruns
skipped prereg: no PREREG.md and no .prereg/ here
skipped results: no .results/ ledger here
skipped citations: no claims directory holding a claims file here
each runs on a push to main and on every pull request

add to your README, one line per check. GitHub's own badge, which also
works in a private repository:

[![claims](https://github.com/you/my_project/actions/workflows/claims.yml/badge.svg)](https://github.com/you/my_project/actions/workflows/claims.yml)
[![reproduced](https://github.com/you/my_project/actions/workflows/reruns.yml/badge.svg)](https://github.com/you/my_project/actions/workflows/reruns.yml)

or, for a public repository, the same status drawn by shields.io with the
check's icon:

[![claims](https://img.shields.io/github/actions/workflow/status/you/my_project/claims.yml?label=claims&labelColor=24292f&logo=data%3Aimage%2Fsvg%2Bxml%3Bbase64%2CPHN2Zy...)](https://github.com/you/my_project/actions/workflows/claims.yml)
[![reproduced](https://img.shields.io/github/actions/workflow/status/you/my_project/reruns.yml?label=reproduced&labelColor=24292f&logo=data%3Aimage%2Fsvg%2Bxml%3Bbase64%2CPHN2Zy...)](https://github.com/you/my_project/actions/workflows/reruns.yml)

next: commit and push. Each badge prints its workflow's name beside `passing` or
`failing`, for the latest run on the default branch.
```

`repro ci init` writes one workflow for each check the repository keeps a record for, says which it skipped and why, and prints two badge lines for each one written, in the order prereg, results, claims, citations, reruns. Which records a repository keeps is decided as `repro check` decides it.

| workflow | badge reads | written when the repository has | the workflow runs |
|---|---|---|---|
| `prereg.yml` | `prereg` | a `PREREG.md` at the top or up to three levels below, or `.prereg/` | `repro ci prereg` |
| `results.yml` | `results` | `.results/` | `repro ci results` |
| `claims.yml` | `claims` | `repro.yaml` | `repro ci claims` |
| `citations.yml` | `citations` | a `claims` directory holding a claims file | `repro ci citations` |
| `reruns.yml` | `reproduced` | a `repro.yaml` that declares a command, and at least one re-run in `.repro/reproductions.jsonl` | `repro ci reruns` |

The owner and repository in a badge line are read from `git remote get-url origin`; where that names no GitHub repository the lines are printed with `OWNER/REPO` in their place. The command exits 2 and writes nothing outside a git repository, and in a repository that keeps none of these records.

A workflow it writes, in full:

```yaml
# Written by `repro ci init`. The workflow runs one command and is named for the check that
# command makes: https://reproducible.science/tools/repro/#in-ci
name: claims

on:
  push:
    branches: [main]
  pull_request:

permissions:
  contents: read

jobs:
  claims:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1  # v7.0.1
        with:
          persist-credentials: false
      - uses: astral-sh/setup-uv@c18668ad3cf93ea998bef934396af7bb5c839dc7  # v10.2.0
      - run: uvx --from reproducible-science==0.5.6 repro ci claims
```

The others differ in the name, the job and the last line. Every workflow installs one distribution, `reproducible-science`, pinned to the version that wrote the workflow: it provides `repro ci` and depends on `prereg`, `results-cli` and `citations`, so no second install is needed. Each action is pinned by commit, and the job's token can only read the repository. The branch is the one `origin/HEAD` names, or `main`. A manifest below the top of the repository is named in the command, as `repro ci claims paper/repro.yaml`.

`citations.yml` has one more step before the check, `sudo apt-get update && sudo apt-get install --yes poppler-utils`, because `citations` reads a PDF with `pdftotext` first and GitHub's Ubuntu runner image does not list poppler-utils among its installed packages.

### prereg in CI

`repro ci prereg` runs `prereg check`: every plan at or below the top of the project, with its amendments and its log, against the bytes that were frozen.

```markdown
## prereg

prereg: each frozen plan, its amendments and its log against the bytes that were frozen. What this means: https://reproducible.science/tools/repro/#prereg-in-ci

`prereg check`: **passed** (exit 0)

| checked | found |
|---|---|
| plans | 1 of 1 frozen plan unchanged since the freeze |
| amendments | 0 frozen amendments, 0 drafts |
| log | 1 log entry |

What this checks: each frozen plan, its amendments and its log are the bytes that were frozen. It does not show that the study followed the plan.
```

A plan that was never frozen is counted apart from the frozen ones and called a draft, and the run does not pass: there is nothing to compare a draft with. The log row counts entries, because `prereg` keeps notes and deviations in one log.

### results in CI

`repro ci results` runs `results verify --files`: the ledger's chain, and each file the ledger records against the hash recorded for it.

```markdown
## results

results: the ledger's chain, and each recorded file against the hash recorded for it. What this means: https://reproducible.science/tools/repro/#results-in-ci

`results verify --files`: **FAILED** (exit 1)

| checked | found |
|---|---|
| chain | intact: 3 events |
| recorded files | 1 of 2 recorded files match the hash recorded, 1 changed |

- `results.json`: changed

What this checks: the ledger's chain is intact and each recorded file is the bytes that were recorded. It does not show that the results are right.
```

A recorded file the repository does not commit is `missing` in a clone, and the run fails on it. A file `reverted` to an earlier of its recorded hashes fails too. The states `results verify --files` passes besides `ok` are counted on rows of their own and not listed: `resealed`, a path recorded under more than one hash that holds the latest; `appended`, a plan frozen in place whose log only grew; `ignored`, one of the ledger's own files, which is not compared; and `retired`, a path `results retire` recorded as no longer part of the project. A retired path that `reappeared` with bytes no record names fails.

### claims in CI

`repro ci claims` runs what `repro verify` runs: each value and passage the manifest declares against the file it is declared to come from, and each file against its pin. It executes nothing, writes nothing to the project, and keeps no record of checks: `repro verify` is the command that appends to one. `--policy` grades as it does for `repro verify`.

```markdown
## claims: my_project

claims: the manuscript's printed values and quoted passages against the files they are declared to come from. What this means: https://reproducible.science/tools/repro/#claims-in-ci

`repro ci claims` under policy `publication`: **FAILED** (1 errors, 0 warnings)

| checked | found |
|---|---|
| assertions | 75 of 76 assertions verified, 1 mismatch |
| numbers in the manuscript | 458 numbers in 1 text: 38 bound, 80 set aside by rule, 0 set aside with a reason, 340 unbound |
| pinned files | 12 of 12 declared files match their pins |
| re-runs | not re-run in this job; the last recorded re-run, started 2026-10-13T19:44:16+00:00: 7 of 7 commands reproduced |
| freshness | 57 current of 57 assertions that read a file with a recorded producer; 19 read files no command is recorded for |

### Assertions not verified

- `responders` metric responders: the manuscript prints `36`; `totals.json` at `/responders` holds `35`: mismatch

What this checks: each declared value or passage is in the file the manifest names, at the address it declares, and each file matches its pin. It does not show that the analysis is right.
```

The assertions are the ones the manifest declares, and the row under them is what `repro numbers` counts in the manuscript's text, so `75 of 76 assertions verified` is not read as covering every number printed. Warnings are counted beside the outcomes, as `warnings: 2 short`, and change none of them. An assertion that reads many values, as an `aggregate` does, is listed with the first three and the statistic of all.

The numbers, re-runs and freshness rows are reported and grade nothing here. The verdict of `repro ci claims` is the verification's alone: a file that is stale or never rerun does not fail it, under any policy. `repro ci reruns` is the check that fails on that.

### citations in CI

`repro ci citations` runs `citations verify --claims <dir>` over the project's claims directory: each quoted passage against the source its claims file pins.

```markdown
## citations

citations: each quoted passage against the source its claims file pins. What this means: https://reproducible.science/tools/repro/#citations-in-ci

`citations verify --claims claims`: **1/2 verified** (exit 0)

1 of 2 quotations were not checked: 1 of 2 sources are not on this machine. An unchecked quotation is not a found one.

| checked | found |
|---|---|
| quotations | 1 found, 0 not found, 1 unchecked of 2 quotations |
| sources | 1 of 2 sources on this machine, 1 absent |

What this checks: each quoted passage is in the source its claims file pins. It does not show that the source supports the sentence that quotes it.
```

A cited paper is usually not the author's to redistribute, so a clone holds every pin and few sources, and each quotation against an absent source is `unchecked`. A run in which some quotations were found, none was not found and the rest were unchecked passes, as `citations verify` exits 0 for it. Its summary gives the verdict as the count, `1/2 verified`, never as `passed`, and opens on how many were not checked; the `citations` badge of `repro badges` draws the same run amber. `repro audit` calls the same run `could not check`. A run that read no source does not pass: `citations verify` exits 1 for it and `repro ci citations` exits 2. There is no threshold option. A minimum share of quotations checked would be a number each project picks, and the count on the first line says what a threshold would hide.

`repro ci init --fetch-sources` writes the workflow with `repro ci citations --fetch-sources`, which runs `citations fetch --claims <dir>` before the check. `citations fetch` asks where an open copy of each absent source is, downloads it, and installs it only where its sha256 is the one the claims file pins. A source that could not be fetched does not fail the job. Its quotations stay `unchecked`, and a `fetch` row counts the sources fetched, already present, and each other outcome under the word `citations fetch` gives it. This is the one place `repro ci` reaches the network.

A checkout holds only what git holds. Where none of the sources the claims files pin is in git, in the index or the last commit, `repro ci init` without `--fetch-sources` says so: the workflow it writes can only report `could not check`, and `--fetch-sources` has it fetch them first. The workflow is written either way, because whether a source may be fetched, and from where, is the author's decision.

### reruns in CI

Most projects cannot run their commands again in a CI job: the data is not public, or the run takes a week on a GPU. What a job can do is read the record. `repro ci reruns` executes nothing. It reads the commands the manifest declares and `.repro/reproductions.jsonl`, as `repro stale` does, and passes where every declared command has a recorded re-run that reproduced, made over the command and the inputs as they are now, whose output is the file now in the repository. It fails where one is `stale`, `never rerun` or `undetermined`, whatever `--policy` says, and names each with its cause.

```markdown
## reruns: my_project

reruns: each declared command against the record of its re-runs. What this means: https://reproducible.science/tools/repro/#reruns-in-ci

`repro ci reruns`: **FAILED**

| checked | found |
|---|---|
| commands | 6 of 7 declared commands have a recorded re-run over the current files that reproduced, 1 stale |
| record | `.repro/reproductions.jsonl` holds 3 re-runs |
| where | of the 7 re-runs compared: 2 recorded in GitHub Actions [run 123456](https://github.com/you/my_project/actions/runs/123456) of you/my_project, as the environment said; 5 recorded with no witness, which is how a re-run on someone's own machine is recorded |

### Commands with no current re-run on record

- `totals`, written by `sum`: stale: input changed

What this checks: for each declared command, the record holds a re-run that reproduced, made over the command and the input files as they are now, whose output is the file now here. The re-runs were recorded before this job, which read the record and ran no command; where each was recorded is what the record holds of it, in the table. `reproduced` means a command was run again and every number the manuscript prints from its output still holds; whether the output had the same bytes is recorded beside it. Commands the manifest does not declare were not run, and this does not show that a command would reproduce if run now.
```

The workflow is named `reproduced`, which is what its badge reads, and not "reproducible". It reports that the commands the manifest declares were run again, by whoever recorded the re-runs, and reproduced. It does not report that anyone else has reproduced the study. `reproduced` is the word `repro reproduce` gives a re-run after which every number the manuscript prints from the command's output still holds; whether the bytes matched is recorded beside it and is not what the word means.

`repro ci init` writes `reruns.yml` only where the manifest declares a command and the record holds a re-run. With commands and no re-run on record it writes no such workflow and prints no badge for it, and says that `.repro/reproductions.jsonl` holds no re-run, and to run `repro reproduce` and commit that file. `--reruns` requires the workflow and exits 2 where it cannot be written. Where it writes the workflow and a declared command has no current re-run on record, it warns that `reruns.yml` fails until each is run again, and names each command with its state.

The record shows three levels, and the summary says which each re-run is at. A re-run recorded with no witness is how one made on someone's own machine is recorded, and the summary says only that it has none. A re-run recorded under GitHub Actions carries the run's repository and id, as the job's environment gave them and unchecked, and the summary links the run's page. A re-run made in this job, with `--run`, is recorded the same way and links this run. The `re-runs` row of `repro ci claims` names the run of the last recorded re-run where the record holds one.

For a project whose commands can run in a job, `repro ci reruns --run` runs what `repro reproduce` runs, on the machine the job runs on, appends the re-run to `.repro/reproductions.jsonl` as that command does, and grades it under `--policy`. `repro ci init --run-reruns` writes `reruns.yml` with that command and a commented step where the project installs what its commands need; it needs no re-run on record. The step suggests `uv sync` where the project has a `uv.lock`, `uv pip install --system -r requirements.txt` where it has a `requirements.txt`, and otherwise names the lockfile it found, or says there is none. `--skip ID` leaves a record out, and it is counted as `not re-run`. The summary then counts the commands that reproduced, how many of the ones that ran wrote the pinned bytes, and the system, Python and lockfile of the machine, and says the commands were run again in this job.

### Exit codes

| command | 0 | 1 | 2 |
|---|---|---|---|
| `repro ci prereg` | every plan, amendment and log is as frozen | a frozen file or a log changed | a plan was never frozen, a commit-pinned registration could not be compared, or there is no plan |
| `repro ci results` | the chain verifies and every recorded file matches | the chain does not verify, or a recorded file changed or is missing | no ledger |
| `repro ci claims` | the policy passes the verification | the policy fails the verification | no manifest, or one that cannot be read |
| `repro ci citations` | at least one quotation was found and none was not found | a quotation was not found, or a source is not the pinned bytes | no source could be read, so nothing was checked; or no claims directory |
| `repro ci reruns` | every declared command has a current re-run on record | a command is stale, never rerun or undetermined | no manifest, one that cannot be read, or no command declared |
| `repro ci reruns --run` | the policy passes every re-run | the policy fails a re-run: by default one that `changed` or `failed` | as above |
| `repro ci init` | the workflows were written | | not in a git repository, no record to check, a workflow already there, `--reruns` with no command declared or no re-run on record, or `--readme` with no README or no GitHub remote |

For `prereg`, `results` and `citations` the outcome is the word `repro audit` gives the same command: `passed`, `failed`, `could not check` or `nothing to read`, exiting 0, 1, 2 and 2, with the one difference for `citations` said above.

### The summary on the run page

Where `GITHUB_STEP_SUMMARY` is set, as it is in every GitHub Actions step, each command appends a Markdown summary to that file, and GitHub shows it on the page of the run. `--summary PATH` names the file instead. The file is appended to and never replaced.

A badge leads to the page of a run, and nothing on that page says what the workflow is. Each summary therefore opens, under its heading, on what the check compares and a link to its section of this page. Every count carries what it is a count of, and each summary ends on what its check does not show. An assertion or a quotation that is `unchecked` or `not found` is counted under that word and never as verified or found. The counts of `prereg`, `results` and `citations` are read from the JSON each tool writes with `--json`, and no line of their printed text is parsed for a number. The lists appear only where there is something to list, each stops at 20 lines and says how many more there are, because a manifest can declare thousands of assertions and GitHub refuses a step summary over 1 MiB.

### The two badge lines

`repro ci init` prints two lines for each workflow, and either goes in a README.

```markdown
[![claims](https://github.com/you/my_project/actions/workflows/claims.yml/badge.svg)](https://github.com/you/my_project/actions/workflows/claims.yml)
```

The first is GitHub's own badge. It works in a private repository, for whoever has access to it, and reads the workflow's name beside `passing` or `failing`.

```markdown
[![claims](https://img.shields.io/github/actions/workflow/status/you/my_project/claims.yml?label=claims&labelColor=24292f&logo=data%3Aimage%2Fsvg%2Bxml%3Bbase64%2CPHN2Zy...)](https://github.com/you/my_project/actions/workflows/claims.yml)
```

The second is drawn by [shields.io](https://shields.io/badges/git-hub-actions-workflow-status), which reads GitHub's badge for the workflow and redraws it with the check's icon on a dark label. It shows the same status and links to the same runs. It works only for a public repository: shields.io asks GitHub as anyone would, and for a private one it reads `repo or workflow not found`. The icon is in the address, as a base64 data URI of an SVG of a few hundred bytes.

`--readme` puts the first form of each badge on one line under the first heading of `README.md` and prints what it added, and `--readme --branded` puts the second. It adds nothing for a workflow whose badge the README already shows in either form.

A workflow is named for the one thing it runs and not for the project, because the badge prints the workflow's name beside `passing`, and no one of these jobs can establish that a study is reproducible. GitHub's badge is per workflow file. Its documentation says "A status badge shows whether a workflow is currently failing or passing", and the badge's address names a workflow file and no job, so each badge is a workflow of its own.

`--name WORKFLOW=TEXT` gives a workflow another name, as `--name "claims=claims match files"` does. `--prefix repro-` writes `repro-claims.yml`, for a repository that already has a `claims.yml`. A workflow this command wrote is replaced only with `--force`. A file of that name that it did not write is never replaced, with or without `--force`.

A run in CI adds three things to a run on the author's machine: the check ran on a machine the author does not control, at a commit the run names, and its log is public. It does not remove the author from the record: the author writes the workflow, the manifest and the list of what each command reads.

This repository keeps a `repro.yaml` that declares no command, and none of the other records, so it runs `repro ci claims` on itself, in `.github/workflows/claims.yml`.

## Badges with counts

```bash
cd my_project
repro badges
```

```text
[![prereg: 1 plan frozen](https://img.shields.io/static/v1?label=prereg&message=1%20plan%20frozen&color=2da44e&labelColor=24292f&logo=data%3Aimage%2Fsvg%2Bxml%3Bbase64%2CPHN2Zy...)](https://reproducible.science/tools/repro/#prereg-in-ci)
[![results: 19/19 runs sealed](https://img.shields.io/static/v1?label=results&message=19%2F19%20runs%20sealed&color=2da44e&labelColor=24292f&logo=...)](https://reproducible.science/tools/repro/#results-in-ci)
[![claims: 74/76 verified](https://img.shields.io/static/v1?label=claims&message=74%2F76%20verified&color=cf222e&labelColor=24292f&logo=...)](https://reproducible.science/tools/repro/#claims-in-ci)
[![citations: 199 pinned](https://img.shields.io/static/v1?label=citations&message=199%20pinned&color=0969da&labelColor=24292f&logo=...)](https://reproducible.science/tools/repro/#citations-in-ci)
[![reproduced: 6/7](https://img.shields.io/static/v1?label=reproduced&message=6%2F7&color=bf8700&labelColor=24292f&logo=...)](https://reproducible.science/tools/repro/#reruns-in-ci)
```

`repro badges` runs each check the project keeps a record for, as the matching `repro ci` command runs it, and prints one badge per check whose message is what that check counted. A badge is a static shields.io image: the label, the count and the colour are in its address, so it draws for a private repository, and the command reaches no network. Each badge links to the section of this page that says what its check compares.

| badge | counts | green | amber | red |
|---|---|---|---|---|
| `prereg` | plans frozen | every plan frozen and unchanged | a plan or an amendment never frozen | a frozen plan changed |
| `results` | runs with a seal before them, of the ledger's runs; runs named `smoke_`, `prefreeze_`, `test_` or `dryrun_` are left out | `results verify --files` passes and every run is sealed | a run with no seal before it, or `results verify --files` fails over recorded files: changed, missing, reverted, reappeared, not a tree or not a file | the ledger's chain does not verify, or a timestamp contradicts it |
| `claims` | assertions verified, of every assertion | every assertion verified | none mismatched, and some were not found, not checked or could not be read | an assertion mismatched |
| `citations` | quotations found, of every quotation pinned | every quotation found | none not found, and some unchecked | a quotation not found, or a source not the pinned bytes |
| `reproduced` | declared commands with a current re-run on record, as `repro stale` reports them | every command current | a command stale, never re-run or undetermined | |

The `results` badge reads `19/19 runs sealed` whatever its colour; which files `results verify --files` found not as recorded is in that command's output and in the `repro ci results` summary the badge links to. Where no source of any pinned quotation is on the machine, nothing was checked, and the `citations` badge reads `199 pinned` in blue. A check the project keeps no record for has no badge, and standard error says which were left out and why, in the words `repro ci init` uses. `--all` gives each of those a gray `none declared` badge instead.

`repro badges --readme` writes the badges on one line between two marker lines in `README.md`, under the first heading, where `repro ci init --readme` puts its line:

```markdown
<!-- repro badges: start -->
[![prereg: 1 plan frozen](...)](...) [![results: 19/19 runs sealed](...)](...) ...
<!-- repro badges: end -->
```

A second run replaces what is between the markers and changes no other byte of the file. `repro badges --check` writes nothing, exits 0 where the block holds what the project gives now, and exits 1 where it does not, or where `README.md` has no block, naming each badge that is out of date and the command that refreshes it. It exits 2 where there is no `README.md` or a block is not closed. Run in a pre-commit hook, it stops a commit whose badges no longer say what the files say.

A badge from `repro badges` is a count written from a run on the author's machine, with the files that machine holds; a badge from `repro ci init` is a status GitHub computed on its runner from the files in the repository.

## Badges that update themselves

```bash
repro badges init
```

`repro badges --readme` writes counts into the README, and they hold until the next time someone runs it. `repro badges init` writes one workflow, `.github/workflows/repro.yml`, that recomputes them on GitHub. On every push to the default branch it runs `repro ci endpoints`, which runs each check the repository keeps a record for, as `repro badges` does, and writes one [shields.io endpoint file](https://shields.io/badges/endpoint-badge) per check:

```json
{
  "color": "2da44e",
  "label": "claims",
  "labelColor": "24292f",
  "logoSvg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 24 24\">...</svg>",
  "message": "76/76 verified",
  "schemaVersion": 1
}
```

The label, message, colours and icon are the ones `repro badges` draws, so the two kinds of badge look the same. The workflow force-pushes the five files as the only commit of a branch named `badges`, which it makes on its first run. It has `contents: write` for that push and pushes nothing else: the push names `refs/heads/badges`, and the job stops where the default branch is itself called `badges`, which `init` refuses too. The actions are pinned by commit, as in the workflows `repro ci init` writes.

`init` puts the badge block under the first heading of `README.md`, between the markers `repro badges --readme` uses, with one badge per check the repository keeps a record for, each reading its file from the `badges` branch and linking to the workflow's runs:

```markdown
<!-- repro badges: start -->
[![claims](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/OWNER/REPO/badges/claims.json)](https://github.com/OWNER/REPO/actions/workflows/repro.yml) ...
<!-- repro badges: end -->
```

`OWNER/REPO` is read from `git remote get-url origin`, and `init` writes nothing where that names no GitHub repository. A block already in the README is left as it is, and a workflow already at `repro.yml` is never replaced; `--force` replaces both where this command wrote them, and a `repro.yml` it did not write is never replaced. It then prints what is left to do: commit, push, and allow the workflow to write if the repository's settings forbid it. Until the first run has made the branch, the badges draw as `resource not found`. shields.io reads the files from `raw.githubusercontent.com`, which serves public repositories only, so in a private repository the badges do not draw; `repro badges --readme` writes static badges that do. A badge can lag a push by the few minutes `raw.githubusercontent.com` and shields.io cache a file.

### citations, from the record of a local check

A clone does not hold the sources a claims directory pins, so `citations verify` in the job would find every quotation `unchecked`. The job reads instead what a check on the author's machine found. `repro badges --record` runs `citations verify` as `repro ci citations` runs it and writes `.repro/citations-verified.json`: the counts, the outcome, the version of `citations` and the time, and for every claims file its sha256 and the digest of the source it pins. `init` writes it too. Commit it. The record is written by `repro`, and `citations verify` writes nothing it was not asked to.

The citations endpoint file is read from that record and from no run in the job:

| record | badge |
|---|---|
| every claims file is the one the record covers | what the local run gave, said `locally`: `203/203 verified locally`, in the colour `repro badges` gives it |
| a claims file was added, removed or changed since | `re-verify locally`, amber |
| no record | `not verified locally`, gray, and the job's log names `repro badges --record` |

A claims file pins its source by digest, so a source swapped under a pin changes the claims file and the record goes stale. `repro badges --check`, run against the block `init` wrote, compares that record with the claims files and exits 1 where it no longer covers them, naming each file; in a pre-commit hook it stops a commit whose citations badge would read `re-verify locally`. `repro badges --readme` refuses to replace the block `init` wrote.

## A bot on pull requests

```bash
repro ci init --pr-bot
```

The pull-request bot comments on a pull request once for each assertion that fails or went stale, and records the answer someone with write access gives. It is its own distribution, `reproducible-science-pr-bot`, and runs from GitHub Actions in your repository with its own token. Nothing is hosted, and no model reads or writes anything.

`repro ci init --pr-bot` writes two short caller workflows. Each calls the reusable workflow `elliottower/reproducible-science/.github/workflows/pr-bot.yml`, which holds the jobs; the callers only choose when it runs and what its token may do.

| caller | runs on | job | token | does |
|---|---|---|---|---|
| `repro-pr-bot.yml` | `pull_request`, and `workflow_dispatch` from `reply` | check | `contents: read` | checks out the pull request's head commit, runs `reproducible-science-pr-bot check`, and uploads what it found as the artifact `repro-pr-bot-findings` |
| `repro-pr-bot-respond.yml` | `workflow_run`, after the check | post | `actions: read`, `issues: write`, `pull-requests: write` | downloads that artifact and runs `reproducible-science-pr-bot post`; checks out nothing |
| `repro-pr-bot-respond.yml` | `issue_comment`, `pull_request_review_comment` | reply | `actions: write`, `contents: write`, `issues: write`, `pull-requests: write` | runs `reproducible-science-pr-bot reply` on a reply to one of the bot's comments; checks out nothing |

The callers are two because the comments must be posted by a run holding a token that writes, which `pull_request` never gives a pull request from a fork, and that run is started by `workflow_run` after the check. GitHub's documentation does not say that a workflow can be started by its own completion, so a second file starts it. A called workflow can lower the permissions its caller grants and never raise them ([Reusing workflow configurations](https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations)), so each job of the reusable workflow asks for the token in the table, whatever the caller grants: the check job holds `contents: read` even in a caller that grants more.

`reproducible-science-pr-bot check` decides what fails as `repro export` does: an assertion whose record says `mismatch`, `not-found` or `error`, or whose producing command is `stale`, as `repro ci claims` and `repro ci reruns` report it. An inferred assertion nobody reviewed is `not-checked` and gets no comment. It executes nothing and writes at most fifty findings. `post` comments on each:

```text
Table 2: `0.931` no longer matches `results/metrics.json` (now `0.928`)

Reply in this thread with a number:
1. Yes, the paper should say `0.928`
2. No, the result file is wrong
3. Ignore this one
4. Not a claim
```

The comment is on the manuscript's line where the claim quotes its sentence from a text file that holds it once, as `repro export sarif` places a result, and that line is in the diff. Otherwise it is in the pull request's conversation, where a reply says which comment it answers by quoting it or by starting with the short name the comment prints, such as `r-3f2a9c1b`. Each comment carries a hidden marker naming the claim, the assertion, the assertion's fingerprint, which is the one `repro export sarif` gives GitHub, and a digest of what was found. A second run never posts a comment again: it edits the comment already open on the same assertion where what it says has changed, strikes it through as fixed where the assertion passes and resolves its review thread, and opens both again where it fails again. An answer recorded in a comment is kept when the comment is edited. Text echoed from the pull request is shown as code, with control characters and HTML comment syntax taken out, and a body that would pass GitHub's limit of 65,536 characters drops the echoed passage first.

A reply is read where it is in one of the bot's threads and its text, after any quoted lines and an optional `@repro`, starts with a number from 1 to 4. Words after the number are the reason. A reply naming two numbers or a time, `1-2`, `1, 2`, `1 or 2`, `1:30`, gives no answer. Fullwidth digits, invisible characters and a number in emphasis or code, `**1**`, are read as the plain number. A reply from someone with write access that starts with another number, or with `@repro`, is answered with one line, `reply 1–4`; any other discussion in the thread is left alone, and a reply anywhere else is not read. Of the replies in a thread, the latest from someone the API reports as having `write`, `maintain` or `admin` access holds, and an answer is never replaced by an earlier one. An edited reply is read again when it is edited, as what it now says, and the answer it gives replaces the one it gave; a deleted reply leaves what it recorded, `set_aside` entry included, in place.

| answer | recorded |
|---|---|
| 1, yes | in the comment: who accepts the file's value. The manuscript is never edited, and the claim fails until the paper prints the value |
| 2, no | in the comment: who says the result file is wrong. The claim keeps failing |
| 3, ignore | a `set_aside` entry for the claim's passage, committed to the pull request's branch |
| 4, not a claim | the same, with `not a claim` in its reason |

The bot confirms in the thread, `recorded: ignored by @login`. Where the passage is already set aside, by hand or otherwise, it says so, commits nothing and closes the comment. The entry it commits names the passage the claim quotes, and says who answered and when under `reviewed`:

```yaml
set_aside:
- artifact: paper
  text: an accuracy of 0.931
  reason: 'pull request #7, ignored: a figure from the pilot'
  reviewed:
    who: alice
    when: '2026-10-14T12:00:00Z'
    via: reproducible-science-pr-bot
```

The entry is added after the last one, indented as they are, and no other byte of `repro.yaml` changes; the file is never loaded and dumped again. Answers 1 and 2 change no file, except that a 1 or 2 after a 3 or 4 removes the entry the bot wrote for it. The bot knows its own entries by `via: reproducible-science-pr-bot` and never removes another. A claim that quotes no passage has no entry to write, and the bot says so. A `set_aside` entry accounts for the numbers in its passage in `repro numbers` and nothing more: `repro verify` still reports the claim, and the comment, closed as set aside, says so.

The split follows GitHub's advice for workflows that handle pull requests from forks ([Secure use reference](https://docs.github.com/en/actions/reference/security/secure-use)): the job that reads the pull request's files holds a read-only token, and the jobs with a token that writes check out nothing and run nothing from the pull request. `post` treats the findings as data and refuses them unless the pull request they name is at the commit the check ran on and from the repository and branch that were checked, and unless they are about the manifest the workflow names. `reply` commits only to that manifest, whatever a comment says, and answers no comment about another file. The check runs `uvx --no-config`, so a `uv.toml` in the pull request cannot choose where the package is installed from. No workflow uses `pull_request_target`, and none places a comment's text in a shell command. On a pull request from a fork the bot comments only in the conversation, says so in each comment, and commits nothing; an answer of 3 or 4 is recorded in the comment and the entry is left for a maintainer to add. A commit made with the workflow's token starts no other workflow, so after committing `reply` starts `repro-pr-bot.yml` again on the branch with `workflow_dispatch`, which that token may do, and with it each workflow `repro ci init` wrote that has a `workflow_dispatch` trigger. A check started that way reports on the branch's new head commit, so a branch protection rule requiring it does not hold the merge. `repro ci init` writes that trigger; a workflow it wrote before it did is named by `repro ci init --pr-bot`, and `repro ci init --force` then `repro ci init --pr-bot --force` adds it.

Runs of `post` on one branch wait for each other, and so do runs of `reply` on one pull request. A run of `post` and a run of `reply` can overlap: they are kept apart because GitHub cancels a run waiting in a concurrency group when another queues behind it, and a shared group would drop findings or answers. Each reads a comment again right before it edits it and changes only its own part: `post` never changes the recorded answer, and `reply` changes whether a comment is open or fixed only by setting it aside or undoing that. Each run of `reply` records every answer on the pull request not yet in its comment, not only the one that started it, and reads the thread and the manifest again right before it commits. When `check` found more than fifty assertions failing, `post` closes no comment, because one left out of the findings may still fail.

GitHub runs `workflow_run` and `issue_comment` workflows only from the default branch, so the bot comments on no pull request until the two callers are merged there. `repro ci init --pr-bot` never replaces a file it did not write; `--force` replaces the two it wrote. Each caller and the reusable workflow grant nothing at their top, `permissions: {}`, and each job names what it needs, with a comment saying why. Every action the reusable workflow uses is pinned by commit, as in the workflows `repro ci init` writes.

## On a pull request, as SARIF

```yaml
      - run: repro export sarif -o repro.sarif
      - uses: github/codeql-action/upload-sarif@24c54180a607b1449ed407dd24f251e4e9147c8d  # v4.38.3
        with: {sarif_file: repro.sarif, category: repro}
```

The job needs `permissions: security-events: write` beside `contents: read`. Run the export from the top of the repository, so that the paths in the log are the paths GitHub knows. Code scanning is enabled for public repositories by default; a private repository needs a GitHub Code Security licence ([About GitHub Advanced Security](https://docs.github.com/en/get-started/learning-about-github/about-github-advanced-security)).

`repro export sarif` writes a SARIF 2.1.0 log from the check records, for display. It is a projection and a lossy one.

| the record says | in the log |
|---|---|
| `mismatch` | a result, `kind: fail`, `level: error` |
| `not-found` | a result, `kind: fail`, `level: warning` |
| `error` | a result, `kind: fail`, `level: error`, and a notification at `level: error`, which marks the run as failed |
| `not-checked` | no result: a notification at `level: warning` on the invocation, counted by reason in the run's properties |
| `match` | no result, unless `--include-matches` asks for one, `kind: pass` |

An assertion that was not checked is neither a finding nor a pass, so it is never a result. A word the exporter does not know is `not-checked`, never a pass.

Leave `--include-matches` off for an upload to GitHub. GitHub does not read `kind`: uploaded from this repository, each `pass` result at `level: none` became an open alert of severity `warning`, annotated on the pull request beside the real findings. The flag is for a SARIF viewer that does read `kind`.

Each result is shown at one place, the first of these that exists: the line of the sentence, where the claim has a `quote` assertion against a text file (`.md`, `.tex`, `.txt`, `.rst`) that holds the passage exactly once; otherwise the assertion's own line in `repro.yaml`. A line is never estimated. The files the assertion reads are related locations. GitHub annotates a pull request only where that line is in its diff, and lists every alert under Security, Code scanning.

An alert follows its assertion across commits by `partialFingerprints`: a digest over the claim's id, the assertion's kind, name and position, and the address or passage it declares. GitHub reads only `primaryLocationLineHash`, so the same digest is supplied there. Moving a sentence or reordering the manifest keeps the alert; changing an address closes one and opens another.

SARIF has no property for most of what a record holds. The whole record is in each result's `properties` under `repro/checkRecord`, and these fields are there and nowhere else in the log: the record version, the manifest digest, the claim's text, digest, `where` and passages, the assertion's kind, name, position and index, `check_type`, each file's `validity`, pinned digest, side, address, stored value and converted value, `printed`, `comparison`, `outcome`, `native_outcome`, `native_reason`, `stages`, `reader`, `warnings`, `execution` and `history`. GitHub ignores the property bag.

GitHub keeps the 5,000 most severe results of a run and rejects a file over 10 MB compressed. The default output holds only what did not match; with `--include-matches` a log over 5,000 results is written whole and a warning says so.

`repro verify --format sarif` is an older log built from the report, graded by `--policy`, and is unchanged.

## As an RO-Crate

```bash
repro export ro-crate -o .        # writes ./ro-crate-metadata.json beside repro.yaml
repro export ro-crate             # the same document on standard output
```

`repro export ro-crate` writes the same check records as an [RO-Crate 1.3](https://w3id.org/ro/crate/1.3) metadata document. Each file a record names is a `File` with the `sha256` of its bytes, each claim a schema.org `Claim`, each checked assertion a `CheckAction`, and each command under `regenerations` with a recorded re-run a `CreateAction` as [Process Run Crate 0.6](https://w3id.org/ro/wfrun/process/0.6) describes one. The crate's root is the directory `repro.yaml` is in, so `-o .` there puts the file where its paths resolve. `-o DIR` writes `DIR/ro-crate-metadata.json`, and a path ending in `.json` is written as that file.

Experimental. RO-Crate has no term for the address inside a file, for a printed value against a stored one or for the outcome of comparing them, so those come from a profile of this tool's own, [`https://reproducible.science/ro-crate/claim-check/0.1/`](https://reproducible.science/ro-crate/claim-check/0.1/), version `0.1-experimental`. It is this tool's export format and nothing more, and its terms may change before `1.0`.

The crate is written from the records alone and loses none of them: `repro.export.rocrate.from_ro_crate` reads one back into the records it came from. Two consequences follow. A file no record names is not in the crate, which is an artifact that no assertion reads and no command upstream of one touches. And a record knows no license, which RO-Crate requires of a crate, so the document says none is stated; add the project's own before publishing one.

## For a venue

```bash
repro venue acm                          # an Artifact Appendix, as Markdown
repro venue acm --format latex -o ae.tex # in the layout of the template, as LaTeX
```

`repro venue acm` drafts an Artifact Appendix in the layout of the [Unified Artifact Appendix template](https://github.com/ctuning/artifact-evaluation/blob/307966059368634d9882a3daa42e4b63ef1946d6/docs/template/ae.tex) that ACM conferences running artifact evaluation ask for. The headings and field labels are the template's, stored in the package with the commit and the day they were copied. A field that a record in the repository bears on carries what that record says, one line per fact, each line naming its record:

| field | read from |
|---|---|
| Run-time environment, Software dependencies | lockfiles and environment files at the top of the project, and the environment of the most recent re-run that is still current |
| Hardware | the machine and GPUs of the most recent current re-run in `.repro/reproductions.jsonl` |
| Execution, time to complete | the durations of the re-runs that are current, added up |
| Output | the claims and pinned artifacts `repro.yaml` declares, and the claims the ledger binds to runs |
| Experiments, Workflow automation framework | each command under `regenerations`, with the file it writes |
| Code licenses | `LICENSE` by its first line, and the license `CITATION.cff` names |
| Archived (provide DOI)? | the DOI `CITATION.cff` names |
| How to access | `git remote get-url origin` with any user name, password or token taken out and "author: confirm this repository is public", that DOI, and the project's own code repository |
| Experiment workflow | the commands, each plan frozen with `prereg` and its commit, and the ledger's count of seals and runs |
| Evaluation and expected results | the claims, whether each declared command's output is current, stale or never re-run as `repro stale` decides it, and each origin as `repro origins` finds it with no network |

Each such field is marked **DRAFT** and names the records it was generated from. Every other field is marked **TODO** and left empty for the authors: the abstract, the algorithm, the data sets, installation and the rest are not in any record, and generated prose in their place would read as the authors' own. A yes or no is filled in only where a record settles it with no judgment involved, marked DRAFT with the record named, and only from the project's own identifiers: `doi`, `identifiers` and `repository-code` at the top of `CITATION.cff`, and `identifier` and `codeRepository` in `codemeta.json`. A DOI or Software Heritage ID (`swh:1:...`) there answers Yes to *Archived (provide DOI)?*; a GitHub or GitLab address alone does not. Any of those, or the code repository, answers Yes to *Publicly available?*, with "author: confirm this repository is public", since whether it is public cannot be seen offline. A declared command answers Yes to *Workflow automation framework used?*. References, cited works, the README and the origins of copied files are never read for these. Every other yes or no is left to the authors. Plans are found as `prereg check` finds them, leaving out any under a folder named `tests`, `test`, `testdata`, `fixtures`, `fixture` or `examples`; `--plan PATH` names one instead, and must exist. A ledger whose chain does not verify is said to, and a claim in it counts as bound only where the run it names is recorded. `--format json` gives every answer with its status and its records. `-o FILE` refuses to replace a file that exists, since the authors may have edited it; `--force` replaces it.

### Evidence against the badging criteria

```bash
repro venue acm-evidence -o evidence.html     # one page, no images
repro venue acm-evidence --format json
```

`repro venue acm-evidence` lists, for each criterion of [ACM Artifact Review and Badging](https://www.acm.org/publications/policies/artifact-review-and-badging-current) version 1.1, the records in the repository that bear on it, under the policy's own words for the criterion. It is labelled, in every format, "Evidence mapped to ACM Artifact Review and Badging v1.1 criteria; not an ACM badge." It never says whether a criterion is met, which is the evaluators' decision, and it uses no badge's name or image as a label or a status.

| criterion | records listed |
|---|---|
| placed on an archival repository, with an identifier | a DOI or Software Heritage ID among the project's own identifiers in `CITATION.cff` or `codemeta.json`; never the origin of a copied file, which is someone else's repository |
| documented, consistent, complete and exercisable | the declared commands, the last re-run of each, the claims in `repro.yaml` and the ledger, the README, `docs/` and `CITATION.cff` |
| documented and structured for reuse | all of those, the license, and the lockfiles at the top of the project |
| main results obtained by others, with or without the authors' artifacts | none: `not determinable by this tool` |

Each criterion's standing is `records listed`, `no record found` or `not determinable by this tool`, shown as `DRAFT: records listed` where records are listed and `TODO: ...` otherwise, and the page and the JSON open with a DRAFT notice. The last two criteria are always the third: the policy asks for the results to be obtained by a person or team other than the authors, which nothing in the authors' repository can show. acm.org refuses scripted requests, so the policy page was saved from a browser on 2026-10-11 and converted to text. Each criterion's words are quoted from that text verbatim, ACM's spelling *publically* included, and stored in the package with the page's address, the retrieval date, the sha256 of the saved text and of the saved page, the line each quotation is on, and the sha256 of each quotation, so a copy saved independently can be checked against them. There is no SARIF output: SARIF reports results of an analysis, and a list of records under a criterion is not a result.

### NeurIPS and ACL checklists

```bash
repro venue neurips --format latex -o checklist-draft.tex
repro venue acl
```

`repro venue neurips` drafts the NeurIPS Paper Checklist from `checklist.tex` in the [NeurIPS 2026 formatting archive](https://media.neurips.cc/Conferences/NeurIPS2026/Formatting_Instructions_For_NeurIPS_2026.zip); `repro venue acl` drafts the [ACL Responsible NLP Research checklist](https://aclrollingreview.org/responsibleNLPresearch/). The question text of each is stored in the package, verbatim, with the address and the day it was read, 2026-10-14.

A NeurIPS question asks what the paper discloses, and no record can say that, so a NeurIPS answer stays `\answerTODO{}`, with one exception: open access (5) is `\answerYes{}` followed by a mark that prints, such as **(DRAFT: from `CITATION.cff`; author: confirm this repository is public)**, where the project's own DOI, Software Heritage ID or code repository is recorded, as for ACM's *Publicly available?*. No ACL answer is chosen: no ACL question asks whether code or data were released, and whether a file a claim reads is a scientific artifact in ACL's sense is the authors' judgment, so question B lists the artifacts `repro.yaml` declares and leaves the answer TODO. Where a record bears on a question, the justification is a draft listing what the record says, marked DRAFT with the record named, for the authors to check against the paper and rewrite:

| question | records |
|---|---|
| NeurIPS 1, claims | the claims in `repro.yaml` and the ledger |
| NeurIPS 4, experimental result reproducibility | the declared commands, their last re-runs, the frozen plans |
| NeurIPS 5, open access to data and code | the DOI, origins, commands, lockfiles and license |
| NeurIPS 8, compute resources; ACL C1 | the duration and environment of the last re-runs |
| NeurIPS 12, licenses for existing assets; ACL B1 | each artifact's `origin` |
| NeurIPS 13, new assets; ACL B5 | the README, `docs/` and `CITATION.cff` (with the license, for NeurIPS) |
| ACL B2 | `LICENSE` and the license `CITATION.cff` names |
| ACL C4 | the lockfiles at the top of the project |

The LaTeX for NeurIPS keeps the shape of `checklist.tex` without the guidelines under each question, which stay as that file has them. ACL's checklist is filled in on the submission form, so its draft is Markdown or JSON.

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

A quotation whose source the repository does not carry is read from the citations library when a file there matches the SHA-256 the record pins. `citations audit` reaches Crossref, DataCite and PubMed, and `--offline` skips it. An entry whose registry lookup failed is counted as could not check, never as agreeing, disagreeing or not found.

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

The rule reports one finding for the manifest — every assertion holding is a pass, some
holding is partial, a pinned artifact having changed is a failure naming it — with one item
per checked assertion under it: its status, the printed and stored values, the comparison
rule, and the manifest line and files it read. adduce never scores an item on its own, so the
finding weighs what it did. Past adduce's envelope of 10,000 items the finding says how many
more there are, and the full report is written to `.adduce/repro-report.json` in every case.
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

## MCP server

`repro mcp` serves the toolkit's checks to any coding agent that speaks MCP. Register it once
per agent, for every project:

```bash
uv tool install "reproducible-science[mcp]"
claude mcp add --transport stdio --scope user reproducible-science -- repro mcp
```

Codex, in `~/.codex/config.toml`:

```toml
[mcp_servers.reproducible-science]
command = "repro"
args = ["mcp"]
```

Gemini CLI takes the same `command` and `args` under `mcpServers` in `~/.gemini/settings.json`,
and Cursor under `mcpServers` in `~/.cursor/mcp.json`, with `"type": "stdio"`.

The server follows the paths the agent passes. Each call works in the project its path is in,
the nearest folder above it holding one of `PROJECT_MARKERS` (`repro.yaml`, `.results/`,
`.prereg/`, `claims/`, `PREREG.md`, or a reader's `repro.draft.yaml`), and every path is kept
inside that project. A symlink belongs to the folder it sits in. A call with no path takes a
`project` argument, or the project of the last call.

| tool | what it does |
|---|---|
| `verify`, `why`, `stale`, `numbers`, `origins` | as the commands; `verify` writes no record of checks |
| `prereg_check`, `results_verify`, `citations_verify` | the three tools' checks |
| `citations_audit` | each `.bib` entry against its registry record, ten a call: agrees, disagrees, not found, or could not check; the one tool that reads the network |
| `next_open_item`, `get_open_item` | one open item: the claim, the printed value, the sentence, each candidate's address, labels and stored value |
| `propose_binding` | one assertion filling an item, `basis: inferred`, then its check |
| `add_artifact` | one file, pinned and `basis: inferred` |
| `mark_reviewed` | what the user approved in the chat, as `reviewed` |
| `pin_quote` | `citations pin`, which writes only a passage that resolves |

Each write is one line of the draft, and no other byte changes. `propose_binding` reports a
match as `matched, inferred: not verified`, and a retry replaces only its own proposal that did
not match. Every attempt is appended to a hash chain in `.repro/attempts.jsonl` beside the
open-items file, which `claims open-items` counts from, flagging an item tried more than five
times. An assertion reading an inferred artifact counts as inferred too. `mark_reviewed` writes
who (git `user.name`), when, how (`approved in chat via` the client) and the digest of what was
accepted; when that changes, the review no longer counts. Nothing the server offers freezes,
registers, seals, runs a declared command, and nothing but `citations_audit` fetches.

MIT licensed.


## Run it in your browser

<div class="nb-embed" id="run-it" data-nb="end-to-end.ipynb">
  <button class="nb-start" type="button">Start the notebook</button>
  <p>Runs here, in this tab. Nothing is installed and nothing is uploaded.</p>
</div>
