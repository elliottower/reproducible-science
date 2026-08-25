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

## What you get

Each plugin installs a skill rather than a slash command. Claude reads the skill's description
and uses it when the situation calls for it — you do not invoke it by name.

| skill | when it applies |
|---|---|
| `prereg` | freezing a plan before a run, and recording what changed after |
| `citations` | quoting a paper, adding a citation, or checking whether a quote is real |
| `results` | sealing inputs, recording outputs, binding a paper's claims to runs |

Each skill shells out to the published package of the same name, so the CLI has to be installed
where Claude is running:

```bash
uv tool install citations
```

A project can move between the plugin and the command line without changing anything on disk.

## Verifying

Verification runs from the command line:

```bash
pip install reproducible-science
repro verify
```
