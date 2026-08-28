- **[citations] `citations add` writes an entry into a `.bib` and refuses a key the file
  already has.** Appending by hand put a duplicate key in a paper's bibliography twice in one
  session. BibTeX's answer to a repeated key is non-fatal -- it reports `Repeated entry`,
  keeps the copy defined first, skips the second and writes a `.bbl` without it -- so the
  entry just added never reaches the reference list and the failure surfaces as `Citation
  undefined` warnings that name nothing. `add` takes the entry from a file, from standard
  input, or fetched by `--doi` or `--arxiv`; a fetched entry is shown before it is written and
  carries every author the registry lists, never `and others`. A repeated key exits non-zero,
  prints both entries side by side and writes nothing, with case folded because BibTeX folds
  it. The write is read back before it is reported, and the original bytes go back if the file
  does not parse as what it parsed as before plus one entry. `citations lint --bib <file>`
  asks the same question of a file already written and needs neither papis nor a library.
