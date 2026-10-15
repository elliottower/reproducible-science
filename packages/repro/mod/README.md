# repro

A Claude Code mod for research sessions. The `reproducible-science` plugin's hooks speak when a
number enters a manuscript unbound or a frozen plan changes, refuse an edit to a frozen plan, and
act only in a project that already keeps a ledger or a plan. This closes the other half: it works
in a project that keeps neither yet.

It is a plugin of function hooks. That API is early access and changes between Claude Code
releases, so this ships beside the `reproducible-science` plugin and not inside it: a build
that cannot load it still loads the plugin.

## What it does

| | |
|---|---|
| Refuses an edit to a frozen file | An `Edit` or `Write` to a file with a freeze record (`.prereg/<name>.json` beside it: a plan or an amendment), or to a `PREREG.md` carrying a freeze digest, is denied, with the instruction to record a note with `prereg log` or a change with `prereg amend`. The file is matched where it lands as well as by the name the edit gives: a symbolic link to a frozen plan, or `prereg.md` on a disk that ignores case, is refused too. A hard link to a frozen plan is not matched, because the mod's file interface reports no device or inode. An amendment still in draft has no record and is edited freely. |
| Notes a manuscript with no ledger | The first edit to a `.tex`, `.Rmd`, `.qmd` or `.typ` with no `.results/` ledger above it goes through, and the model is told no number in the file is bound to a run. |
| Notes an analysis with no ledger | The same, once per project, when a command runs an analysis. |
| Notes a downloaded source | After `curl` or `wget` saves a PDF, the model is told the address to record as `url:` in the claims file, so `citations fetch` can retrieve the same bytes for a reader. |
| Puts the gates in the system prompt | Seal before a run, claim before a number, freeze before a confirmatory analysis, with the state of the project's records as of the last turn. |
| Shows the state | One dim row above the prompt, refreshed at the end of each turn, with one field per tool and one for re-runs of the declared commands. |
| Warns | The pinned line under the prompt appears only when something is wrong, a few words per problem. |
| `/repro-status` | The same readout on demand, with the sealed files hashed. Instant, and no model turn. |
| `/repro-verify` | Checks every pinned quotation of the working project against its source, which takes minutes on a large project, and keeps the count for the readout. |
| `/repro-hide`, `/repro-show` | Hides the readout above the prompt, and shows it again. A warning still appears while it is hidden. |

## The status row

    study · prereg: 1/1 frozen · results: 3/3 runs sealed, 4 claims bound · citations: 120/120 quotes found · repro: 34/34 checks verified

Above the prompt each field is drawn on a row of its own. `prereg` is frozen plans over all plans, or `none drafted`.

`results` is the runs recorded after inputs were sealed, over all runs, then the claims
bound to a run with `results claim`. A run recorded before anything was sealed lowers
the first number: `2/3 runs sealed`. A run whose id begins `smoke_`, `prefreeze_`, `test_` or
`dryrun_` is a test run and is left out of the row, because it is recorded before a plan is
frozen and nothing may be claimed from it.

`citations` is the last full check by `/repro-verify`, and before one has run it is the count
pinned: `citations: 120 pinned, not verified`. Checking quotations takes minutes on a large
project, so the row never runs it. A check that does not finish in a minute marks its own field
`not read (timed out)` and leaves the others standing.

`repro` is the checks `claims verify` verified over all the manifest declares, one per assertion: the
claims alone, which is the fast check. The manifest is
the `repro.yaml` at the project's top or above it, which is the one `claims verify` reads without
being given a path. A manifest under another name or in a subfolder (`paper/repro.yaml`) is not
found, and a project with none reads `repro: no manifest`. Claims are counted on the `results`
row, where `results claim` makes them:

    repro: 56/56 checks verified
    repro: 55/56 checks verified
    repro: 6/6 checks verified, 1 broken pin

A pinned file that changed is named because the assertions read from it still verify, against a
file that is not the declared one. Where `claims verify` does not print a line for every
assertion and some did not verify, the field gives the tool's own words: `repro: 1 mismatch,
33 verified`. The check takes under a second on a manifest of
56 assertions, so it runs with the others at the end of each turn.

A manifest that declares commands under `regenerations` adds a second `repro` row, for the
re-runs of those commands that `repro reproduce` has recorded in `.repro/reproductions.jsonl`:

    repro: 7/7 reproduced, last 13 Oct
    repro: 5/7 reproduced, 2 stale since 13 Oct  →  repro reproduce
    repro: 0/7 reproduced  →  repro reproduce

The numbers count declared commands, not assertions. A command is reproduced where `repro stale`
calls it `current`: a recorded re-run that reproduced ran today's command over the files now on
disk, and the same holds for every command upstream. A command `repro stale` calls `stale` or
`undetermined` is counted under that word, and a command never re-run only lowers the first
number. The date is the day the latest of the re-runs compared against started, in the
machine's time zone, and `in CI` follows it where that re-run's entry carries a `witness`. The
row is read from `repro stale --format json`, which executes nothing and takes about as long as
`claims verify`, and it is not run for a manifest with no `regenerations`, which draws no row.
Neither does a record of re-runs with a line `repro stale` cannot read.

A row whose tool has a next step still to take names the command that takes it, directly after
the row:

    citations: none pinned  →  citations pin
    repro: no manifest  →  repro manifest init

`prereg: none drafted` points at `prereg new`, an unfrozen draft at `prereg freeze`, a missing
ledger at `results init`, a ledger with no runs at `results seal`, a manifest with no claims
at adding some, and declared commands not all reproduced at `repro reproduce`. A project with none of the four set up shows one hint, `repro init`, which
creates all four. A row with something to report carries no hint.

The warnings, each on the pinned line as `repro: ...`:

| | |
|---|---|
| `1 plan edited after freeze` | a frozen `PREREG.md` no longer matches its digest |
| `ledger truncated`, `edited`, `corrupt` | the chain does not verify |
| `ledger rewritten after timestamp` | a timestamp proof contradicts the chain |
| `2 sealed files changed` | after `/repro-status`, which hashes the sealed files |
| `16 runs, nothing sealed` | runs are recorded and no input was sealed |
| `3 runs, no plan frozen` | runs are recorded and no plan is frozen |
| `1 number mismatched` | a number in the manuscript disagrees with the artifact `repro.yaml` binds it to |
| `1 quotation mismatched` | the same, for a `quote` assertion |
| `2 claims mismatched` | the same, where the kind could not be read off `claims verify`'s lines |
| `1 quotation not found` | after `/repro-verify`: a pinned quotation is not in its source |
| `1 claim on test runs` | a manuscript number is bound to a run named as a test run |

An assertion or a quotation that is `unchecked`, and a claim offering no evidence, are counted
in the row and draw no warning.

## The working project

A session started in one folder often edits files in another, so the project is read off the
paths the tools touch: the nearest directory above a touched file that holds a `.results/`
ledger, a `claims/` directory, a `PREREG.md` or a `paper/` directory.

    /repro-status                  the working project's state
    /repro-status <part of a name> set the working project, among the folders beside the session's
    /repro-status pick             choose one from a list
    /repro-status list             print them
    /repro-status auto             go back to following the files

The model can set it too, through the `set_project` tool the mod registers.

## Install

    /plugin marketplace add elliottower/reproducible-science
    /plugin install repro@reproducible-science

It needs the `results`, `prereg` and `citations` commands on `PATH`, and `repro` for the fourth and fifth fields.

## Develop

    claude plugin validate packages/repro/mod
    claude plugin test packages/repro/mod

The tests stand in for the engine and need no network or account. The `mod tests` job of this
repository's CI installs the Claude Code pinned in `.github/mod-tests` and runs both commands.
