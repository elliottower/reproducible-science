# claims-cli

[![pypi](https://img.shields.io/pypi/v/claims-cli)](https://pypi.org/project/claims-cli/)
[![python](https://img.shields.io/pypi/pyversions/claims-cli)](https://pypi.org/project/claims-cli/)
[![license](https://img.shields.io/pypi/l/claims-cli)](https://github.com/elliottower/reproducible-science/blob/main/LICENSE)
[![docs](https://img.shields.io/badge/docs-live-blue)](https://reproducible.science/)

Check what a manuscript states against the files it names.

The part of [reproducible-science](https://github.com/elliottower/reproducible-science) that reads a manifest of claims and checks each one: a number against a results file, a table cell against a table, a quotation against its source. It installs alone, and it runs no command of yours.

## Install

```bash
pip install claims-cli
```

This installs `claims` and one dependency of ours, [`citations`](https://pypi.org/project/citations/), which reads the documents a quotation is checked in. The optional readers are extras, each named for what it reads:

```bash
pip install "claims-cli[parquet,sheets]"
```

`arrays`, `hdf5`, `netcdf`, `parquet`, `rds`, `sheets` and `stata-spss`. Without the extra a format needs, a check of that format is `unchecked` and names the extra to install.

## What it reads

`repro.yaml`, a manifest that pins a project's files by sha256 and declares what the manuscript claims about them:

```yaml
artifacts:
  - id: results
    path: analysis/results.json
    digest: {algorithm: sha256, value: 9f635f9a...}

claims:
  - id: primary
    text: The treatment reduced the primary outcome
    evidence:
      - kind: metric
        artifact: results
        name: p_value
        pointer: /primary/p
        reported: "0.031"
```

The file has the same name and the same format whichever command reads it. The [specification](https://reproducible.science/reference/spec/) defines every kind of evidence and every outcome.

## The commands

```bash
claims manifest init
```

Writes a starter `repro.yaml` at the top of the project: each file it finds or is given, pinned, with example claims that verify as written. It never overwrites one.

```bash
claims verify
```

Checks every declared assertion against the file it names and prints one line per assertion: `ok`, `MISS` where the file holds another value, `GONE` where the address does not resolve, `--` where the check could not run. It exits 1 where the policy fails, and `--format json` and `--format sarif` print the report as a document. With no `repro.yaml` it reports the result files and the manuscript `claims manifest init` would pin, and lists as guesses the numbers the manuscript prints that agree with a value in one of those files. It writes nothing, verifies nothing, and exits 2.

```bash
claims stale
```

Says which claims read a file that is no longer what a recorded re-run produced. It reads `.repro/reproductions.jsonl` and runs nothing.

```bash
claims why primary
```

For one claim: each assertion as `claims verify` evaluates it now, each file the claim rests on and the command recorded for it, and then what the record does not establish.

```bash
claims numbers
```

Counts every number the manuscript's text prints and says which a claim accounts for.

```bash
claims export record
```

Writes one record per checked assertion, for another program to read. `sarif` and `ro-crate` write the same records in those formats. Each record names its version, `reproducible.science/claim-check/0.1-experimental`, and 0.6 also reads records under `repro.check/0.1-experimental`, the name 0.5.6 wrote. The JSON Schema is at <https://reproducible.science/schemas/claim-check-0.1-experimental.schema.json>, and the [check record](https://reproducible.science/concepts/check-record/) page describes the format.

```bash
claims origins --repo https://github.com/owner/study=../study
```

For each artifact copied from another repository, compares the pinned digest with the bytes of that path at that commit. The artifact names its source with `origin`:

```yaml
artifacts:
  - id: indices
    path: artifacts/indices.json
    digest: {algorithm: sha256, value: 3db72e39...}
    origin:
      repository: https://github.com/owner/study
      commit: d4d6909cd7a99bec2416c2fe561b1a04d5bf5802
      path: results/indices.json
```

`commit` is the full 40-character id, and `path` is relative to that repository's root; a branch, a tag, a short id or a path with `..` is refused when the manifest is read. Here the copy was edited after it was taken:

```text
  DIFFERS        indices: https://github.com/owner/study d4d6909cd7a9:results/indices.json
                 the origin's bytes do not have the pinned digest (read from /home/you/work/study)
                 pinned    3db72e396caeafded64ab436f341936577b90ad3767a6edb59dea9045d20c5e0
                 at origin 2ec7fab1cf2458f30591cc157b23cc50380644ee085a46b9b23237650456e4c4

  1 origins: 0 same, 1 differs, 0 absent, 0 unknown commit, 0 not checked
```

Each origin is `same`, `differs`, `absent`, `unknown commit` or `not checked`, with the reason. A clone given with `--repo REPOSITORY=PATH`, or a repository named by a local path, is read with `git cat-file`, so committed bytes are compared and never a working tree. With `--fetch`, a GitHub repository no clone is given for is read from `raw.githubusercontent.com`; without it nothing touches the network. It exits 0 where every origin is `same`, 1 where one differs or is absent, and 2 where one could not be checked and none failed, or where no artifact declares an origin. `claims verify` never reads an origin, and `claims export record` carries the declared origin on each file it read.

## With `repro`

[`reproducible-science`](https://pypi.org/project/reproducible-science/) depends on this package and adds the commands that run things: `repro reproduce`, which runs each declared command again and writes the record `claims stale` reads, `repro audit`, which drives `prereg`, `results` and `citations`, and `repro ci`. Under `repro`, every command above but `verify` has the same name, does the same thing and prints the same output. `repro verify` checks what `claims verify` checks and, in the same report, every other record the project keeps: `prereg check`, `results verify --files`, `citations verify` and each declared command against its recorded re-runs. `claims verify` is the claims alone, and the fast check. A project that uses `repro` has no reason to install this by itself. It is separate so that checking a manuscript's claims does not require installing something that executes commands a manifest names.

MIT licensed.
