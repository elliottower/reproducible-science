---
title: Web UI
description: A local web page over a project's records, served by repro ui.
---

`repro ui` serves a local web page over a project's records: the claims a manuscript makes and
whether each still holds, the files each claim reads, the runs that wrote them, the quotations
pinned from cited sources, and the rebuild steps with their re-runs. It ships in 0.7.0.

```bash
pip install "reproducible-science[ui]"
repro ui                 # in a folder holding repro.yaml; opens http://localhost:5190/
```

The page is built from what `repro verify`, `repro stale`, `prereg check` and `results verify`
report, and from the project's ledger, check history, record of re-runs, manifest and
manuscript. It is served on localhost only.

| tab | what it shows |
|---|---|
| Overview | the status of the plan, the ledger, the quotations, the claims and the re-runs |
| Prereg | what `prereg check` reports for each plan |
| Results | each run, the files it wrote, whether they still hold those bytes, the outside records linked to them, and the claims that read them |
| Citations | each source, its pinned quotations, the reading the paper takes of them, and the sentences that cite it, by section |
| Claims | every claim with its check history |
| Reproduce | each rebuild step, what changed since its last re-run, and every re-run |
| Graph | the files and runs behind each claim, as a lineage graph grouped automatically |

## Writes

- **Refresh** re-reads the records and writes nothing to the project.
- **repro verify** runs the whole-project check (the claims, the plan, the ledger, the
  quotations and what went stale), which adds one line to the project's local check history,
  kept inside `.git` and never committed. It asks first.
- **Reproduce** runs the rebuild steps you choose with `repro reproduce`, which executes the
  commands `repro.yaml` declares and adds the re-run to `.repro/reproductions.jsonl`. It lists
  each command before anything runs.
- **Copy prompt to fix**, on a failing or stale count, puts a prompt for a coding agent on the
  clipboard.

The page's own data and caches are kept in `.git/repro/ui/`, or under
`~/.cache/reproducible-science-ui/` for a project outside git.

## Options

```bash
repro ui [project] [--port 5190] [--offline] [--no-browser] [--groups groups.yaml]
```

`--offline` looks up no DOI. By default the publisher's landing page of each DOI a source names
is looked up once and cached, so the page can link to it. `--groups` takes a YAML list of
`{group, match}`, putting each file whose id matches the pattern into that group of the graph.
