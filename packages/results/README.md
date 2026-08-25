# results

[![pypi](https://img.shields.io/pypi/v/results-cli)](https://pypi.org/project/results-cli/)
[![python](https://img.shields.io/pypi/pyversions/results-cli)](https://pypi.org/project/results-cli/)
[![license](https://img.shields.io/pypi/l/results-cli)](https://github.com/elliottower/reproducible-science/blob/main/LICENSE)
[![docs](https://img.shields.io/badge/docs-live-blue)](https://elliottower.github.io/reproducible-science/)

Seal inputs, record outputs, and bind a paper's claims to the runs behind them.

Part of [reproducible-science](https://github.com/elliottower/reproducible-science) alongside `repro`, `citations` and `prereg` — see the [documentation](https://elliottower.github.io/reproducible-science/tools/results/).

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
| `results run <file>...` | Record outputs after a run |
| `results claim <text>` | Bind a manuscript claim to a run |
| `results verify` | Check the ledger chain and every hash it names |

## The chain

A number in a manuscript names a claim. The claim names a run. The run names its outputs. The
outputs were hashed when they were recorded. The inputs were hashed before the run started.

```text
manuscript  →  claim  →  run  →  output file  →  sha256
                                  input files  →  sha256
```

`results verify --files` walks the whole thing and tells you what moved.

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
uv tool install results        # or: pip install results
```

All four tools in one plugin, with every hook, skill and command:

```bash
/plugin install reproducible-science@reproducible-science
```

MIT licensed.
