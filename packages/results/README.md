# results

[![pypi](https://img.shields.io/pypi/v/results-cli)](https://pypi.org/project/results-cli/)
[![python](https://img.shields.io/pypi/pyversions/results-cli)](https://pypi.org/project/results-cli/)
[![license](https://img.shields.io/pypi/l/results-cli)](https://github.com/elliottower/reproducible-science/blob/main/LICENSE)
[![docs](https://img.shields.io/badge/docs-live-blue)](https://reproducible.science/)

Seal inputs, record outputs, and bind a paper's claims to the runs behind them.

Part of [reproducible-science](https://github.com/elliottower/reproducible-science) alongside `repro`, `citations` and `prereg` — see the [documentation](https://reproducible.science/tools/results/).

## Install

```bash
pip install results-cli
```

## Quick start

```bash
results init
results seal prereg.md analysis.py data.csv --role input
results access "read zenodo metadata" --level "metadata only"

# run the computation, then record its outputs
results run output.json --run-id exp_001 --note "ICC analysis"
results claim "ICC = 0.42" --run-id exp_001 --confirmatory --location "Table 2"
results verify --files
```

```text
chain intact: 5 events

  access       1
  claim        1
  init         1
  run          1
  seal         1

file hashes:
  ok         prereg.md
  ok         analysis.py
  ok         data.csv
  ok         output.json

all checks passed.
```

## Commands

| Command | What it does |
|---------|-------------|
| `results init` | Start tracking results here |
| `results seal <file>...` | Hash inputs before a run |
| `results access <note>` | Record a data-access event |
| `results run <file>...` | Record outputs after a run; `--holds` says the outputs hold metadata or structure and no outcome |
| `results label <run-id>` | Declare after the fact that a recorded run's outputs hold no outcome |
| `results claim <text>` | Bind a manuscript claim to a run |
| `results review <file>...` | Record that someone examined these files, and what they found |
| `results annotate <file>...` | Link these files to something outside the ledger; linked, not checked |
| `results verify` | Check the ledger chain and every hash it names |
| `results timestamp` | Date the ledger's head outside the repository, and check earlier dates |

## The chain

A number in a manuscript names a claim. The claim names a run. The run names its outputs. The
outputs were hashed when they were recorded. The inputs were hashed before the run started.

```text
manuscript  →  claim  →  run  →  output file  →  sha256
                                  input files  →  sha256
```

`results verify --files` walks the whole thing and tells you what moved.

## Reviews

Some checks are done by reading: a person, or a model, compares a table with the file behind it.
`results review` records that the reading happened, and of which bytes.

```bash
results review results/table3.csv paper/table3.pdf \
    --scope "every cell of Table 3 against the regenerated file" \
    --procedure "read the rendered page beside the csv" \
    --verdict partial --reviewer "A. Reader" --model claude-opus-5-5 \
    --note "30 cells agree at the certified revision; 4 differ"
```

Each file is recorded by its sha256, so the review is of those bytes and no others.
`results verify --files` lists every review and marks a subject `STALE` once the file has
changed, without failing: a reviewed file that then changes is the ordinary result of acting on
a review. `--scope`, `--procedure`, `--verdict` and `--reviewer` are required, and the verdict
is one of `pass`, `fail`, `partial` and `uncertain`.

The record is self-reported and unsigned. The ledger shows that the review was stated and when;
nothing checks who stated it. `--model` is the identifier the caller gives. Inside Claude Code
the command also records the harness, its version and the session identifier from the
environment, which does not say which model ran, so a model reviewer passes `--model`.

## Annotations

Some of what a paper rests on lives outside the repository: a Weights & Biases artifact, a
deposited dataset, an OSF node, a row in another group's table. `results annotate` records that
a file here corresponds to that outside thing.

```bash
results annotate checkpoints/model.pt \
    --kind wandb:artifact --ref "lab/study/model:v3" \
    --digest md5:0123456789abcdef0123456789abcdef \
    --by "A. Reader" --note "the checkpoint behind Table 2"

results annotate results/table2.csv \
    --kind doi:dataset --ref 10.5281/zenodo.1234567 --location "Table 2"
```

An annotation is a statement of a link and not a check: the tool fetches nothing and compares
nothing, and the event carries the status `linked, not checked`. Each file is recorded by its
sha256, so the link is stated of those bytes.

`--kind` and `--ref` are required. `--kind` is `namespace:type` in lowercase, such as
`wandb:artifact`, `doi:dataset`, `osf:node`, `url:page`, `zenodo:record` or `hf:dataset`; any
kind of that shape is accepted, and a malformed kind writes nothing. `--ref` is the artifact
path, DOI, URL or identifier. `--digest` records the digest the outside system reports, as
`algorithm:hex`. `--by` names who states the link, `--note` says anything else, and `--location`
names where in the manuscript the linked number or sentence appears. No session information is
recorded.

```text
annotations (linked, not checked):
  2026-10-11T16:54:21  wandb:artifact  lab/study/model:v3  [A. Reader]
    digest as stated: md5:0123456789abcdef0123456789abcdef
    STALE        checkpoints/model.pt
      annotated 1b465fa6b6bcbc06…, now 7e4fa2eb8c7ac089…
  2026-10-11T16:54:21  doi:dataset  10.5281/zenodo.1234567
    appears in: Table 2
    current      results/table2.csv
  1 annotated file(s) are no longer the bytes the link was stated of.
```

`results verify` lists every annotation. With `--files` each file is `current`, `STALE` once it
has changed, or `MISSING`; without `--files` it is `not checked`. None of the three changes the
exit code.

## Data-access levels

The access timeline is what makes the confirmatory/exploratory distinction verifiable.

| Level | Meaning |
|-------|---------|
| `nothing seen` | No target data touched |
| `metadata only` | Structure, region names, sample sizes — not outcomes |
| `structure seen` | Data shape and distributions, not the target variable |
| `outcomes seen` | The dependent variable was observed |

An analysis registered after `outcomes seen` is retrospective.

## Verify output

| Result | Meaning |
|--------|---------|
| `chain intact` | Every event's prev_hash matches the line before it |
| `CHAIN BROKEN` | The ledger was edited after it was written |
| `ok` | File matches its recorded hash |
| `CHANGED` | File was modified since it was recorded |
| `MISSING` | File no longer exists |

## The ledger

Append-only JSONL in `.results/ledger.jsonl`. Each line is hash-chained to the previous — editing
or inserting a line breaks the chain. `git diff` shows what changed; `results verify` checks
whether it should have.

`results init` writes a `.results/.gitignore` that ignores only the lock files, so the ledger and
its anchor are committed with the project. A ledger on one disk is a record nobody else can
check. What is committed is public with the repository, so a run's `note` is written as a commit
message would be.

## Timestamp

The chain catches a line edited by hand. It cannot catch the ledger and its anchor rewritten
together, because whoever can write one can write the other. `results timestamp` sends the head
to the [OpenTimestamps](https://opentimestamps.org) calendars, which commit it into a Bitcoin
block within a few hours, and keeps the proof under `.results/timestamps/`. Each line names the
hash of the one before it, so a proof of the head dates every earlier event too.

```text
events 1–153 existed by Bitcoin block 915004, 2026-10-03 16:12 UTC
```

`results verify` reads the proofs with no network. A proof whose head no longer matches the
chain at its length means the ledger was rewritten after it was stamped:

```text
TIMESTAMP CONTRADICTS THE CHAIN — the ledger was rewritten after it was stamped
  000153-3f9c2a1b7d4e5f60.ots dates event 153 as 3f9c2a1b7d4e5f60…, and the ledger's event 153 is 81d0…
```

## Claude Code

`plugin/` is a Claude Code plugin. Three surfaces, because each catches a different failure:
the hook catches what the model does not think to do, the skill catches what you did not know
to ask for, and the command is there for when you want the answer now.

| surface | fires |
|---|---|
| hook | when a number enters a manuscript that no recorded claim names |
| skill | when Claude judges the situation calls for sealing inputs, recording outputs, binding a paper's claims to runs |
| command | when you type `/results-check` |

**Why the hook.** The address is on screen while the sentence is being written and gone immediately afterward. A number recovered later has to be matched by its digits, and a value reported to two or three significant figures matches something in an artifact of any size.

It reports and never blocks, and stays silent in a project with no `.results/` ledger.

```bash
/plugin marketplace add elliottower/reproducible-science
/plugin install results@reproducible-science
```

The plugin ships instructions and hooks, not binaries, so install the tool as well:

```bash
uv tool install results-cli    # or: pip install results-cli
```

All four tools in one plugin, with every hook, skill and command:

```bash
/plugin install reproducible-science@reproducible-science
```

MIT licensed.

## This tool and `repro`

`results` installs and runs on its own, is not deprecated, and is not going to be.
`reproducible-science` depends on it, so `repro results ...` runs this same command with the
same arguments and the same exit code. That is a spelling, not a feature.

What only exists in the umbrella is `repro check`, which runs every tool a project uses in one
pass, with one report and one exit code, and names the tools the project does not use rather
than counting them as passing. If a project only records runs, use this command directly.
