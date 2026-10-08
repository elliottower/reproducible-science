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
# commit .prereg/ and the proof, run the experiment, then log what happened
prereg log "tolerance now derived from fixtures" --access "no results seen"
prereg check
```

```text
unchanged    V16_reliability_ceilings/PREREG.md  frozen 2026-10-06  nothing run
  timestamp  pending at 4 calendars. `prereg timestamp` completes it.
log          V16_reliability_ceilings/PREREG.log  1 entry, chain intact
```

## Commands

| Command | What it does |
|---------|-------------|
| `prereg new <name>` | Scaffold a plan in OSF's headings |
| `prereg freeze` | Record the file's hash, the commit and the time beside the plan, and set the plan read-only |
| `prereg freeze PREREG_AMENDMENT_N.md` | Freeze an amendment, the same way |
| `prereg freeze --allow-tracked-sources` | Freeze although git tracks a source the project's quotations are pinned to |
| `prereg freeze --osf` | Freeze and push as a draft registration to OSF |
| `prereg freeze --osf --attach PATH` | Also upload a file into the draft, so it is registered with the plan |
| `prereg register --embargo DATE` / `--immediate` | Submit the draft as an OSF registration |
| `prereg link [--anonymous]` | Create a view-only link on the registration |
| `prereg log <note>` | Append an entry to `PREREG.log`, beside the plan |
| `prereg amend [--parent FILE]` | Start `PREREG_AMENDMENT_N.md`, a change to the frozen plan |
| `prereg check` | Has any frozen file changed since its freeze? |
| `prereg check --staged` | Does the git index hold a change to a frozen file? For a pre-commit hook |
| `prereg timestamp` | Complete each freeze's outside timestamp and check it against Bitcoin |
| `prereg setup` | Save your OSF token to `.env` |

## Timestamp

A freeze is recorded in the repository, and whoever holds the repository can rewrite its
history. `prereg freeze` therefore always sends the file's digest to the
[OpenTimestamps](https://opentimestamps.org) calendars and keeps the proof beside the plan as
`PREREG.md.ots`. No account is needed, and only the digest leaves the machine. No flag skips
it.

The proof is pending until the calendars commit it into a Bitcoin block, usually within a few
hours. `prereg timestamp` then completes it and reports the block and its date, which is the
latest date the plan could have been written. Commit the proof with the plan.

```text
timestamped  V16_reliability_ceilings/PREREG.md
  Bitcoin block 915004, 2026-10-03 16:12 UTC
```

`prereg check` reports the proof without the network, and fails when the proof is of a different
digest than the freeze.

A freeze made with no network still succeeds. The timestamp is then owed: the freeze says so,
and `prereg check` says so on every run until `prereg timestamp` makes it.

```text
unchanged    V16_reliability_ceilings/PREREG.md  frozen 2026-10-06  nothing run
  timestamp  owed. `prereg timestamp` completes it.
```

An empty `PROVENANCE_CALENDARS` names no calendar, which is how a test suite stays off the
network. A freeze made under it owes its timestamp like any other.

## One rule

**A frozen file never changes by one byte. Anything later is a separate file.**

```text
V16_reliability_ceilings/
    PREREG.md                 the plan. Frozen once, never written to again.
    PREREG.log                short dated entries. Append-only.
    PREREG.log.head           the log's length and last entry, rewritten by each `prereg log`
    PREREG_AMENDMENT_1.md     an amendment. Frozen once, never written to again.
    .prereg/                  one freeze record per frozen file
        PREREG.md.json
        PREREG_AMENDMENT_1.md.json
    PREREG.md.ots             the timestamp proof of each frozen file
    PREREG_AMENDMENT_1.md.ots
    .gitattributes            `-text` rules, so no checkout converts a frozen file's line endings
    tests/  results/
```

Commit all of it. A freeze is evidence once its record is in history.

## Freezing

`prereg freeze` refuses a plan with uncommitted changes, because the freeze names a commit. It
then:

1. takes one sha256 over the whole file;
2. writes the record to `.prereg/PREREG.md.json`: the digest, the commit, the time in UTC, and
   the access level;
3. sets the plan read-only;
4. adds `-text` rules for the plan, its amendments and its log to the nearest `.gitattributes`
   at or above the plan, or to a new one beside it, leaving the lines already there as they are;
5. sends the digest to the OpenTimestamps calendars.

The access level is `nothing run` unless `--access` says otherwise or a results ledger shows
more: with a ledger at or above the plan, the level defaults to the ledger's floor and
`--access` can raise it and cannot lower it (see [Amending a frozen plan](#amending-a-frozen-plan)
for how the floor is read).

A file frozen whole is hashed byte for byte, and a checkout with `core.autocrlf` on rewrites the
line endings of a text file. The `-text` rules stop git converting these files, so the same
bytes arrive on every machine.

Nothing is written into the plan. A second `prereg freeze` is refused, with or without
`--force`: a change to a frozen plan is an amendment.

```json
{
  "file": "PREREG.md",
  "sha256": "35abc8ae2767bee40600e37a5032b1536a8799fea672bdc323f6c317176dd966",
  "commit": "9894e148e4291c0b5f0d1a7a3c1f2b6e8d7a9c01",
  "frozen_at": "2026-10-06T14:03:11+00:00",
  "access": "nothing run",
  "parent": null
}
```

### A pinned source that git tracks

A freeze names a commit, and a source text in that commit can only be removed later by
rewriting history, which changes the commit's identifier. So where `citations` is installed, a
freeze first runs `citations lint --claims --json` beside the plan, and where git tracks a
source the project's claims files pin, it is refused before anything is written. There is no
record, no log entry and no timestamp request, and the exit code is 1:

```text
study/PREREG.md was not frozen, and nothing was written.
git tracks 1 source this project's quotations are pinned to
  tracked  study/sources/woodward.txt
A freeze names a commit, and a source in that commit can only be removed later by
rewriting history, which changes the commit's identifier. Untrack each with
`git rm --cached <file>`, add an ignore rule, commit, and freeze again: the record's
sha256 still pins the file. Or keep them and freeze with --allow-tracked-sources.
```

It names ten sources at most and then counts the rest. `--allow-tracked-sources` is for text
that is the author's to commit: the freeze goes ahead, and the sources are named after its
report. The same holds for an amendment and for a forced re-freeze of a plan frozen in place.

Only an answer refuses. With no `citations` on `PATH`, a version of it that cannot be asked
this way, no claims directory, or nothing tracked, the freeze goes ahead and says nothing.

## The log

`prereg log` writes one entry to `PREREG.log`: the time, the note, and what had been seen.

```text
2026-08-13T09:12:40+00:00  tolerance now from fixtures           no results seen  ·35abc8ae…
2026-08-14T17:03:02+00:00  ran                                   results not opened  ·9f0613…
2026-08-15T08:44:19+00:00  C5 failed at k=15: 6.6% vs 5%         results seen  ·c8e26e…
```

The access level is one of `nothing run`, `no results seen`, `results not opened`, `results
seen`. The last field chains the entries, and is shortened here: the first carries the plan's
sha256, and each later entry carries the sha256 of the entry before it. Removing or rewording an entry breaks
every entry after it, and `prereg check` reports the log as altered.

A chain cannot see an entry removed from its end, because the entries that remain still follow
one another. `PREREG.log.head` is the witness to the length: it holds the number of entries and
the sha256 of the last, and each `prereg log` rewrites it. `prereg check` reports a log shorter
than its anchor as altered, and `prereg log` refuses to append to one. The anchor is not a
frozen file. Someone who removes the last entry and edits the anchor to match leaves a log and
an anchor that verify, and `prereg check` passes on that working tree. `prereg check --staged`
refuses the pair when a longer log is already committed, and the commit history is what shows
the removed entry afterwards.

The log is for bookkeeping and small deviations. A new hypothesis, criterion or experiment is
an amendment.

## Amending a frozen plan

`prereg amend` creates `PREREG_AMENDMENT_N.md` beside the plan, with four required fields:

- **Amends**: the plan or amendment it amends, by sha256 digest. `prereg amend` names the plan;
  `prereg amend --parent PREREG_AMENDMENT_1.md` names an amendment.
- **Sections replaced or added.**
- **Reason.**
- **What had been seen**: an access level, and what had been run and read.

Where a [results](https://elliottower.github.io/reproducible-science/tools/results/) ledger
sits at or above the plan (`.results/ledger.jsonl`), the access level is filled from the
ledger's floor, with the highest level it records and the number of runs recorded so far. The
floor is the highest access level ever recorded there, mapped onto the four levels here:

| the ledger records | the amendment starts at |
|---|---|
| `nothing seen` | `nothing run` |
| `metadata only` | `no results seen` |
| `structure seen` | `no results seen` |
| `outcomes seen` | `results seen` |

One or more recorded runs put the floor at `results not opened` or above, whatever access was
recorded. The author can raise the level. `prereg freeze` refuses an amendment that states a
lower level than the floor, and one with a field left unfilled; a plan's own freeze has the same
floor. The ledger is read whole, so one ledger at the top of a repository sets the floor for
every plan and amendment in it, including a plan for an experiment none of its runs belong to.

```bash
prereg amend
# fill in the four fields, commit the file
prereg freeze PREREG_AMENDMENT_1.md
```

An amendment is frozen as a plan is: one digest over the whole file, the commit, the time, the
outside timestamp, read-only. Its date is the time of its freeze, whatever its prose says. An
amendment frozen after results were seen is allowed, and `prereg check` labels it.

## Check output

`prereg check` reports the plan, then its amendments in order of freeze time, then the log:

```text
unchanged    PREREG.md  frozen 2026-07-08  nothing run
  timestamp  Bitcoin block 915004. `prereg timestamp` checks the block.
unchanged    PREREG_AMENDMENT_1.md  frozen 2026-07-08  nothing run
  amends     PREREG.md
  timestamp  Bitcoin block 915004. `prereg timestamp` checks the block.
unchanged    PREREG_AMENDMENT_2.md  frozen 2026-09-11  results seen
  amends     PREREG_AMENDMENT_1.md
  written after results were seen
  timestamp  pending at 4 calendars. `prereg timestamp` completes it.
log          PREREG.log  4 entries, chain intact
```

| Exit | Result | Meaning |
|------|--------|---------|
| 0 | `unchanged` | The file is byte for byte what was frozen |
| 1 | `CHANGED` | A frozen file differs from its freeze by at least one byte |
| 1 | `MISSING` | A file was frozen and is gone |
| 1 | `orphaned` | An amendment's parent digest matches no frozen file present |
| 1 | `LOG ALTERED` | The log's chain does not verify, or the log is shorter than its anchor records |
| 2 | `not frozen` | No freeze recorded for the plan, or for an amendment still in draft |

`not frozen` is not a pass. It is the absence of a check. A timestamp that is owed or pending
is reported and does not change the exit code.

### A pre-commit hook

A file on the author's disk can be changed by anyone who removes the read-only flag, and git
does not carry that flag to another machine. `prereg check --staged` exits 1 when the git index
holds a change to a frozen file, an amendment or a committed freeze record, a log that no longer
begins with its committed entries, or a log anchor whose count went down, and names each path. `prereg` installs no hook. To have git refuse such a commit, put this in
`.git/hooks/pre-commit` and make it executable:

```sh
#!/bin/sh
exec prereg check --staged
```

### Plans frozen by an earlier version

Before this rule, `prereg freeze` wrote the freeze into the plan, as `**Status:** FROZEN at`,
`**Plan sha256:**` and `**Frozen:**` lines, and `prereg log` appended to a `## Log` section
under a `---` line in the same file. Such a plan is not converted, and every command reads it
under the rule it was frozen by:

- `prereg check` hashes the plan above the log line, leaves the status lines out, and verifies
  the log's chain and its `**Log:**` count, as it did. `CHANGED`, `UNCOVERED` and `LOG ALTERED`
  exit 1.
- `prereg log` appends in the file, and prints one line saying that plans frozen from now on
  keep their log beside them.
- `prereg timestamp`, `prereg register` and `prereg link` work on it unchanged, and
  `prereg freeze --force --access LEVEL` re-freezes it in the file.
- `prereg amend` amends it, naming the `**Plan sha256:**` digest. The amendment is frozen whole.
- `prereg check --staged` refuses a staged change above its log line and allows a log entry.

A project holding plans of both kinds, and registrations frozen by a commit line, reports each
under its own rule.

### Registrations frozen by a commit line

A registration can also be fixed without `prereg freeze`: the document is committed, and the
commit that follows writes the first commit's SHA into the document.

```text
# Does the rule hold?

**Commit SHA:** b96d10a
```

`prereg check` finds every markdown file git tracks at or below the working directory that
carries such a line, and compares it with the file at the commit the line names, leaving the
commit line out of both sides. The line is bold and starts a line, `**Commit SHA:**`,
`**Freeze SHA:**` or `**Freeze commit:**`, or the commit sits on the first line under a heading
of one of those names. The hash is 7 to 40 digits, bare, in backticks or in bold. A bold
`**Status:**` line before the first heading after the title is part of the freeze record too:
it is left out of the comparison, and a status that differs from the frozen one is reported
under the document without counting as an edit. These
documents are listed under their own heading, after the plans:

```text
registrations frozen by a commit line:
unchanged    PREREGISTRATION_AMENDMENT_2.md  at 12ea0ed
appended     PREREGISTRATION_AMENDMENT_5.md  at fbc7d33
  8 lines added after the frozen text
CHANGED      PREREGISTRATION.md  at b96d10a
  24 lines added, 4 removed
  first difference at line 107:
  - | Anti-CD20/MS | Per allele (FCRL3) | Yes |
  + | Anti-CD20/MS | Per SD circulating FCRL3 | No |
pending      PREREGISTRATION_AMENDMENT_3.md
  the commit line names no commit: _pending_

4 commit-pinned: 1 unchanged, 1 appended, 1 changed, 1 pending, 0 unknown commit
```

| Exit | Result | Meaning |
|------|--------|---------|
| 0 | `unchanged` | The document equals the file at its commit, apart from the commit line |
| 0 | `appended` | Lines were added after the end of the frozen text, or at the end of the fenced log that closes it |
| 1 | `CHANGED` | Frozen text was edited or removed, or lines were added inside it |
| 2 | `pending` | The commit line holds a placeholder, so there is nothing to compare with |
| 2 | `unknown commit` | The repository does not hold the named commit, or the file is not in it |

`pending` and `unknown commit` are not passes. A shallow clone, a rewritten history and a commit
of another repository all read as `unknown commit`, and none of them says the document changed.
A changed plan or document exits 1 whatever else was found. `prereg check` reads these documents
and never writes to them, and `prereg freeze` does not produce them.

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
prereg freeze --osf --attach ../CONTEXT.md \
  --subject "Artificial Intelligence and Robotics" \
  --description "What the study compares." --tag "AI incidents" \
  --category hypothesis --copyright-holder "A. Author" \
  --title-prefix "EXPT01: "                                  # freeze, push the draft, fill its metadata
prereg register --embargo 2027-06-01 --access "nothing run" # or --immediate
prereg register --all --immediate --access "nothing run"     # every frozen plan below, one phrase
prereg link --anonymous --name "review" --access "results seen"
```

`freeze --osf` needs no one at the terminal. A draft is private to its author and can be deleted
on OSF, so pushing one, uploading its files and filling its Metadata page runs unattended; an
agent can prepare every draft of a study. What cannot be undone -- `register` and `link` -- asks
for a typed phrase.

The flags fill OSF's Metadata page: `--subject` (repeatable, OSF's subject names in full;
OSF refuses to register a draft with none, and the push warns when none is given), `--description`,
`--tag` (repeatable), `--category` (one of OSF's project categories), and `--copyright-holder`
(repeatable), which sets the license, CC-BY 4.0 by default or `--license NAME`, with the current
year. `--title-prefix` goes before the plan's own title, so five drafts read `EXPT01: …` through
`EXPT05: …` on OSF. A subject, license or category OSF does not have is refused before anything
is frozen.

Four OSF questions are multiple choice: Foreknowledge of data or evidence, Study type, Intention
for causal interpretation, and Blinding of experimental treatments. OSF accepts only the listed
options there, so each line under those headings names one option, by its full text or by a
prefix no other option shares; `N/A` leaves the question unanswered. The push refuses a plan
that does not, before anything is frozen, and lists the options.

`--attach` uploads a file into the draft's storage, which OSF archives into the registration.
Use it for a file several plans point at, such as a shared `CONTEXT.md`. The log records each
file's sha256, and the push fails if OSF reports a different hash for what it received.

Nothing here writes into the plan: the draft, the attachments, the registration and the link are
entries in `PREREG.log`. A plan frozen without `--osf`, or whose push failed, is pushed with
`prereg freeze --osf --access LEVEL`, which makes the draft from the frozen file and leaves the
freeze as it is.

`register` submits the draft the log recorded. It refuses a plan that has changed since the
freeze, a draft made from an earlier freeze of a plan frozen in place, and a draft already
registered. With
`--all`, or run from a directory no plan governs, it registers every frozen plan below after one
phrase that names the list: every plan is checked first, one that cannot be registered stops
the batch before anyone is asked, and a plan already registered is skipped, so an interrupted
batch can be run again.

A failed request is not taken as a failed registration. OSF has answered 502 while creating the
registration, and a retry then got 403 because the draft was already registered. After an error
other than a 400, `register` reads OSF's list of registrations for one with the draft's title
made since the request, and retries only if there is none; a registration found that way is
logged with `found after OSF error 502`. Choosing
between `--embargo` and `--immediate` is required: an immediate registration is public once it
is approved. OSF emails every admin, and the registration is approved after 48 hours unless one
of them cancels it. By OSF's defaults an embargo ends at least two days and at most four years
ahead. OSF also refuses a draft with no subject; add one on the draft's page first.

`link --anonymous` creates a view-only link that hides the contributors, for double-blind
review; without `--anonymous` the link shows them. The URL is printed. The log records the
link's id, not its key, because the key opens the registration while it is embargoed.

### What the log records

```text
2026-09-27T10:02:11+00:00  osf draft 64f1c2a9e4b0c1d2e3f4a5b6 of plan 35abc8ae2767bee4  nothing run
2026-09-27T10:02:14+00:00  osf attached CONTEXT.md sha256 c8e26e6c8064b9cb…  nothing run
2026-09-28T08:40:53+00:00  osf registration x7k2p from draft 64f1c2a9e4b0c1d2e3f4a5b6, embargo until 2027-06-01, https://osf.io/x7k2p/  nothing run
2027-03-02T15:21:07+00:00  osf view-only link 65a0b1c2d3e4f5a6b7c8d9e0 on x7k2p, anonymous  results seen
```

The attached file's sha256 is written in full; it is shortened here, and each entry's chain
value is left off.

Each entry is appended through the same chained log as `prereg log`, so `prereg check` notices
one removed or edited. `register` and `link` take `--access`, because the command cannot know
what has been seen by the time it runs.

### Who must be present

Every write to OSF that cannot be undone — registering, creating a link — shows what it will
send and asks for a phrase naming it: `register <draft>`, `register 5 plans <digest>`,
`link <registration>`. Pushing a draft does not ask. The phrase is read from the terminal (`/dev/tty`), never stdin, so a
piped answer does not count, and a process with no terminal is refused before any request. No
flag or variable skips it.

This is a guard against accidents, not a security boundary. An agent that wants to write to
OSF has to go out of its way, for instance by faking a terminal, and that is not
insurmountable. Anything that can read `OSF_TOKEN` can also call OSF without `prereg` at all.

The barrier that holds is the token. Keep it in a secret source that asks for approval each
time it is read, such as a 1Password-managed `.env`, which is a named pipe: every OSF
interaction then needs Touch ID or the account password first. `prereg` reads such a pipe
directly, only when a request is about to be made and after the phrase is typed, and gives up
after 60 seconds if nothing is delivered.

### The token

Create a token at [osf.io/settings/tokens](https://osf.io/settings/tokens) with the
`osf.full_write` scope. `prereg` reads `OSF_TOKEN`, or `OSF_PAT`, from the environment, or from a `.env`
in this directory or above, whether a regular file or a named pipe. `prereg setup` writes it to a
plain `.env` and adds `.env` to `.gitignore`; a plain file can be read by every process running
as you, coding agents included.

### Changes after registering

`prereg` does not change a registration. Updates are made in OSF's web interface: an update
needs a written justification and goes to the registration's admins for approval, with a
48-hour window. OSF reserves updates for events outside the authors' control. Record what
changed, and why, here as well: a change to the plan with `prereg amend`, a note with
`prereg log`.

## What a freeze is

A commit, a hash of the whole file, and a timestamp held outside the repository. The commit is
in history and dated. The hash lets `prereg check` tell you in a second whether the plan is byte
for byte what was frozen. The timestamp and an OSF registration hold a copy of the digest that
the author cannot alter, which is what makes a deliberate change detectable; read-only on disk
and the pre-commit hook prevent an accidental one. A frozen file and its record in `.prereg/`
edited together pass `prereg check` on that working tree: the staged check, the commit history,
the timestamp and the registration are what show it.

Neither proves you did not run the experiment first. Nothing can: a timestamp bounds when
something existed, never when work began.

## Claude Code

`plugin/` is a Claude Code plugin. Three surfaces, because each catches a different failure:
the hook catches what the model does not think to do, the skill catches what you did not know
to ask for, and the command is there for when you want the answer now.

| surface | fires |
|---|---|
| hook | when a frozen plan or amendment no longer matches the digest it was frozen with |
| skill | when Claude judges the situation calls for freezing a plan before a run, and recording what changed after |
| command | when you type `/prereg-check` |

**Why the hook.** This is the only exact check in the set. It recomputes a hash you recorded and compares two strings, so there is no threshold and no judgment. A plan rewritten around a result defeats registration entirely and no reader can detect it afterward, so the hook reports the difference and never edits the registration.

It reports and never blocks, and stays silent in a project with no frozen plan. It reads the freeze record beside a file frozen whole, and the digest a plan frozen in place carries.

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
