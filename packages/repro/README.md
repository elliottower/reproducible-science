# reproducible-science

[![pypi](https://img.shields.io/pypi/v/reproducible-science)](https://pypi.org/project/reproducible-science/)
[![python](https://img.shields.io/pypi/pyversions/reproducible-science)](https://pypi.org/project/reproducible-science/)
[![license](https://img.shields.io/pypi/l/reproducible-science)](https://github.com/elliottower/reproducible-science/blob/main/LICENSE)
[![docs](https://img.shields.io/badge/docs-live-blue)](https://elliottower.github.io/reproducible-science/)

Check whether a paper's claims match its artifacts.

Part of [reproducible-science](https://github.com/elliottower/reproducible-science) alongside `citations`, `results` and `prereg` — see the [documentation](https://elliottower.github.io/reproducible-science/tools/repro/).

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
done.
```

`init` spawns `prereg new`, `results init` and `citations init`, whose own output it does not
relay; the two lines above are everything it prints itself.

This creates:

```text
my_experiment/
    CLAUDE.md           tells Claude Code about the tools
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

## Verify everything at once

```bash
cd my_experiment
repro verify
```

Reads `repro.yaml` and checks every declared evidence assertion against the artifact it names. It spawns nothing: `prereg`, `results` and `citations` are separate commands.

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

This repository is a Claude Code plugin marketplace. One plugin carries all four tools:

```bash
/plugin marketplace add elliottower/reproducible-science
/plugin install reproducible-science@reproducible-science
```

It installs four skills, four commands and three hooks. The hooks are the part a CLI
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
