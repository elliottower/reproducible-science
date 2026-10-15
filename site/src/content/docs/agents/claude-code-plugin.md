---
title: Claude Code plugin
description: The Claude Code plugin, with a skill per tool, four commands and five hooks.
---

This repository is a Claude Code plugin marketplace. One plugin carries all four tools:

```bash
/plugin marketplace add elliottower/reproducible-science
/plugin install reproducible-science@reproducible-science
```

It installs a skill for each tool, `prereg-style` and `osf-registration` beside them, four commands and five hooks. The hooks are the part a CLI
cannot do, because each fires at a moment rather than when you remember to run something:

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
