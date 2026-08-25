---
title: Claude Code plugin
---

```
/plugin marketplace add elliottower/reproducible-science
```

Then install whichever tools you want:

```
/plugin install prereg@reproducible-science
/plugin install citations@reproducible-science
/plugin install results@reproducible-science
```

## Why use it instead of the CLI

The commands are the same. What changes is when they run.

Provenance is easiest to record while the work is happening and hardest to reconstruct
afterward — the inputs a run consumed, the outputs it produced, and the order of the two. Used
from inside a session, the plugin records that chain as you go, so a claim written into a paper
weeks later still has a run behind it.

## Commands

| command | what it does |
|---|---|
| `/prereg` | freeze a plan before running, and record what changed after |
| `/citations` | check that quotations resolve in the sources they cite |
| `/results` | seal inputs, record outputs, bind a paper's claims to runs |

Each is backed by the published package of the same name, so a project can move between the
plugin and the command line without changing anything on disk.

## Verifying

Verification runs from the command line:

```bash
pip install reproducible-science
repro verify
```
