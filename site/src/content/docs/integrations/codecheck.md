---
title: CODECHECK
description: claims from-codecheck reads a codecheck.yml into a draft manifest and the items it leaves open.
---

`claims from-codecheck` reads a CODECHECK configuration file and writes a draft manifest. The
configuration file lists the output files a codechecker recreated and a comment saying what
each one is. It states no value and no sentence of the paper, so every claim the reader writes
is left open.

## Reads

- A `codecheck.yml` (configuration specification 2.0), by its path, or by a certificate
  identifier `YYYY-NNN`.
- For an identifier: a copy of the register's `register.json`, passed with `--register`, whose
  sha256 is recorded in the open items. `--register-sha256` refuses any other copy.
- The output files, from the folder the `codecheck.yml` is in, or from `--bundle`. With
  `--fetch`, an identifier with no `--bundle` has its `codecheck.yml` fetched from GitHub at the
  commit the default branch points to, and that commit is recorded.

## Writes

`repro.draft.yaml` and `open-items.json` in the output directory.

- Each output file is an artifact, pinned by sha256 where it is on disk.
- Each output in a format the claims backends read as a value becomes a claim whose text is
  the output's comment as written, with two open items: the passage of the paper it supports,
  and a value the paper prints from it.
- A figure, a file in another format, an output the comment places outside the paper, and a
  check that declares no output files are passed over, each with the reason.

## Command

```bash
claims from-codecheck 2024-001 --register register.json --bundle ../codecheck-2024-001 -o draft/
```

## Refuses or never does

- Writes no certificate field, and names no claim, artifact or project of the draft by the
  certificate's identifier.
- Binds nothing by itself: every claim it writes is left open.
- Never writes over an existing file, and never writes into the bundle.
- Refuses a `register.json` whose sha256 is not the one given, a configuration file with no
  `manifest` list, and a key given twice.
- Never fetches a repository that is not on GitHub.
- Never follows a link out of the bundle, and never pins a Git LFS pointer: the file is
  reported as not checked.

## Does not claim

The draft is not a CODECHECK certificate and does not restate one. A codechecker's report says
that outputs were recreated; the draft says which outputs exist and leaves the binding of each
to the paper open. The [open items](/agents/open-items/) page describes how those are
filled.

## The other project

[codecheck.org.uk](https://codecheck.org.uk/), and the
[configuration file specification](https://codecheck.org.uk/spec/config/2.0/).

Not affiliated with or endorsed by CODECHECK.
