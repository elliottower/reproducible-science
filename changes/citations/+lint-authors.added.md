- **[citations] `citations lint --authors` reads a bibliography's author lists back against the
  registry each entry's own identifier names.** Two agents in one session attributed
  "Mediational E-values" (Epidemiology 30(6):835-837, 2019) to VanderWeele and Chiba while
  quoting the paper's DOI, 10.1097/EDE.0000000000001064, whose authors Crossref gives as Smith,
  Louisa H. and VanderWeele, Tyler J. A VanderWeele and Chiba paper exists on another subject in
  another journal, so the entry was two real papers written as one and every field named
  something that exists -- which is why reading the reference list does not catch it. The
  identifier was right both times and nothing read the names. The check reports four kinds of
  finding from one comparison: a name belonging to another paper, a list that stops early with
  no marker, `and others` or `et al.` written into a `.bib`, and the registry's names in another
  sequence. It compares family names folded, with both spellings of an accent and with surname
  particles stripped as well as kept, so Krzyżosiak against Krzyzosiak is not a finding. Entries
  with no identifier are skipped and counted rather than passed, findings exit non-zero under
  `--json` as well as in the report, and resolved lists are cached beside the bibliography so a
  second run needs no network.
