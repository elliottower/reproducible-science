# The Claude Code plugin

Tells Claude the `citations` CLI exists and when to reach for it. The CLI does the work; this
adds nothing the CLI cannot do.

## Install

Drop it in, no install step:

```bash
cp -r plugin ~/.claude/skills/citations
```

A directory under `~/.claude/skills/` containing `.claude-plugin/plugin.json` is discovered in
place on the next session. Note that a bare `SKILL.md` copied there is *not* enough — the
manifest directory is what makes it load.

For development against a checkout:

```bash
claude --plugin-dir ./plugin
```

## It needs the CLI

The manifest has no field for declaring an external binary, so the requirement lives in the
skill's description instead:

```bash
uv tool install citations     # or: pip install citations
```

Without it Claude will read the skill, run the command, and get "command not found".
