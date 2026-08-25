# The `prereg` Claude Code plugin

Is the plan still the plan that was registered?

Three surfaces, because each catches a different failure. The hook catches what the model
does not think to do, the skill catches what the author did not know to ask for, and the
command is there for when you want the answer now.

| | |
|---|---|
| **hook** `hooks/frozen_plan_changed.py` | fires when a frozen preregistration no longer matches the digest it was frozen with |
| **skill** `skills/prereg/SKILL.md` | fires when Claude judges the tool relevant |
| **command** `/prereg-check` | fires when you type it |

## Why the hook

This is the only exact check in the set. It recomputes a hash the author recorded and compares two strings, so there is no threshold and no judgment. It is also the one whose failure matters most: a plan rewritten around a result defeats registration entirely, and no reader can detect it afterward. The hook reports the difference and never edits the registration.

It reports and never blocks, exits zero on every failure path, and stays silent in a project
with no frozen plan — nothing to check means nothing said.

## What the skill changes

Claude freezes a plan before running rather than after seeing the outcome, and records amendments and deviations in the log instead of editing the plan in place.

## Install

```bash
/plugin marketplace add elliottower/reproducible-science
/plugin install prereg@reproducible-science
```

The plugin ships instructions and hooks, not binaries. Install the tool as well:

```bash
uv tool install prereg
```

Against a checkout:

```bash
/plugin marketplace add ~/Documents/GitHub/reproducible-science
/plugin install prereg@reproducible-science
```

## The other three

`prereg`, `citations`, `results` and `repro` are one lifecycle, and each plugin ships
separately so you can take only what you use. `reproducible-science@reproducible-science`
installs all of them at once.
