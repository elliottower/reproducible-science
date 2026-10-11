# The `prereg` Claude Code plugin

Is the plan still the plan that was registered?

Three surfaces, because each catches a different failure. The hooks catch what the model
does not think to do, the skill catches what the author did not know to ask for, and the
command is there for when you want the answer now.

| | |
|---|---|
| **hook** `hooks/frozen_file_before_edit.py` | fires before an `Edit`, `Write` or `MultiEdit` to a frozen plan or a frozen amendment, and refuses it |
| **hook** `hooks/frozen_plan_changed.py` | fires when a frozen plan or amendment no longer matches the digest it was frozen with |
| **skill** `skills/prereg/SKILL.md` | fires when Claude judges the tool relevant |
| **skill** `skills/prereg-style/SKILL.md` | fires when a plan is being drafted or revised |
| **skill** `skills/osf-registration/SKILL.md` | fires when a plan is going on OSF |
| **command** `/prereg-check` | fires when you type it |

## Why the hooks

`frozen_plan_changed.py` is the only exact check in the set. It recomputes a hash the author recorded and compares two strings, so there is no threshold and no judgment. It is also the one whose failure matters most: a plan rewritten around a result defeats registration entirely, and no reader can detect it afterward. The hook reports the difference and never edits the registration.

`frozen_file_before_edit.py` refuses the edit before it happens. An `Edit`, `Write` or `MultiEdit` to a file with a freeze record (`.prereg/<name>.json` beside it: a plan or an amendment), or to a plan carrying a freeze digest, is denied, with the instruction to record a note with `prereg log` or a change with `prereg amend`. An amendment still in draft has no record and is edited freely. `frozen_plan_changed.py` then reports a frozen file changed by another route, such as a shell command or an edit made outside the session.

The refusal is the only thing either hook blocks. Both exit zero on every failure path, which
allows the edit, and both stay silent in a project with no frozen plan — nothing to check means
nothing said.

## What the skills change

Claude freezes a plan before running rather than after seeing the outcome, and records a note in the log beside the plan and a change in an amendment file instead of editing the frozen plan.

| skill | what it is for |
|---|---|
| `prereg` | Freeze an experiment's plan against a commit and a content hash before running it, then record notes in a log beside it and changes in amendments. |
| `prereg-style` | One author's opinionated style for writing a preregistration, none of it required by the tool. |
| `osf-registration` | Register a frozen `prereg` plan on OSF. |

## Install

```bash
/plugin marketplace add elliottower/reproducible-science
/plugin install prereg@reproducible-science
```

The plugin ships instructions and hooks, not binaries. Install the tool as well:

```bash
uv tool install prereg
```

Against a checkout:

```bash
/plugin marketplace add ~/Documents/GitHub/reproducible-science
/plugin install prereg@reproducible-science
```

## The other three

`prereg`, `citations`, `results` and `repro` are one lifecycle, and each plugin ships
separately so you can take only what you use. `reproducible-science@reproducible-science`
installs all of them at once.
