# The Claude Code plugin

Tells Claude the `results` CLI exists and when to reach for it. The CLI does the work; this
adds nothing the CLI cannot do.

## Install

```bash
/plugin marketplace add elliottower/reproducible-science
/plugin install results@reproducible-science
```

The plugin ships instructions, not binaries. Install the tool too:

```bash
uv tool install results-cli
```

For development against a checkout:

```bash
/plugin marketplace add ~/Documents/GitHub/results
/plugin install results@reproducible-science
```

## What it changes

Claude will seal inputs before running a computation rather than after, record outputs with their
hashes, and bind manuscript claims to specific runs instead of leaving numbers untraced. It will
also record data-access events so the distinction between confirmatory and exploratory analysis
is verifiable from the timeline, not from a self-report.
