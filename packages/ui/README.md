# reproducible-science-graph

A lineage view of a project checked with [Reproducible Science](https://reproducible.science): which files each claim in a manuscript reads, which rebuild step produces each file, whether each check passes, and which rebuild steps are stale. It has two views:

- **Graph:** a Dagster-style lineage graph with collapsible groups.
- **Catalog:** a table of files or claims.

Prototype. The topic groups in `builder/build_graph.py` are written for the reproducible-science paper and have not yet moved to a config file.

## Build

```sh
# 1. Data: runs `repro verify` and `repro stale` in the project and reads its ledger and check history
uv run --no-project --with pyyaml==6.0.2 python builder/build_graph.py <project> web/public/graph.json

# 2. Page
cd web && npm install && npm run build      # or: npm run dev
```

`web/public/graph.json` holds the project's claims and file paths, so it is gitignored.
