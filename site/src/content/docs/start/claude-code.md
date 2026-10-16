---
title: Claude Code plugin
---

```text
/plugin marketplace add elliottower/reproducible-science
```

Then install whichever tools you want:

```text
/plugin install reproducible-science@reproducible-science
```

Or one tool at a time:

```text
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
| frozen file before edit | an edit targets a frozen plan or a frozen amendment; the edit is refused |
| frozen plan changed | a preregistration no longer matches the digest it was frozen with |
| unverified quotation | a passage enters a manuscript that no claim file pins to a source |
| unbound number | a number enters a manuscript that no recorded claim names |

An edit to a frozen plan or a frozen amendment is refused, with the instruction to record a note
with `prereg log` or a change with `prereg amend`. Every other hook reports and never blocks. All
of them stay silent in a project that has not opted in: no ledger, no claims directory and no
frozen plan means nothing to check and nothing said.

The commands are `/prereg-check`, `/citations-check`, `/results-check` and `/repro-check`,
named alike so there is nothing to remember about which tool answers which question.

Each tool's skill shells out to the published package of the same name, so the CLI has to be
installed where Claude is running:

```bash
uv tool install reproducible-science --with-executables-from claims-cli,prereg,results-cli,citations
```

Without `--with-executables-from`, uv puts only `repro` on PATH. `pip install
reproducible-science` installs all five commands.

A project can move between the plugin and the command line without changing anything on
disk.

## Verifying

Verification runs from the command line:

```bash
pip install reproducible-science
repro verify
```

See the [Claude Code plugin](/agents/claude-code-plugin/) page for more information.
