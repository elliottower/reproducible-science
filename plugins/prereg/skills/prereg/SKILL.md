---
name: prereg
description: Freeze an experiment's plan against a commit and a content hash before running it, then log amendments and deviations. Use when writing or freezing a PREREG.md, before launching a run a plan governs, when a frozen plan needs to change, or when asked whether a plan still says what it said. Requires the `prereg` CLI (`uv tool install prereg`).
---

# prereg

A plan, frozen against a commit and a hash, plus an append-only log of what changed after.

## The rule that matters

**Freeze before you look. Never write the header by hand.**

A pre-registration is worth exactly one thing: evidence that the predictions existed before the
data did. Every way it fails is a version of the plan moving after the numbers were seen — a
threshold nudged, a hypothesis dropped, a subgroup added. The freeze exists so that movement leaves
a trace, and a hand-written `**Status:** FROZEN` header leaves none. It produces a document that
reads as registered and cannot be verified, which is worse than one that never claimed to be.

`**Status:**`, `**Plan sha256:**` and `**Frozen:**` are the tool's output. Writing them yourself is
the one thing this skill exists to prevent.

## Commands

```bash
prereg new <name>      # scaffold PREREG.md in OSF's headings, plus tests/ and results/
prereg freeze          # write the header, hash the plan, append to the log
prereg log <note> --access <level>
prereg check           # has anything above the log line changed since the freeze?
```

## Freezing, in order

1. **Write the plan, then get it reviewed.** A plan frozen without review registers the author's
   guesses, not an agreed design.
2. **Commit the PREREG.md alone.** No code in that commit. A freeze whose commit also carries a
   code change cannot distinguish the registered design from the change made while registering it.
3. **`prereg freeze`** in the experiment directory. It refuses on a dirty tree, because the freeze
   names a commit.
4. **Commit the freeze header.** The freeze is only evidence once it is in history.
5. **Then run.** Not before step 4.

## Reading `prereg check`

Three results, exhaustive:

| exit | | |
|---|---|---|
| 0 | `unchanged` | the plan says what it said |
| 1 | `CHANGED` | the plan was edited above the log line after freezing |
| 2 | `not frozen` | no hash recorded — **nothing was measured** |

**`not frozen` is not a pass.** It is the absence of a check, and it reads identically to success
if you only look at whether the command complained.

**`CHANGED` is not fixed by re-freezing.** Re-freezing overwrites the evidence that the plan moved.
Restore the plan and `prereg log` the change with an honest `--access`.

At a repository root with no governing plan, `check` checks every plan below it.

## Amendments and deviations

`--access` is one of `nothing run`, `no results seen`, `results not opened`, `results seen`. It
records what was known when the change was made, so the distinction is never a judgment call: an
entry logged before results is an amendment, one logged after is a deviation. Log the honest level
even when it is the damaging one — that is the entire function of the field.

## When to reach for this

- Before launching any run whose result will be reported as confirmatory
- When a plan is ready to freeze, after review
- When a frozen plan has to change — log first, never edit silently
- Before reporting a result a plan governs, to confirm the plan still says what it said
- In CI, as `prereg check`

## Non-obvious behavior

- `freeze` is idempotent: the commit, digest and date sit on lines the hash skips, so re-freezing
  an unedited plan reproduces its hash.
- `--force` re-freezes an already-frozen plan. Use it when the plan legitimately changed and was
  re-committed, never to clear a `CHANGED` warning.
- Appending below the log line is the allowed edit and does not fail `check`.

## What it will not do

It cannot prove you did not run the experiment first. Nothing can: a timestamp bounds when
something existed, never when the work began. It also cannot tell you the plan was any good — a
frozen bad design is still a bad design, registered.
