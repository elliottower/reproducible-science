---
title: CORE-Bench
description: claims from-corebench reads a capsule and its task into a draft manifest and the items it leaves open.
---

`claims from-corebench` reads a CORE-Bench capsule folder and the task for it, and writes a
draft manifest. A task states each question and the value the capsule's run produces. It does
not say which file holds the value, so the address of every value is left open.

## Reads

- The capsule's folder, holding `results/`.
- A task file holding this capsule's task, or a list of tasks. The capsule is found by
  `--capsule-id`, or by the folder's name.
- Files under `results/` only through parsers that evaluate nothing: JSON, YAML with the safe
  loader, and delimited text.

## Writes

`repro.draft.yaml` and `open-items.json` in the output directory.

- Each file under `results/` in a format a backend reads is an artifact, pinned by sha256.
- Each question is a claim whose text is the question as written, with one open item: the
  address of the value in a result file, or, for an answer that is not a number, the passage
  that prints it.
- Each item lists as candidates the addresses at which a check of the task's value would
  match. An item is `unique` where exactly one candidate passes two guards: the value has at
  least three significant digits and is not an integer below 1000, and every label the
  question names agrees with the address's labels.

## Command

```bash
claims from-corebench capsule-5507257 core_test.json -o draft/
```

## Refuses or never does

- Never writes a candidate into the draft, unique or not.
- Runs nothing in the capsule.
- Gives no candidate where the runs recorded in the task disagree, and lists each run's value.
- Never treats a small integer, or a value at two addresses, as unique.
- Refuses a task file without the capsule, and a task file with a key twice; writes nothing
  then.
- Never reads through a link out of the capsule or a Git LFS pointer, and never writes over an
  existing file.

## Does not claim

A unique candidate is a lead for whoever fills the item, not a binding. The draft does not say
the capsule reproduces: it says which files exist and which values the task states.

## The other project

[CORE-Bench on GitHub](https://github.com/siegelz/core-bench).

Not affiliated with or endorsed by CORE-Bench or its authors.
