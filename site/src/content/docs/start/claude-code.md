---
title: Claude Code plugin
---

```
/plugin marketplace add elliottower/reproducible-science
```

Then install whichever tools you want:

```
/plugin install reproducible-science@reproducible-science
```

Or one tool at a time:

```
/plugin install prereg@reproducible-science
/plugin install citations@reproducible-science
/plugin install results@reproducible-science
/plugin install repro@reproducible-science
```

## Why use it instead of the CLI

The commands are the same. What changes is when they run.

Provenance is easiest to record while the work is happening and hardest to reconstruct
afterward — the inputs a run consumed, the outputs it produced, and the order of the two. Used
from inside a session, the plugin records that chain as you go, so a claim written into a paper
weeks later still has a run behind it.

## What you get

Each plugin carries three surfaces, because each catches a different failure.

| surface | fires |
|---|---|
| hook | on the tool event, whether or not anyone remembered |
| skill | when Claude judges the situation calls for it |
| command | when you type it |

The hooks are the part a CLI cannot do, since each fires at a moment rather than when you
think to run something:

| hook | fires when |
|---|---|
| frozen plan changed | a preregistration no longer matches the digest it was frozen with |
| unverified quotation | a passage enters a manuscript that no claim file pins to a source |
| unbound number | a number enters a manuscript that no recorded claim names |

Every hook reports and never blocks, and stays silent in a project that has not opted in: no
ledger, no claims directory and no frozen plan means nothing to check and nothing said.

The commands are `/prereg-check`, `/citations-check`, `/results-check` and `/repro-check`,
named alike so there is nothing to remember about which tool answers which question.

Each skill shells out to the published package of the same name, so the CLI has to be
installed where Claude is running:

```bash
uv tool install reproducible-science   # or: pip install reproducible-science
```

A project can move between the plugin and the command line without changing anything on
disk.


## Verifying

Verification runs from the command line:

```bash
pip install reproducible-science
repro verify
```
