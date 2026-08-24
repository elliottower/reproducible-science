# The Claude Code plugin

Tells Claude the `citations` CLI exists and when to reach for it. The CLI does the work; this
adds nothing the CLI cannot do.

## Install

```bash
/plugin marketplace add elliottower/citations
/plugin install citations@citations
```

The plugin ships instructions, not binaries. Install the tool too:

```bash
uv tool install citations
```

For development against a checkout:

```bash
/plugin marketplace add ~/Documents/GitHub/citations
/plugin install citations@citations
```

## What it changes

Claude will look up a source before quoting it rather than generating text that sounds like what
a paper says. It will pin quotations to artifacts with sha256 hashes, run `citations verify` to
check them, and flag truncated quotes that stop mid-number.
