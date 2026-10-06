# repro

A Claude Code mod for research sessions. The `reproducible-science` plugin's hooks speak when a
number enters a manuscript unbound or a frozen plan changes, and they speak only in a project
that already keeps a ledger or a plan. This closes the other half: it works in a project that
keeps neither yet, and it can refuse.

It is a plugin of function hooks. That API is early access and changes between Claude Code
releases, so this ships beside the `reproducible-science` plugin and not inside it: a build
that cannot load it still loads the plugin.

## What it does

| | |
|---|---|
| Refuses an edit to a frozen plan | An `Edit` or `Write` to a `PREREG.md` carrying a freeze digest is denied, with the instruction to record the change with `prereg log`. |
| Notes a manuscript with no ledger | The first edit to a `.tex`, `.Rmd`, `.qmd` or `.typ` with no `.results/` ledger above it goes through, and the model is told no number in the file is bound to a run. |
| Notes an analysis with no ledger | The same, once per project, when a command runs an analysis. |
| Notes a downloaded source | After `curl` or `wget` saves a PDF, the model is told the address to record as `url:` in the claims file, so `citations fetch` can retrieve the same bytes for a reader. |
| Puts the gates in the system prompt | Seal before a run, claim before a number, freeze before a confirmatory analysis, with the state of the project's records as of the last turn. |
| Shows the state | One dim row above the prompt, refreshed at the end of each turn, with one field per tool. |
| Warns | The pinned line under the prompt appears only when something is wrong, a few words per problem. |
| `/repro-status` | The same readout on demand, with the sealed files hashed. Instant, and no model turn. |
| `/repro-verify` | Checks every pinned quotation of the working project against its source, which takes minutes on a large project, and keeps the count for the readout. |
| `/repro-hide`, `/repro-show` | Hides the readout above the prompt, and shows it again. A warning still appears while it is hidden. |

## The status row

    study · prereg: 1/1 frozen · results: 3/3 runs sealed, 4 numbers bound · citations: 120/120 quotes found · repro: 17/17 claims verified

Above the prompt each field is drawn on a row of its own. `prereg` is frozen plans over all plans, or `none drafted`.

`results` is the runs recorded after inputs were sealed, over all runs, then the manuscript
numbers bound to a run with `results claim`. A run recorded before anything was sealed lowers
the first number: `2/3 runs sealed`. A run whose id begins `smoke_`, `prefreeze_`, `test_` or
`dryrun_` is a test run and is left out of the row, because it is recorded before a plan is
frozen and nothing may be claimed from it.

`citations` is the last full check by `/repro-verify`, and before one has run it is the count
pinned: `citations: 120 pinned, not verified`. Checking quotations takes minutes on a large
project, so the row never runs it. A check that does not finish in a minute marks its own field
`not read (timed out)` and leaves the others standing.

`repro` is the claims `repro verify` verified over all the manifest declares. The manifest is
the `repro.yaml` at the project's top or above it, which is the one `repro verify` reads without
being given a path. A manifest under another name or in a subfolder (`paper/repro.yaml`) is not
found, and a project with none reads `repro: no manifest`. A claim carries one or more assertions and is
verified when every one of them is:

    repro: 28/28 claims verified
    repro: 27/28 claims verified
    repro: 3/3 claims verified, 1 broken pin

A pinned file that changed is named because the assertions read from it still verify, against a
file that is not the declared one. Where `repro verify` does not print a line for every
assertion, the field counts assertions under the tool's own words: `repro: 34/34 checks
verified`, or `repro: 1 mismatch, 33 verified`. The check takes under a second on a manifest of
56 assertions, so it runs with the others at the end of each turn.

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
| `2 claims mismatched` | the same, where the kind could not be read off `repro verify`'s lines |
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

It needs the `results`, `prereg` and `citations` commands on `PATH`, and `repro` for the fourth field.

## Develop

    claude plugin validate packages/repro/mod
    claude plugin test packages/repro/mod

The tests stand in for the engine and need no network. They do not run in this repository's
CI, which has no Claude Code.
