# reproducible-science-ui

A local web page over a project's [Reproducible Science](https://reproducible.science) records:
the claims a manuscript makes and whether each still holds, the files each claim reads, the runs
that wrote them, the quotations pinned from cited sources, and the rebuild steps with their
re-runs.

```sh
pip install "reproducible-science[ui]"
repro ui                 # in a folder holding repro.yaml; opens http://localhost:5190/
```

`repro ui` builds the page's data from what `repro verify`, `repro stale`, `prereg check` and
`results verify` report, and from the project's ledger, check history, record of re-runs,
manifest and manuscript, then serves it on localhost only.

| Tab | What it shows |
|---|---|
| Overview | the status of the plan, the ledger, the quotations, the claims and the re-runs |
| Prereg | what `prereg check` reports for each plan |
| Results | each run, the files it wrote, whether they still hold those bytes, the outside records linked to them, and the claims that read them |
| Citations | each source, its pinned quotations, the reading the paper takes of them, and the sentences that cite it, by section |
| Claims | every claim with its check history |
| Reproduce | each rebuild step, what changed since its last re-run, and every re-run |
| Graph | the files and runs behind each claim, as a lineage graph grouped automatically |

## What it writes

- **Refresh** re-reads the records and writes nothing to the project.
- **repro verify** checks every claim again, which adds one line to the project's local check
  history, kept inside `.git` and never committed. It asks first.
- **Reproduce** runs the rebuild steps you choose with `repro reproduce`, which executes the
  commands `repro.yaml` declares and adds the re-run to `.repro/reproductions.jsonl`. It lists
  each command before anything runs.
- **Fix with Claude Code**, on a failing or stale count, appends a request to
  `~/.claude/repro-fixes/queue.jsonl`, which the `repro` Claude Code mod shows above the prompt
  of a session working in the project. Nothing runs until it is loaded and sent. **Copy prompt
  to fix** puts the same prompt on the clipboard, for any other agent.

The page's own data and caches are kept inside the project's git directory
(`.git/repro/ui/`), or under `~/.cache/reproducible-science-ui/` for a project outside git.

## Options

```sh
repro ui [project] [--port 5190] [--offline] [--no-browser] [--groups groups.yaml]
```

`--offline` looks up no DOI: by default the publisher's landing page of each DOI a source names
is looked up once and cached, so the page can link to it. `--groups` takes a YAML list of
`{group, match}`, putting each file whose id matches the pattern into that group of the graph.

## Development

The page is a Vite project in `web/`. Its build goes into `src/repro_ui/static/`, which is not
in git; the build hook makes it with npm whenever a wheel or an sdist is built.

```sh
cd web && npm ci && npm run build       # or: npm run dev
```
