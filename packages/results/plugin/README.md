# The `results` Claude Code plugin

Does every number in the manuscript name the run that produced it?

Three surfaces, because each catches a different failure. The hook catches what the model
does not think to do, the skill catches what the author did not know to ask for, and the
command is there for when you want the answer now.

| | |
|---|---|
| **hook** `hooks/unbound_numbers.py` | fires when a number enters a manuscript that no recorded claim names |
| **skill** `skills/results/SKILL.md` | fires when Claude judges the tool relevant |
| **command** `/results-check` | fires when you type it |

## Why the hook

Recovering a binding after the fact does not work. Measured against 45 CORE-Bench capsules, values precise enough to identify are found about three times in four, and values reported to two or three significant figures cannot be identified at all, because a short number matches something in an artifact of any size. While writing, the address is on screen.

It reports and never blocks, exits zero on every failure path, and stays silent in a project
with no `.results/` ledger — nothing to check means nothing said.

## What the skill changes

Claude seals a run's inputs before computing, records the outputs after, and binds a number to its run as the sentence is written rather than leaving it to be traced later.

## Install

```bash
/plugin marketplace add elliottower/reproducible-science
/plugin install results@reproducible-science
```

The plugin ships instructions and hooks, not binaries. Install the tool as well:

```bash
uv tool install results
```

Against a checkout:

```bash
/plugin marketplace add ~/Documents/GitHub/reproducible-science
/plugin install results@reproducible-science
```

## The other three

`prereg`, `citations`, `results` and `repro` are one lifecycle, and each plugin ships
separately so you can take only what you use. `reproducible-science@reproducible-science`
installs all of them at once.
