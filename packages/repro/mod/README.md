# repro-gates

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
| Shows the state | In the status line, refreshed at the end of each turn. |
| `/repro-status` | The same readout on demand, with the sealed files hashed and the quotations counted. No model turn. |

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
    /plugin install repro-gates@reproducible-science

It needs the `results`, `prereg` and `citations` commands on `PATH`.

## Develop

    claude plugin validate packages/repro/mod
    claude plugin test packages/repro/mod

The tests stand in for the engine and need no network. They do not run in this repository's
CI, which has no Claude Code.
