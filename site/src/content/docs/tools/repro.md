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
done.
```

`init` spawns `prereg new`, `results init` and `citations init`, whose own output it does not
relay; the lines above are everything it prints itself.

This creates:

```text
my_experiment/
    CLAUDE.md           tells Claude Code about the tools
    repro.yaml          the manifest, with nothing pinned yet and two example claims as comments
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

## On every commit

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/elliottower/reproducible-science
    rev: v0.4.0
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

It installs four skills, four commands and four hooks. The hooks are the part a CLI
cannot do, because each fires at a moment rather than when you remember to run something:

| hook | fires when |
|---|---|
| frozen plan changed | a preregistration no longer matches the digest it was frozen with |
| unverified quotation | a passage enters a manuscript that no claim file pins to a source |
| unbound number | a number enters a manuscript that no recorded claim names |

Every hook reports and never blocks, and stays silent in a project that has not opted in: no
ledger, no claims directory and no frozen plan means nothing to check and nothing said.

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
