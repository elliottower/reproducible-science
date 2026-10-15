---
title: Codex plugin
---

The Claude Code bundle also installs in [Codex](https://learn.chatgpt.com/docs/plugins), from the
same repository and the same directory. `packages/repro/plugin` carries a Codex manifest at
`.codex-plugin/plugin.json`, the Codex format described in
[Upload and submit your plugin](https://developers.openai.com/plugins/deploy/submission), beside
its Claude Code manifest, and both name the same `skills/` directory.

## Install

Add the repository as a marketplace:

```bash
codex plugin marketplace add elliottower/reproducible-science
```

Then run `/plugins` inside Codex and install `reproducible-science` from the
`reproducible-science` tab. Start a new session afterwards: bundled skills and tools are
available in a session started after installation.

The skills and the MCP server shell out to the command-line tools, which are installed
separately:

```bash
uv tool install reproducible-science   # prereg, citations, results, repro
```

Codex does not run a plugin's hooks until you have reviewed them. Open `/hooks`, read the
commands the plugin registers, and trust them. A hook changed by an update is skipped again until
it is trusted again.

## What you get

| surface | in Codex |
|---|---|
| skills | `prereg`, `prereg-style`, `osf-registration`, `citations`, `results`, `repro`, `open-items`, the same files Claude Code loads |
| MCP server | `repro`, started as `repro mcp` over stdio, with the tools `verify`, `why`, `stale`, `numbers`, `origins`, `prereg_check`, `results_verify`, `citations_verify`, `citations_audit`, `next_open_item`, `get_open_item`, `propose_binding`, `add_artifact`, `mark_reviewed` and `pin_quote` |
| hooks | the five Claude Code hooks, on Codex's events |
| commands | `/prereg-check` becomes the skill `source-command-prereg-check`; the other three take an argument, and Codex does not convert those, so use the `citations`, `results` and `repro` skills |

Codex edits files with `apply_patch`, which sends the patch text rather than a file path. The
plugin runs each edit hook through `hooks/codex_apply_patch.py`, which reads the patch and runs
the hook once for each file it touches, with the input Claude Code would have sent for that file.
A patch sent as a shell command is read the same way.

A frozen file moved or deleted by a shell command such as `mv` or `rm` is not blocked, and
`prereg check`, which compares every frozen file's sha256 with its freeze record, reports that
change, as it reports a change by any route.

| hook | Codex event | fires when |
|---|---|---|
| frozen file before edit | `PreToolUse` on `apply_patch` and `Bash` | a patch would change, delete, overwrite or move a frozen plan or a frozen amendment; the patch is refused |
| unfrozen plan before run | `PreToolUse` on `Bash` | an analysis is about to run under a plan that was never frozen |
| frozen plan changed | `PostToolUse` on `apply_patch` and `Bash` | a preregistration no longer matches the digest it was frozen with |
| unverified quotation | `PostToolUse` on `apply_patch` and `Bash` | a passage enters a manuscript that no claim file pins to a source |
| unbound number | `PostToolUse` on `apply_patch` and `Bash` | a number enters a manuscript that no recorded claim names |

As in Claude Code, only the first refuses anything, and every hook is silent in a project that
has not opted in.

## Limits

These come from Codex, not from the plugin:

- The `repro` MCP server starts in the session's working directory: the folder Codex was
  started in, or the one given with `codex --cd`. Codex passes it no `--root` and offers no MCP
  roots, so each call finds its project from the path it is given: the nearest folder at or
  above that path holding `repro.yaml`, `repro.draft.yaml`, `.results/`, `.prereg/`, `claims/`
  or `PREREG.md`. A call with no path takes its `project` argument, else the project of the
  previous call, else the project above that working directory. Where none is found the tool
  answers `no project: pass a path or a project`. Every path a call gives is kept inside its
  project.
- Hooks run where Codex runs locally: the CLI and Codex in the ChatGPT desktop app. Plugin hooks
  do not run in cloud-orchestrated ChatGPT Work, and the IDE extension does not load plugins
  ([plugins](https://learn.chatgpt.com/docs/plugins)).
- A plugin that bundles hooks is not eligible for the public plugin directory, so this one is
  installed from its repository
  ([packaging](https://developers.openai.com/codex/plugins/build)).
- Codex calls its tool hooks "a useful guardrail, not a complete enforcement boundary": some tool
  paths can bypass them ([hooks](https://developers.openai.com/codex/hooks)).

## References

- Plugins: <https://learn.chatgpt.com/docs/plugins>
- Packaging a plugin, manifests and marketplaces: <https://developers.openai.com/codex/plugins/build>
- Codex manifest fields: <https://developers.openai.com/plugins/deploy/submission>
- MCP server settings: <https://developers.openai.com/codex/mcp>
- Hooks, events and their input and output: <https://developers.openai.com/codex/hooks>
- Skills: <https://developers.openai.com/codex/skills>
