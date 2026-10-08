---
name: prereg
description: Freeze an experiment's plan against a commit and a content hash before running it, then record notes in a log beside it and changes in amendments. Use when writing or freezing a PREREG.md, before launching a run a plan governs, when a frozen plan needs to change, or when asked whether a plan still says what it said. Requires the `prereg` CLI (`uv tool install prereg`).
---

# prereg

A plan, frozen whole against a commit and a hash and never written to again, an append-only log
beside it, and an amendment file for each change to it.

## The rule that matters

**Freeze before you look. A frozen file never changes by one byte.**

A pre-registration is worth exactly one thing: evidence that the predictions existed before the
data did. Every way it fails is a version of the plan moving after the numbers were seen — a
threshold nudged, a hypothesis dropped, a subgroup added. So `prereg freeze` hashes the whole
file, records the freeze outside it in `.prereg/`, and sets the file read-only. Anything later
is a separate file: a note in `PREREG.log`, a change in `PREREG_AMENDMENT_N.md`.

Never edit a frozen plan or a frozen amendment, never remove its read-only flag, and never write
or edit a record under `.prereg/` by hand. A record is the tool's output.

## Commands

```bash
prereg new <name>      # scaffold PREREG.md in OSF's headings, plus tests/ and results/
prereg freeze          # hash the whole file, record it in .prereg/, set the plan read-only
prereg freeze --allow-tracked-sources   # freeze although git tracks a pinned source
prereg freeze --osf    # freeze and push as a draft registration to OSF (unattended)
prereg freeze --osf --attach ../CONTEXT.md --subject "<OSF subject>" \
  --description "<text>" --tag <tag> --category hypothesis \
  --copyright-holder "<name>" --title-prefix "EXPT01: "   # files and Metadata page too
prereg register --embargo YYYY-MM-DD --access <level>   # or --immediate; irreversible
prereg register --all --immediate --access <level>      # every frozen plan below, one phrase
prereg link --anonymous --access <level>     # view-only link for double-blind review
prereg setup           # save OSF token to .env (once)
prereg log <note> --access <level>   # one entry in PREREG.log, beside the plan
prereg amend           # start PREREG_AMENDMENT_N.md: a change to the frozen plan
prereg freeze PREREG_AMENDMENT_N.md  # freeze the amendment, as a plan is frozen
prereg check           # has any frozen file changed since its freeze?
prereg check --staged  # does the git index hold a change to a frozen file? (pre-commit hook)
prereg timestamp       # complete each freeze's outside timestamp
```

### Who must be present

A draft push needs nobody: `freeze --osf` creates the draft, uploads the attached files and fills
its Metadata page (subjects, description, tags, category, license, title prefix) unattended. A
draft is private and deletable. Do this part yourself, for every plan in the study.

`register` and `link` cannot be undone and ask for a typed phrase on the terminal. Do not try to
answer it, and do not call the OSF API to get around it: give the person one command, usually
`prereg register --all --immediate --access "nothing run"` from the directory above the plans,
which registers every frozen plan after a single phrase. Before handing it over, check each draft
has a subject; OSF refuses to register one without. The token is read as `OSF_TOKEN` or
`OSF_PAT`. The phrase guards against accidents; it is not a security boundary, because
anything that can read `OSF_TOKEN` can call OSF directly. The real gate is a token kept in a
secret source that requires approval at read time, such as a 1Password-managed `.env` (a named
pipe), where every OSF interaction first needs Touch ID or the account password. `prereg` reads
such a pipe directly.

## Freezing, in order

1. **Write the plan, then get it reviewed.** A plan frozen without review registers the author's
   guesses, not an agreed design.
2. **Commit the PREREG.md alone.** No code in that commit. A freeze whose commit also carries a
   code change cannot distinguish the registered design from the change made while registering it.
3. **`prereg freeze`** in the experiment directory. It refuses on a dirty tree, because the freeze
   names a commit. It always sends the digest to the OpenTimestamps calendars; with no network
   the freeze still succeeds and the timestamp is owed until `prereg timestamp` makes it. With
   a results ledger at or above the plan, the access level recorded is at least what the ledger
   shows: its highest recorded level, and `results not opened` once any run is recorded.
   Where `citations` is installed and git holds a source the project's claims files pin, the
   freeze is refused with exit 1 before anything is written: no record, no log entry, no
   timestamp request, no file of any kind. A source in the commit a freeze names can only be
   removed later by rewriting history, which changes that commit's identifier. The refusal
   lists each source as `tracked`, `staged`, or `in HEAD`. For the first two, untrack with
   `git rm --cached`, add an ignore rule, and commit. `in HEAD` is a source already untracked
   whose removal is not committed: the last commit still holds it, so commit the removal. Then
   freeze again. Pass `--allow-tracked-sources` only where the person has said the sources are
   theirs to commit; the freeze then goes ahead and names them. Never add the flag to get past
   the refusal.
4. **Commit `.prereg/`, `.gitattributes` and the `.ots` proof.** The freeze is only evidence once it is in history.
5. **Then run.** Not before step 4.

## Reading `prereg check`

It lists the plan, then its amendments by freeze time, then the log. Each frozen file's line
gives its freeze date and the access level recorded at its freeze.

| exit | | |
|---|---|---|
| 0 | `unchanged` | the file is byte for byte what was frozen |
| 1 | `CHANGED` | a frozen file differs from its freeze |
| 1 | `MISSING` | a file was frozen and is gone |
| 1 | `orphaned` | an amendment's parent digest matches no frozen file present |
| 1 | `LOG ALTERED` | the log's chain does not verify |
| 2 | `not frozen` | no freeze recorded — **nothing was measured** |

**`not frozen` is not a pass.** It is the absence of a check, and it reads identically to success
if you only look at whether the command complained.

**`CHANGED` is not fixed by freezing again.** A frozen file cannot be frozen a second time.
Restore the file from git, and record the change as an amendment with an honest access level.

`timestamp  owed` under a file means the freeze reached no calendar. It does not fail the check;
say so, and that `prereg timestamp` completes it.

At a repository root with no governing plan, `check` checks every plan below it.

## Notes, and changes to the plan

`prereg log <note> --access <level>` is for bookkeeping and small deviations. Never edit
`PREREG.log` or its anchor `PREREG.log.head` by hand: `check` reports a shortened or reworded log. `--access` is one
of `nothing run`, `no results seen`, `results not opened`, `results seen`. Log the honest level
even when it is the damaging one — that is the entire function of the field.

A new hypothesis, criterion or experiment is an amendment, not a log entry. `prereg amend`
creates `PREREG_AMENDMENT_N.md` with four required fields: what it amends, by digest; the
sections replaced or added; the reason; and what had been seen. Where a results ledger exists,
the access level is filled from it and cannot be lowered. Fill the file in, commit it, and
`prereg freeze PREREG_AMENDMENT_N.md`. An amendment frozen after results is allowed, and `check`
labels it.

## When to reach for this

- Before launching any run whose result will be reported as confirmatory
- When a plan is ready to freeze, after review
- When a frozen plan has to change — `prereg amend`, never an edit to the frozen file
- Before reporting a result a plan governs, to confirm the plan still says what it said
- In CI, as `prereg check`; in a pre-commit hook, as `prereg check --staged`

## Non-obvious behavior

- A plan frozen by an earlier version carries its freeze in the file (`**Status:** FROZEN`,
  `**Plan sha256:**`) and its log under a `## Log` line. It is not converted: `check` and `log`
  treat it as they did, `log` appends in the file, and `freeze --force` re-freezes it there.
  Never write those lines by hand.
- A draft made by an earlier `prereg new` carries a `**Status:** DRAFT` line and a `## Log`
  section. `freeze` refuses it until both are removed, because they would stay in the frozen
  file for good.
- `prereg log` is refused on a plan not yet frozen: the log's first entry carries the frozen
  plan's digest.

## What it will not do

It cannot prove you did not run the experiment first. Nothing can: a timestamp bounds when
something existed, never when the work began. It also cannot tell you the plan was any good — a
frozen bad design is still a bad design, registered.

## Where this sits

Four tools guard four moments, and each is weak without the others. A frozen plan over
unsealed inputs proves nothing; a sealed run whose numbers never reach the manuscript proves
nothing either.

| moment | tool | what it fixes |
|---|---|---|
| before you run | `prereg freeze` | the plan cannot be rewritten around the result |
| before you compute | `results seal` | the inputs are what you say they were |
| after a run | `results run` | the outputs are recorded and hashed |
| writing a number | `results claim` | the number names the run behind it |
| writing a quotation | a `claims/` entry | the passage is in the source |
| before submitting | `prereg check`, `results verify`, `citations verify` | nothing drifted |

Every tool named here is installed by `uv tool install reproducible-science`, so the commands
above are available whatever plugins are present.

Each tool also ships its own plugin, adding a hook that speaks when its moment passes
unrecorded and a `-check` command. Those commands exist only where the matching plugin is
installed; the CLI calls in the table always work.
