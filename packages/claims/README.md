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

Checks every declared assertion against the file it names and prints one line per assertion: `ok`, `MISS` where the file holds another value, `GONE` where the address does not resolve, `--` where the check could not run. It exits 1 where the policy fails, and `--format json` and `--format sarif` print the report as a document.

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

Writes one record per checked assertion, for another program to read. `sarif` and `ro-crate` write the same records in those formats.

## With `repro`

[`reproducible-science`](https://pypi.org/project/reproducible-science/) depends on this package and adds the commands that run things: `repro reproduce`, which runs each declared command again and writes the record `claims stale` reads, `repro check` and `repro audit`, which drive `prereg`, `results` and `citations`, and `repro ci`. Under `repro`, every command above has the same name, does the same thing and prints the same output: `repro verify` and `claims verify` are one function. A project that uses `repro` has no reason to install this by itself. It is separate so that checking a manuscript's claims does not require installing something that executes commands a manifest names.

MIT licensed.
