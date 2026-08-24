# The Claude Code plugin

Tells Claude the `prereg` CLI exists and when to reach for it. The CLI does the work; this adds
nothing the CLI cannot do.

## Install

```bash
/plugin marketplace add elliottower/prereg
/plugin install prereg@prereg
```

The plugin ships instructions, not binaries. Install the tool too:

```bash
uv tool install prereg
```

For development against a checkout:

```bash
/plugin marketplace add ~/Documents/GitHub/prereg
/plugin install prereg@prereg
```

## What it changes

Claude will freeze a plan before running it rather than after, commit the PREREG.md on its own so
the freeze is not contaminated by a code change, and log a change to a frozen plan instead of
editing it quietly. It will also stop writing `**Status:** FROZEN` headers by hand, which produce a
document that reads as registered and cannot be verified.
