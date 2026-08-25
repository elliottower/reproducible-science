# The `citations` Claude Code plugin

Does each quotation in the manuscript appear in the source it cites?

Three surfaces, because each catches a different failure. The hook catches what the model
does not think to do, the skill catches what the author did not know to ask for, and the
command is there for when you want the answer now.

| | |
|---|---|
| **hook** `hooks/unverified_quotations.py` | fires when a passage enters a manuscript that no claim file pins to a source |
| **skill** `skills/citations/SKILL.md` | fires when Claude judges the tool relevant |
| **command** `/citations-check` | fires when you type it |

## Why the hook

A quotation is the one thing in a paper that can be checked exactly: it is in the source or it is not. Prose is where a remembered sentence drifts, and nearly right is wrong. The check is cheap while the source is open and impossible once the paper is finished.

It reports and never blocks, exits zero on every failure path, and stays silent in a project
with no `claims/` directory — nothing to check means nothing said.

## What the skill changes

Claude looks a source up before quoting it rather than producing text that sounds like what the paper says, pins quotations to artifacts by sha256, and reports `unchecked` where a source could not be read rather than calling the passage missing.

## Install

```bash
/plugin marketplace add elliottower/reproducible-science
/plugin install citations@reproducible-science
```

The plugin ships instructions and hooks, not binaries. Install the tool as well:

```bash
uv tool install citations
```

Against a checkout:

```bash
/plugin marketplace add ~/Documents/GitHub/reproducible-science
/plugin install citations@reproducible-science
```

## The other three

`prereg`, `citations`, `results` and `repro` are one lifecycle, and each plugin ships
separately so you can take only what you use. `reproducible-science@reproducible-science`
installs all of them at once.
