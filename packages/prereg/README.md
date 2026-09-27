# prereg

[![pypi](https://img.shields.io/pypi/v/prereg)](https://pypi.org/project/prereg/)
[![python](https://img.shields.io/pypi/pyversions/prereg)](https://pypi.org/project/prereg/)
[![license](https://img.shields.io/pypi/l/prereg)](https://github.com/elliottower/reproducible-science/blob/main/LICENSE)
[![docs](https://img.shields.io/badge/docs-live-blue)](https://elliottower.github.io/reproducible-science/)

Freeze a plan before you run it, and record what changed after.

Part of [reproducible-science](https://github.com/elliottower/reproducible-science) alongside `repro`, `citations` and `results` — see the [documentation](https://elliottower.github.io/reproducible-science/tools/prereg/).

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
| `prereg freeze --osf --attach PATH` | Also upload a file into the draft, so it is registered with the plan |
| `prereg register --embargo DATE` / `--immediate` | Submit the draft as an OSF registration |
| `prereg link [--anonymous]` | Create a view-only link on the registration |
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
OSF as a draft registration.

```bash
prereg freeze --osf --attach ../CONTEXT.md                  # freeze, push the draft, upload the file
prereg register --embargo 2027-06-01 --access "nothing run" # or --immediate
prereg link --anonymous --name "review" --access "results seen"
```

Four OSF questions are multiple choice: Foreknowledge of data or evidence, Study type, Intention
for causal interpretation, and Blinding of experimental treatments. OSF accepts only the listed
options there, so each line under those headings names one option, by its full text or by a
prefix no other option shares; `N/A` leaves the question unanswered. The push refuses a plan
that does not, before anything is frozen, and lists the options.

`--attach` uploads a file into the draft's storage, which OSF archives into the registration.
Use it for a file several plans point at, such as a shared `CONTEXT.md`. The log records each
file's sha256, and the push fails if OSF reports a different hash for what it received.

`register` submits the draft the log recorded at the freeze. It refuses a plan that has changed
since the freeze, a draft made from an earlier freeze, and a draft already registered. Choosing
between `--embargo` and `--immediate` is required: an immediate registration is public once it
is approved. OSF emails every admin, and the registration is approved after 48 hours unless one
of them cancels it. By OSF's defaults an embargo ends at least two days and at most four years
ahead. OSF also refuses a draft with no subject; add one on the draft's page first.

`link --anonymous` creates a view-only link that hides the contributors, for double-blind
review; without `--anonymous` the link shows them. The URL is printed. The log records the
link's id, not its key, because the key opens the registration while it is embargoed.

### What the log records

```text
2026-09-27  frozen at 9894e148e429                nothing run
2026-09-27  osf draft 64f1c2a9e4b0c1d2e3f4a5b6 of plan 35abc8ae2767bee4  nothing run
2026-09-27  osf attached CONTEXT.md sha256 c8e26e6c8064b9cb…  nothing run
2026-09-28  osf registration x7k2p from draft 64f1c2a9e4b0c1d2e3f4a5b6, embargo until 2027-06-01, https://osf.io/x7k2p/  nothing run
2027-03-02  osf view-only link 65a0b1c2d3e4f5a6b7c8d9e0 on x7k2p, anonymous  results seen
```

The attached file's sha256 is written in full; it is shortened here.

Each entry is appended through the same chained log as `prereg log`, so `prereg check` notices
one removed or edited. `register` and `link` take `--access`, because the command cannot know
what has been seen by the time it runs.

### Confirmation

Every write to OSF shows what it will send and asks for a phrase naming it: `push <digest>`,
`register <draft>`, `link <registration>`. The question is asked on the terminal (`/dev/tty`),
not stdin, so a piped answer does not count, and a process with no terminal is refused before
any request. No flag skips it.

This guards against an accidental or unattended write. It is not a security boundary: a
program can open a pseudo-terminal and type the phrase, and anything that can read the token
can call the API without `prereg`.

### The token

Create a token at [osf.io/settings/tokens](https://osf.io/settings/tokens) with the
`osf.full_write` scope. `prereg` reads `OSF_TOKEN` from the environment, or from a `.env` in
this directory or above. `prereg setup` writes it to `.env` and adds `.env` to `.gitignore`.

A token in a plain `.env` can be read by every process running as you, coding agents
included, and with it they can write to OSF directly. Keep it out of files: have a secret
manager inject `OSF_TOKEN` into the one command that needs it, with unlocking left to you.

```bash
op run --env-file=osf.env -- prereg register --embargo 2027-06-01 --access "nothing run"
```

### Changes after registering

`prereg` does not change a registration. Updates are made in OSF's web interface: an update
needs a written justification and goes to the registration's admins for approval, with a
48-hour window. OSF reserves updates for events outside the authors' control. Record what
changed, and why, with `prereg log` as well.

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

## This tool and `repro`

`prereg` installs and runs on its own, is not deprecated, and is not going to be.
`reproducible-science` depends on it, so `repro prereg ...` runs this same command with the
same arguments and the same exit code. That is a spelling, not a feature.

What only exists in the umbrella is `repro check`, which runs every tool a project uses in one
pass, with one report and one exit code, and names the tools the project does not use rather
than counting them as passing. If a project only preregisters, the umbrella adds nothing over this command at all.
