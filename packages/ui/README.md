# reproducible-science-graph

A lineage view of a project checked with [Reproducible Science](https://reproducible.science): which files each claim in a manuscript reads, which rebuild step produces each file, whether each check passes, and which rebuild steps are stale. It has two views:

- **Graph:** a Dagster-style lineage graph with collapsible groups.
- **Catalog:** a table of files or claims.

Prototype. Files are grouped automatically; `--groups groups.yaml` (a list of `{group, match}`) overrides that.

## Run

```sh
cd web && npm install && npm run build && cd ..
uv run --no-project --with pyyaml==6.0.2 python builder/serve.py <project>     # http://localhost:5190
```

The server listens on localhost only. The header carries the same four lines the repro mod draws (prereg, results, citations, repro) and three buttons:

- **Refresh** re-reads the records (`repro stale`, `results verify`, `prereg check`, the ledger, the check history) and writes nothing to the project.
- **Run repro verify** checks every claim again, which records the check in the project's history.
- **Send to Claude Code / Copy prompt** (⇄ switches) hands a prompt covering every failing claim and stale rebuild step to Claude Code. Sending appends it to `~/.claude/repro-fixes/queue.jsonl`, which the `repro-fixes` mod shows above the prompt of the session working in that project; nothing runs until the person loads it and presses Enter. Failing claims and stale files carry the same buttons in their panels.

## Build a static copy

```sh
# 1. Data: runs `repro verify` and `repro stale` in the project and reads its ledger and check history
uv run --no-project --with pyyaml==6.0.2 python builder/build_graph.py <project> web/public/graph.json

# 2. Page
cd web && npm install && npm run build      # or: npm run dev
```

`web/public/graph.json` holds the project's claims and file paths, so it is gitignored.
