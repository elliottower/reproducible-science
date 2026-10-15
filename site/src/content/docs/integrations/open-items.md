---
title: Open items
description: The open-items agent skill fills what a reader left open, and claims open-items counts the result.
---

A reader of another tool's files, such as `claims from-codecheck`, `claims from-corebench` or
`claims from-clawbio`, writes `repro.draft.yaml` and `open-items.json`. Each item is a gap the
source left: a value with no address, or a claim with no passage. Two pieces fill and count
those items: an agent skill, and a command. The [MCP server](/integrations/mcp/) offers the
same procedure as tools, and `repro init` writes the same two files for a project's own
result files.

## The skill

`open-items` ships in the `reproducible-science` Claude Code plugin. It is the procedure an
agent follows: count, take each item in turn, propose an assertion marked `basis: inferred`,
let `claims verify` decide, and count again.

- **Reads** `open-items.json`, the draft, and the files each item names.
- **Writes** assertions into `repro.draft.yaml` only, and saves the counts before and after as
  `open-items.before.json` and `open-items.after.json`.
- **Uses** only `claims open-items`, `claims verify`, `claims why`, `citations pin`,
  `citations verify` and `shasum`.

The skill's rules are instructions to the agent. It tells the agent never to edit
`open-items.json`, never to delete a claim to close an item, never to remove `basis: inferred`
or write `reviewed`, never to change `reported` to make a check pass, never to edit a pinned
quotation, never to run anything in a capsule or bundle, and never to call any assertion it
wrote verified.

## The command

`claims open-items` reads the open-items file and the draft beside it, checks the draft as
`claims verify` does, and counts each claim once: bound from the source alone, every item
filled by assertions that matched, filled by one that did not, still open, or outside the items.

```bash
claims open-items draft/open-items.json --format json
```

## Enforced in code

These hold whatever the agent does:

- An inferred assertion that matched is never counted as verified, and a draft holding one
  fails the `strict` and `publication` policies.
- An item is closed by filling it: a draft whose item's claim was deleted is refused.
- An item naming a claim the draft lacks writes nothing, and an open-items file never names a
  draft outside its directory.
- A reader never writes over an existing draft.
- `claims open-items` executes nothing, writes nothing, and exits 0 whatever it counts.

## Does not claim

An inferred assertion that matched is a proposal that held. It becomes a declared assertion
only when an author accepts it, by deleting its `basis` line or recording
`reviewed: {who, when}`. The agent never does either.

## The other project

The readers that write open items: [CODECHECK](/integrations/codecheck/),
[CORE-Bench](/integrations/core-bench/) and [ClawBio](/integrations/clawbio/).

Not affiliated with or endorsed by CODECHECK, CORE-Bench or ClawBio.
