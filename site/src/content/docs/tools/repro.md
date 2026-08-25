---
title: Repro
description: Repro — Reproducible Science
---

<!-- Generated from packages/repro/README.md. Edit that file, not this one. -->

Scaffold reproducible science workflows in one command.

**[Run it in your browser](/reproducible-science/demo/end-to-end/)** — every command on this page, in a live notebook. No install.

## Install

```bash
pip install reproducible-science
```

This installs `repro` and its three dependencies: [`prereg`](https://pypi.org/project/prereg/), [`citations`](https://pypi.org/project/citations/), [`results-cli`](https://pypi.org/project/results-cli/).

## Quick start

```bash
repro init my_experiment
```

```text
initializing my_experiment
  wrote my_experiment/my_experiment/PREREG.md
  wrote my_experiment/.results/ledger.jsonl
  wrote my_experiment/.citations/
  wrote my_experiment/CLAUDE.md
```

This creates:

```text
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

Reads `repro.yaml` and checks every declared evidence assertion against the artifact it names. It spawns nothing: `prereg`, `results` and `citations` are separate commands.

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

This repo is also a Claude Code plugin marketplace bundling all three tools:

```bash
/plugin marketplace add elliottower/reproducible-science
```

Or install them individually: [`prereg`](https://github.com/elliottower/reproducible-science/tree/main/packages/prereg), [`citations`](https://github.com/elliottower/reproducible-science/tree/main/packages/citations), [`results`](https://github.com/elliottower/reproducible-science/tree/main/packages/results).

MIT licensed.
