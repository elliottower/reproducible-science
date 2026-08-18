# reproducible-science

Scaffold reproducible science workflows in one command.

## Install

```bash
pip install reproducible-science
```

This installs `repro` and its three dependencies: [`prereg`](https://pypi.org/project/prereg/), [`citations`](https://pypi.org/project/citations/), [`results-cli`](https://pypi.org/project/results-cli/).

## Quick start

```bash
repro init my_experiment
```

```
initializing my_experiment
  wrote my_experiment/PREREG.md
  wrote my_experiment/.results/ledger.jsonl
  wrote my_experiment/.citations/
  wrote my_experiment/CLAUDE.md
```

This creates:

```
my_experiment/
    PREREG.md           the plan (OSF headings)
    CLAUDE.md           tells Claude Code about the tools
    .results/           results ledger
    .citations/         citation library
    claims/             claim files for citation verification
    data/               raw data
    scripts/            analysis scripts
    figures/            output figures
```

## Verify everything at once

```bash
cd my_experiment
repro verify
```

Runs `prereg check`, `results verify --files`, and `citations verify --claims claims/` in sequence.

## The workflow

```bash
prereg freeze                         # lock the plan
results seal PREREG.md analysis.py    # hash inputs
results access "read metadata" --level "metadata only"

# run the computation

results run output.json --run-id exp_001
results claim "ICC = 0.42" --run-id exp_001 --confirmatory --location "Table 2"
repro verify                          # check everything
```

## What's included

| Tool | CLI | PyPI | What it does |
|------|-----|------|-------------|
| prereg | `prereg` | [`prereg`](https://pypi.org/project/prereg/) | Freeze a plan before running, record what changed after |
| citations | `citations` | [`citations`](https://pypi.org/project/citations/) | Verify quotations resolve in pinned source artifacts |
| results | `results` | [`results-cli`](https://pypi.org/project/results-cli/) | Seal inputs, record outputs, bind claims to runs, verify the chain |

## Claude Code

This repo is also a Claude Code plugin marketplace bundling all three tools:

```bash
/plugin marketplace add elliottower/reproducible-science
```

Or install them individually: [`elliottower/prereg`](https://github.com/elliottower/prereg), [`elliottower/citations`](https://github.com/elliottower/citations), [`elliottower/results`](https://github.com/elliottower/results).

MIT licensed.
