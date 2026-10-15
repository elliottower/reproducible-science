---
title: MCP server
description: repro mcp serves the toolkit's checks, and the open items of a draft, as tools of an MCP server.
---

`repro mcp` runs an MCP server over standard input and output. Its tools are the toolkit's
checks, the open items of a reader's draft one at a time, and four writes, each one line of a
draft manifest or one pinned quotation. It ships in 0.7.0.

## Setup

Install the toolkit, then register the server once per agent, for every project.

Claude Code:

```bash
uv tool install reproducible-science
claude mcp add --transport stdio --scope user reproducible-science -- repro mcp
```

Any MCP client that launches a stdio server takes the same command and arguments:

```json
{
  "mcpServers": {
    "reproducible-science": { "type": "stdio", "command": "repro", "args": ["mcp"] }
  }
}
```

`--root DIR` sets the project of a call that names no path or project, until one does.

## Tools

| tool | does | refuses or never does |
|---|---|---|
| `verify` | checks every assertion in a manifest under `exploratory`, `publication` or `strict` | a policy it does not know; writes no record of checks |
| `why` | what the record establishes for one claim | never calls an inferred match verified: it reads `matched, inferred: not verified` |
| `stale` | which claims read a file changed since its recorded re-run | executes nothing |
| `numbers` | every number the manuscript prints, and whether a claim binds it | |
| `origins` | each copied artifact against its origin | compares with a local clone only; fetches nothing |
| `prereg_check`, `results_verify`, `citations_verify` | the three tools' own checks | |
| `citations_audit` | each `.bib` entry against its registry record, ten a call: agrees, disagrees, not found, or could not check | the only tool that reaches the network, and only to read registries; writes no `.bib`, record or claims file; a call that compared nothing does not pass |
| `next_open_item`, `get_open_item` | one open item: the claim, the printed value, the sentence, and each candidate's address, labels and stored value | carries no file contents beyond the cell and its labels |
| `propose_binding` | inserts one assertion, `basis: inferred`, into the claim the item names, and checks it | another basis, `reviewed`, a claim not in the file or the draft, a kind that fills no open item, a missing or changed `reported`, an undeclared artifact, an oversized field; never replaces a matched, declared or reviewed assertion; warns from the sixth attempt |
| `add_artifact` | declares a file in the draft, pinned by sha256 and `basis: inferred` | a path outside the project, a directory, a Git LFS pointer, a file over 64 MiB, a file or id already declared |
| `mark_reviewed` | records the user's approval in the chat as `reviewed`: git user, time, client, and the digest of what was accepted | an item that did not match, a claim the draft lacks, a project with no git user; the review lapses when what it accepted changes |
| `pin_quote` | `citations pin`: adds a quotation that resolves in its pinned source | writes nothing for a passage the source lacks, or with `check`; refuses an id the file holds, so a pinned quotation is never replaced |

Each write changes one line of the draft and no other byte. Every proposal is appended to a hash
chain in `.repro/attempts.jsonl` beside the open-items file, which `claims open-items` counts
from.

Nothing the server offers freezes or registers a plan, seals or records a run, runs a declared
command, or publishes. Its instructions tell the agent to ask a person to run those.

## How the project is found

Each call works in the project its path is in: the nearest folder at or above the path holding
one of `repro.yaml`, `repro.draft.yaml`, `.results`, `.prereg`, `claims` or `PREREG.md`. A
reader's draft folder inside a project belongs to that project. Every result names the project
as `root`.

- A call with no path takes its `project` argument, else the project of the last call, else
  `--root`, else the project above the working directory.
- A path under no project is refused, and a call with no project anywhere says to pass one.
- A symlink belongs to the folder it sits in, never where it points. A path that resolves
  outside its project is refused, and so is a manifest that declares a file outside it.

## Does not claim

A proposal that matched is a proposal that held, not a verified claim. It counts as declared
only after a person approves it and `mark_reviewed` records the approval.

## The other project

The [Model Context Protocol](https://modelcontextprotocol.io/).

Not affiliated with or endorsed by the Model Context Protocol project.
