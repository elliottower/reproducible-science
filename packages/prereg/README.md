# prereg

Preregister your plan to prevent p-hacking and unfalsifiable post-hoc analysis.

## Install

```bash
pip install prereg
```

## Quick start

```bash
prereg new V16_reliability_ceilings
# fill in the plan, commit it
prereg freeze
# run the experiment, then log what happened
prereg log "tolerance now derived from fixtures" --access "no results seen"
prereg check
```

```text
unchanged    V16_reliability_ceilings/PREREG.md
```

## Commands

| Command | What it does |
|---------|-------------|
| `prereg new <name>` | Scaffold a plan in OSF's headings |
| `prereg freeze` | Record the commit and hash |
| `prereg freeze --osf` | Freeze and push as a draft registration to OSF |
| `prereg log <note>` | Append to the log without freezing |
| `prereg check` | Has the plan changed since the freeze? |
| `prereg setup` | Save your OSF token to `.env` |

## One file, one rule

```text
V16_reliability_ceilings/
    PREREG.md      the plan, then a line, then an append-only log
    tests/  results/
```

**Never edit above the line. Only append below it.**

`prereg check` enforces it — the freeze records a hash of the plan, and any later edit to it
fails the check. Appending to the log does not.

## The log

```text
2026-08-11  frozen at 9894e148e429              nothing run
2026-08-13  tolerance now from fixtures         no results seen
2026-08-14  ran                                 results not opened
2026-08-15  C5 failed at k=15: 6.6% vs 5%       results seen
```

The last column is what distinguishes an amendment from a deviation, so you never have to
decide which word to use. `nothing run`, `no results seen`, `results not opened`, `results
seen`. An entry logged before results is an amendment; one logged after is a deviation.

## Check output

| Exit | Result | Meaning |
|------|--------|---------|
| 0 | `unchanged` | The plan says what it said |
| 1 | `CHANGED` | The plan was edited above the line after freezing |
| 2 | `not frozen` | No hash recorded — nothing was measured |

`not frozen` is not a pass. It is the absence of a check.

## The plan uses OSF's headings

Verbatim, so the document maps onto an [OSF registration](https://osf.io/prereg/) without being
rewritten. Two of the twenty-seven do the real work:

- **Foreknowledge of data or evidence** — what you have already seen.
- **Inference criteria** — the decision rule as a commitment, before the number exists.

A heading that does not apply is answered `N/A` with a reason, never deleted.

## OSF integration

The plan uses OSF's question titles verbatim, so `prereg freeze --osf` pushes it directly to
OSF as a draft registration. You review and submit it there — submission is irreversible.

```bash
prereg setup                  # save your OSF token (once)
prereg freeze --osf           # freeze locally and push to OSF
```

Create a token at [osf.io/settings/tokens](https://osf.io/settings/tokens) with the
`osf.full_write` scope. The token is stored in `.env` (gitignored).

## What a freeze is

A commit and a hash. The commit is the evidence — it is in history, dated, and not yours to
revise quietly. The hash is the convenience that lets `prereg check` tell you in a second
whether the plan still says what it said.

Neither proves you did not run the experiment first. Nothing can: a timestamp bounds when
something existed, never when work began.

## Claude Code

`plugin/` is a Claude Code plugin. Three surfaces, because each catches a different failure:
the hook catches what the model does not think to do, the skill catches what you did not know
to ask for, and the command is there for when you want the answer now.

| surface | fires |
|---|---|
| hook | when a frozen preregistration no longer matches the digest it was frozen with |
| skill | when Claude judges the situation calls for freezing a plan before a run, and recording what changed after |
| command | when you type `/prereg-check` |

**Why the hook.** This is the only exact check in the set. It recomputes a hash you recorded and compares two strings, so there is no threshold and no judgment. A plan rewritten around a result defeats registration entirely and no reader can detect it afterward, so the hook reports the difference and never edits the registration.

It reports and never blocks, and stays silent in a project with no frozen plan.

```bash
/plugin marketplace add elliottower/reproducible-science
/plugin install prereg@reproducible-science
```

The plugin ships instructions and hooks, not binaries, so install the tool as well:

```bash
uv tool install prereg        # or: pip install prereg
```

All four tools in one plugin, with every hook, skill and command:

```bash
/plugin install reproducible-science@reproducible-science
```

MIT licensed.

