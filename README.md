# reproducible-science

[![CI](https://img.shields.io/github/actions/workflow/status/elliottower/reproducible-science/ci.yml?branch=main&logo=github&label=CI)](https://github.com/elliottower/reproducible-science/actions?query=branch%3Amain+workflow%3ACI)
[![docs](https://img.shields.io/badge/docs-live-blue)](https://elliottower.github.io/reproducible-science/)
[![pypi](https://img.shields.io/pypi/v/reproducible-science?label=%20)](https://pypi.org/project/reproducible-science/)
[![python](https://img.shields.io/pypi/pyversions/reproducible-science)](https://pypi.org/project/reproducible-science/)
[![license](https://img.shields.io/pypi/l/reproducible-science)](LICENSE)

Command-line tools that check whether a paper's claims match its artifacts.

See our [Claude Code plugin](#claude-code), which traces results at the time of experimentation.

## Documentation

**[elliottower.github.io/reproducible-science](https://elliottower.github.io/reproducible-science/)**

The docs include a notebook that runs the published packages in your browser, with nothing to
install.

## Project status

| | |
|---|---|
| Version | 0.2.0 — the evidence contract is specified and stable; the CLI surface may still change |
| Python | 3.11, 3.12, 3.13 |
| Formats addressed | JSON, YAML, CSV/TSV, SQLite, NumPy `.npy`/`.npz` |
| No adapter yet | Parquet, HDF5, NetCDF, XLSX |

Point a manifest at a format with no adapter and you get `format_unsupported` instead of a
guess.

## Install

| tool | install | what it does |
|---|---|---|
| [`repro`](packages/repro) | `pip install reproducible-science` | verifies declared evidence — quotations, reported values, table cells — against hash-pinned artifacts |
| [`citations`](packages/citations) | `pip install citations` | checks that quotations resolve in the sources they cite |
| [`results`](packages/results) | `pip install results-cli` | seals inputs, records outputs, binds a paper's claims to runs |
| [`prereg`](packages/prereg) | `pip install prereg` | freezes a plan before running, and records what changed after |

`pip install reproducible-science` brings all four. Each tool is its own distribution, so
installing one brings only that one.

## Getting started

Write down what your paper claims and where each claim comes from. `repro verify` checks every
one against the file it names and tells you which ones hold.

```console
$ prereg freeze                                    # lock the plan; names a git commit
$ results seal analysis.py data.csv                # hash the inputs, before the run
$ results run output.json --run-id exp_001         # hash the outputs, after it
$ results claim "ICC = 0.42" --run-id exp_001 --location "Table 2"
$ repro verify
  Table 2, "ICC = 0.42"          verified   results.json /icc = 0.42
  Section 3, "p < 0.05"          MISMATCH   the source reads p = 0.051
  Appendix B, "n = 60"           unchecked  results.json is not there
  1 of 3 assertions failed, 1 could not be checked.
```

Quotations are matched against the sources they cite, page numbers included. Reported numbers
are compared against the value stored at an address you gave — never by searching a file for a
number that looks close enough. When a check cannot run at all, it reports that, and the run
does not pass.

Preregistration is optional — you mark a claim confirmatory, exploratory, or not applicable,
and only the first kind needs a plan behind it.

## Claude Code

```
/plugin marketplace add elliottower/reproducible-science
```

The plugin ships `prereg`, `citations` and `results` as slash commands, backed by the same
packages.

## Contributing

[Contributing](CONTRIBUTING.md) to get started, [Development](DEVELOPMENT.md) for the workspace
and release machinery, and [docs/SPEC.md](docs/SPEC.md) for what a decision means. Security
issues: [SECURITY.md](SECURITY.md).

MIT licensed.
