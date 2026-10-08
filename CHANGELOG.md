## 0.5.2 — 2026-10-08

### citations

#### Changed

- **A `citations` command that reads no source no longer loads the PDF and spreadsheet libraries.** Importing the package imported the checker, and the checker imports `pdfplumber`, `pypdf` and `openpyxl`, so `citations lint`, `citations add` and every other subcommand waited most of a second for libraries only `verify` and `coverage` call. The package now imports a public name the first time it is asked for, and the command starts in `citations.entry`, which loads the subcommand asked for. Every name importable from `citations` is still importable, and `citations.cli:main` still runs the whole command. `citations lint --claims DIR --json` on a one-source project went from a median of 1.34 s to 0.48 s.

#### Added

- **A `not found` quotation whose every word is in the source says so.** A quotation made of two or more stretches of the source, in the source's order, with source text left out between them and nothing marking the gap, is still `not found` and still fails. Its result now carries `reason = "omission"` and one gap for each place text was left out, with the position in the quotation, the source text left out there and its length, and `passage`, the source from the first piece to the last; the report prints the left-out text and the passage with it marked, names the two repairs (quote the passage as the source reads, or mark the gap with an ellipsis in a manuscript), and the `not found` row counts these separately. Every piece must match exactly under the existing folding and be at least 20 characters, and a cut may fall only between whole tokens of the source, at white space the source itself has, so a number, a signed number or a hyphenated word cut short, punctuation left out, pieces in another order and a short fragment are a plain `not found` as before.
- **`citations lint --claims` and `citations verify` report a pinned source the last commit still holds.** `git rm --cached` takes a file out of the index and out of no commit, so until the removal is committed the text is still in `HEAD`. `lint --claims` lists such a source as `in HEAD`, whether or not the file is on disk, and its `--json` rows carry `index` and `head` for every source listed. `verify` names the sources it read that the last commit holds and git no longer tracks. Both remain warnings: no verdict and no exit code changes.
- **`citations lint --claims` takes no directory.** Given none, it reads `claims` in the working directory, or the nearest `claims` above it inside the same repository; outside a repository it reads the working directory alone. A named directory is read as before.
- **`citations pin --occurrence N` pins one occurrence of a passage the source repeats.** A passage occurring more than once is refused as `ambiguous`, and the remedy was a `prefix` and `suffix` written into the claims file by hand. `--occurrence N` counts from 1 in the source's order and writes the anchors that single that occurrence out, widened through the source until the anchored passage occurs once and checked before anything is written, so the entry resolves under `verify --strict`. Anchors that would pass 1,000 characters a side are refused. Without the flag a repeated passage is still refused, and the refusal names the flag.
- **`citations pin` says when the source it read is tracked by git, or covered by no ignore rule.** One line after the quotation is written, with the same remedy `verify` names. It refuses nothing and does not edit `.gitignore`. An ignored source, and a source outside any repository, get no line.
- **`citations restore` writes the source's passage for a quotation that leaves text out, as a separate record.** It applies only to an omission whose shortest passage is the only one the quotation can have been taken from, every other way of fitting it spanning a longer passage that contains it, and which leaves out at most `--max-omitted-tokens` tokens, 1 by default; the limit never changes which passage is restored. The source must be pinned. The claims file it is given is never edited; the derived claim goes in `<name>.restored.yaml` beside it, with the original quotation, the bounded passage in the source's own characters, the source and text digests, the offsets of the passage and of each omitted stretch, how many ways the quotation fits, the rule and its limits, and the software version. `verify` counts restored quotations on a line of their own.
- **`citations verify` and `citations lint --claims DIR` report a pinned source that git tracks.** A claims file pins its source by a sha256, so no check needs the source committed, and a committed one is somebody else's text published with the repository. `verify` prints how many sources it read from a tracked file and names the first ten, each with the claims file that pins it; `lint --claims` lists every one, and prints them as JSON with `--json`. The finding is a warning: it changes no verdict and no exit code, with or without `--strict`, and `lint --claims` exits 0 whatever it finds. The report names the remedy, which is to untrack the file and add an ignore rule, the record's sha256 and url being what `citations fetch` restores it from. Outside a repository, and on a machine without git, nothing is reported.

### prereg

#### Changed

- **`prereg freeze` is refused where git holds a pinned source.** This changes what a freeze does: one that succeeded before can now exit 1. A freeze names a commit, and a source text in that commit can only be removed later by rewriting history, which changes the commit's identifier. Where `citations` is on `PATH`, a freeze first runs `citations lint --claims --json` beside the plan; where the index or the last commit holds a source the project's claims files pin, it prints the count, the first ten by path, and the way out of each case, writes nothing (no record, no log entry, no timestamp request, no lock file, nothing sent to OSF), and exits 1. A source is listed as `tracked` (in the index and the last commit), `staged` (in the index alone), or `in HEAD` (untracked with `git rm --cached`, or deleted, with the removal not yet committed). The ways out are to untrack the files, add an ignore rule, commit and freeze again, or to pass the new `--allow-tracked-sources`, with which the freeze goes ahead and names the sources after its report. A plan, an amendment and a forced re-freeze of a plan frozen in place are treated alike. Only an answer refuses: with no `citations` installed, a version that cannot be asked this way, no claims directory, a timeout, or nothing held, the freeze goes ahead as before. Nothing of `citations` is imported.

### results-cli

No significant changes.

### reproducible-science

#### Changed

- `repro audit` counts `*.restored.yaml` files, which `citations restore` writes, apart from the claims files the authors declared: `claim_records`, `claims` and `quotations` leave them out, and `restored_claim_records` and `restored_quotations` are reported where there are any.

#### Added

- **`repro audit` reports how many sources the audited repository commits.** Where `citations verify` read a source that git tracks, the step's `found` ends with `N sources tracked by git`, in the table and in the record. No outcome and no exit code changes.

### provenance-core

No significant changes.

## 0.5.1 — 2026-10-07

### citations

#### Changed

- `citations verify` keeps the text `pdftotext` extracts between runs and reads several sources at a time. An entry is filed under the sha256 of the source's bytes, the extractor's version and its arguments, so a changed source or a different poppler is extracted again, and the report counts the readings taken from the cache. `--no-cache` or `CITATIONS_NO_CACHE=1` reads every source and keeps nothing. Normalizing the extracted text and listing a source's folder are also faster. Checking 947 quotations in 29 PDFs took 20.6 seconds before, 8.1 on a first run and 2.7 on a second.

### prereg

No significant changes.

### results-cli

No significant changes.

### reproducible-science

#### Fixed

- `repro verify` reads each artifact once in a run. A manifest with many claims over one table parsed the table, and extracted the document's text, once for every claim, and scanned every row for each; under a profiler, checking 1,000 numbers bound to one CSV took 17.5 seconds and now takes 1.4. A second verification in the same process still reads every file again. The manifest itself is read with libyaml's loader where PyYAML has it.

### provenance-core

No significant changes.

## 0.5.0 — 2026-10-06

### citations

#### Fixed

- **[citations] A `prefix` or `suffix` written without its separating space singles out its occurrence.** A YAML plain scalar cannot begin or end with a space, so `suffix: in August` reached the check welded to the passage, matched nothing, and the passage stayed `ambiguous` with advice to widen an anchor that was already wide enough. The anchors are now tried as written and then with a space at each seam.
- **[citations] A run that read none of its sources is no longer a pass.** `Report.ok` documented that a run measuring nothing is not one and implemented it only for a claims set with no quotations, so a project whose every source went `unchecked` — a `pdftotext` `extract_cmd` declared without `{} -`, an extractor not installed, a reference directory that moved — exited 0 under a closing line beginning "nothing failed". Measured on this project's own corpus: 35 quotations, no source read, reported as 35 verified. A run resolving even one quotation is unaffected; `--strict` remains what refuses a partially unresolved one, and is now named in the summary when there is something for it to refuse.
- **[citations] A source declaring `extract_cmd: cat {}` is read off disk instead of refused.** `cat` given only the source names no rendering, just the file's bytes, which `citations` already reads itself for a text file. It was treated as a program outside the default allowlist, so on one public site 23 quotations against a plain-text source were `unchecked` and asked for `--allow-extractor cat`. The declaration is now read in process, runs no program and needs no consent, and the result names the reading `text`. `cat` with anything beyond the source, such as `cat -n {}` or a second path, is still a command and is still refused without consent.
- **[citations] `citations audit` reads a field that shares a line with the next one.** The field pattern required a newline before the following `name =`, so an entry writing `volume = {103}, number = {2}, pages = {483--490}, year = {2016},` on one line — which BibTeX permits and reference managers emit — gave `volume` a value swallowing every field after it. The entry then disagreed with the record its own DOI resolves to, on a value nobody had typed wrong, and the real defects in the same report were harder to see for it. Found on a manuscript where two of three flagged entries were this and the third was a genuine dropped author.
- - **[citations] A stroked letter resolves to the letter rather than being deleted.** NFKD leaves
    `ł`, `đ`, `ħ`, `ŧ`, `ð` and `þ` whole, so the fold's character class removed them and
    Kozłowski became `koz owski` -- one name in two tokens, matching nothing. Every author with
    one of those letters in their surname was a disagreement to `citations audit` and unfindable
    to `citations resolve`.

#### Added

- **[citations] `citations fetch` downloads the sources a claims directory pins.** A public repository carries each source's sha256 and not the source, so a reader who cloned one had every pin and no file, and `verify` answered `unchecked` for every quotation. `fetch` tries the arXiv PDF, the URL the claims file records, and the open-access locations Europe PMC and OpenAlex list for the DOI, and installs a download only when its sha256 is the pinned one; bytes that differ are reported as `differs` and never written. Measured on claims directories with no source on disk: 12 of 16 arXiv-hosted sources came back byte-identical and 1,920 of 2,515 quotations resolved; for a biomedical study, 27 of 94 sources and 58 of 175 quotations. A source that records no `url`, `doi` or arXiv id is reported as `no location`, and `citations pin` names that gap when a quotation is pinned against one. ([#79](https://github.com/elliottower/reproducible-science/pull/79))
- **[citations] A workbook, a `.docx` and an article's XML are pinned as the publisher's file and read by a named, versioned extractor.** `citations` read PDFs and plain text, so such a source could be pinned only as a text a script had made from it, and a reader's download never matched the pin; pinned directly, a workbook or a `.docx` reached the PDF readers and was `unchecked`, and an `.xml` was matched with its markup in place. `sheet-rows` (`.xlsx`, `.xls`, `.csv`), `docx-text` and `jats-text` now run in process and are recorded on each result as `name@version`; `openpyxl`, `xlrd` and `python-docx` are optional extras (`citations[sheets]`, `citations[docx]`), and a reader that is not installed or a version this build does not ship is `unchecked` with the reason. A source block can name `extractor`, `extractor_version`, `sheet`, `empty_cells` and `derived_sha256`, the digest of the extracted text, which `citations pin` records with the first quotation. `verify` fails a source whose extractor no longer produces that text, and `fetch` checks the original and then the extracted text, reporting `differs`, `text differs` and `text unchecked` as separate outcomes. Measured on 72 Europe PMC and NCBI articles holding 314 quotations pinned against tag-stripped text: 194 resolved in the XML as served and 308 resolve through `jats-text`; pinned that way, `fetch` installed 72 of 72 originals on an empty checkout and `verify` found 308 of 308. On 22 publisher workbooks, 1,164 of 1,437 quotations pinned against hand-made text resolved unchanged through `sheet-rows`, 264 were ambiguous across sheets and 9 were not found. ([#82](https://github.com/elliottower/reproducible-science/pull/82))
- **[citations] `citations audit` searches by title for an entry with no DOI and no PMID, and compares it with the record it finds.** Such an entry was counted under `no id` and nothing read its authors, year or title back, so the entries least likely to be right were the entries no check reached. The search asks Semantic Scholar, Crossref, OpenAlex and arXiv in turn and accepts a candidate under the rule `citations resolve` already uses: title similarity of at least 0.87, the first author's surname among the candidate's authors, and the year within one. A DOI found that way is fetched from Crossref or DataCite and compared like any other, an arXiv id is read as the DataCite DOI `10.48550/arXiv.<id>`, and the report lists each identifier found so it can be added to the entry. An OpenAlex record with no DOI is reported as `found` with nothing compared. An entry no service has a record for is `not found`, which does not fail the audit under `--strict`, because a book, a report and a thesis land in that row as well as an invented reference. An entry every service refused is `unresolved`, never `not found`. Search answers are cached with the registry payloads, a refusal is not cached, and `--no-search` restores the earlier report. `--json` carries `found_kind`, `found_id`, `found_by` and `searched` on each entry.
- **[citations] `citations verify --claims` reads a source from the library when the path its claims file names is empty.** A public repository carries each source's sha256 and not the source, so a clone had every pin and no file, and every quotation was `unchecked ... file not found` even on a machine whose library held the document. `verify` now looks in the library's `pdfs/` for a file under the record's own filename and reads it only if its bytes hash to the pinned sha256. A claims file with no pin is never read from the library and its reason says a pin is needed; a library file under that name with other bytes is not read and the reason gives both digests. The report counts the sources read from the library and names the directory. `verify` writes nothing and downloads nothing, a source present at the named path is read from there as before, and `--strict` and the exit codes are unchanged. Measured on fresh clones against one library: 175 of 175 quotations in a 94-source biomedical claims directory resolved where 175 had been `unchecked`, and 1 of 1 in a second; a third, whose 7 sources the library does not hold, stayed at 18 `unchecked`.
- - **[citations] `citations lint --authors` reads a bibliography's author lists back against the
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
- - **[citations] `citations lint --bib` reports an author list written as family names with no
    given names.** `author = {Bhaskar and Wettig and Friedman and Chen}` prints as "Bhaskar,
    Wettig, Friedman, and Chen." in the reference list, and five entries in one paper's
    bibliography were like that on the day it was submitted. `--authors` passed all five, because
    the four family names are the four arXiv:2406.16778 lists, in order, and family names are all
    that comparison reads. Nothing outside the file settles a missing given name, so the check
    sits in the offline mode beside the repeated keys and needs no network. A name that is one
    word, carries no comma and is not braced has no given part for a reference style to print;
    `{NASA}` and `{Open Science Collaboration}` are braced, which is how BibTeX is told a name is
    complete as written, so neither is a finding. `--bib` now reports both kinds under one exit
    code and one JSON document, each finding naming its kind.

  - **[citations] A braced author is no longer split at an ` and ` inside its braces.**
    `{President's Council of Advisors on Science and Technology}` was read as two authors, the
    second of which is `Technology}`, and `{U.S. Food and Drug Administration}` as two more. Both
    `--bib` and `--authors` read names through the same splitter, so the second of those phantom
    authors counted against the registry's list as well.

### prereg

#### Fixed

- **[prereg] `prereg check` says whether a log grew or shrank.** Every mismatch between the log and the count recorded beside the plan hash was reported as an entry removed from the end, including a log holding one entry more than recorded. A longer log now names the added entries, says when one carries no chain value and so was written by hand, and says that `prereg log` brings the record up to date. `check` no longer prints "The plan was edited after freezing" beneath a log problem when the plan hash matches. ([#88](https://github.com/elliottower/reproducible-science/pull/88))
- **[prereg] An `OSF_TOKEN` in a `.env` that is a named pipe is found.** The lookup accepted only a regular file, and `is_file()` is false for a pipe, so a `.env` exposed by a secret manager (a 1Password-managed environment is one) was passed over as if absent. A pipe is now read in a thread and abandoned after 60 seconds with an error saying the secret source did not deliver, so a dismissed approval prompt cannot hang the command. The token is read only when a request is about to be made, after the typed confirmation, so a cancelled command never triggers the approval prompt.
- **[prereg] `prereg check` reads the plans below a governing plan as well.** Run where a `PREREG.md` already governed the directory, it checked that plan and stopped, so a second plan kept in a subfolder was never read: an edit to it passed, and the count of plans was one. It now checks the governing plan and every plan below the working directory, and prints the same summary line it prints at a root with no plan of its own. A directory with one plan and none below reports as before.
- **[prereg] `prereg freeze --osf` no longer rejects a plan made by `prereg new`.** The four `- File upload` headings map to no text question on purpose, because OSF answers them with files, and the push then counted them as headings it did not recognize and refused the plan as one that "would be missing" sections. Every plan the template produces carries all four, so no template plan could be pushed. A heading the mapping does not know at all is still refused.
- **[prereg] `prereg freeze --osf` reads the response keys from where OSF keeps them.** The schema fetch read `attributes.schema.blocks`, which carries each question's text and no response key, so the map came back empty and every section with content was refused as unmapped: no plan with an answer in it could be pushed. The keys are on the schema's `schema_blocks`, joined to their question by `schema_block_group_key`, which is how OSF's own validator joins them. Four OSF questions are multiple choice (Foreknowledge, Study type, Intention for causal interpretation, Blinding of experimental treatments); OSF rejects prose there, so each line under those headings has to name one of the question's options, by its full text or a prefix no other option shares, and the push now refuses before anything is written when one does not, listing the options. `N/A` leaves the question unanswered, and a section still holding the template's italic prompt is no longer sent as its own answer. An OSF error now carries OSF's explanation rather than ending in a traceback.

#### Changed

- **[prereg] `prereg freeze --osf` pushes a draft without asking, and fills its Metadata page; `prereg register --all` registers every plan below after one phrase.** A draft is private and deletable, so the push, its uploads and its metadata run unattended, and an agent can prepare every draft of a study; only `register` and `link`, which cannot be undone, ask for a typed phrase. New `freeze` flags fill OSF's Metadata page: `--subject` (repeatable; OSF will not register a draft with none, and the push warns), `--description`, `--tag`, `--category`, `--copyright-holder` with `--license` (CC-BY 4.0 by default), and `--title-prefix`; a subject, license or category OSF does not have is refused before anything is frozen. `register --all` checks every plan first and asks once, with a phrase naming the list; a plan already registered is skipped so an interrupted batch can be rerun. `register` no longer takes a server error as a failed registration: OSF has answered 502 while creating one, so after any error but a 400 it looks for the registration before retrying, and logs one found that way as `found after OSF error 502`. The token is read as `OSF_TOKEN` or `OSF_PAT`.
- **[prereg] `prereg freeze` writes nothing into the plan, and always attempts the outside timestamp.** A freeze takes one sha256 over the whole file and records it, with the commit, the time and the access level, in `.prereg/PREREG.md.json` beside the plan; the plan is set read-only and `prereg check` reports any byte that differs as `CHANGED`, with no exempt lines. The freeze adds `-text` rules for the plan, its amendments and its log to the nearest `.gitattributes`, so a checkout that converts line endings leaves them as frozen. With a results ledger at or above the plan, the access level recorded is at least the ledger's floor: the highest access level it records, and `results not opened` once it records a run. `prereg new` no longer writes a `**Status:**` line or a `## Log` section, and a draft still carrying either is refused at the freeze. `prereg log` on a plan not yet frozen is refused. A frozen plan cannot be frozen again, with or without `--force`. `--no-timestamp` is removed: a freeze that reaches no calendar, or has none configured, still freezes, says the timestamp is owed, and `prereg check` says so on every run until `prereg timestamp` makes it. `prereg freeze --osf` and `prereg register` log the draft, the attachments and the registration beside the plan; `prereg freeze --osf --access LEVEL` on a plan already frozen pushes its draft and leaves the freeze as it is. A plan frozen by an earlier version, with its freeze record and log inside the file, is not converted: `check`, `log`, `timestamp`, `register`, `link` and `freeze --force` read and write it under the rule it was frozen by, and `prereg log` on one prints a line saying that plans frozen from now on keep their log beside them.

#### Added

- **[prereg] `prereg amend` records a change to a frozen plan as a file of its own, `prereg log` keeps the log beside the plan, and `prereg check --staged` is the check a pre-commit hook runs.** `prereg amend` creates `PREREG_AMENDMENT_N.md` beside the plan with four required fields: the plan or amendment it amends, by sha256 digest (`--parent FILE` names an amendment); the sections replaced or added; the reason; and what had been seen. Where a results ledger sits at or above the plan, the access level is filled from the ledger's floor (the highest level it records, and `results not opened` once it records a run), with the number of runs recorded, and `prereg freeze PREREG_AMENDMENT_N.md` refuses an amendment that states a lower level. An amendment is frozen as a plan is, and its date is its freeze. `prereg log` writes to `PREREG.log`: each entry has the time, the note and the access level, the first entry carries the plan's digest and each later entry the digest of the entry before it, and `PREREG.log.head` records the number of entries and the digest of the last, so an entry removed from the end is reported and nothing is appended over it. `prereg check` lists the plan, then its amendments by freeze time, then the log, each frozen file with its freeze date and access level: `CHANGED` for a file that differs from its freeze, `MISSING` for one that is gone, `orphaned` for an amendment whose parent digest matches no frozen file present, `written after results were seen` under an amendment frozen at `results seen`, and `LOG ALTERED` for a log whose chain does not verify; each of `CHANGED`, `MISSING`, `orphaned` and `LOG ALTERED` exits 1. `prereg timestamp` stamps, completes and checks the timestamp of the plan and of each frozen amendment. `prereg check --staged` exits 1 and names each path when the git index holds a change to a frozen file, an amendment, a committed freeze record, a log that no longer begins with its committed entries, a log anchor whose count went down, the plan section of a plan frozen in place, or a document frozen by a commit line. No hook is installed; the README gives a two-line one.
- **[prereg] `prereg check` checks registrations frozen by a commit line.** A markdown document that records its own freeze commit, as `**Commit SHA:** b96d10a`, `**Freeze SHA:**`, `**Freeze commit:**` or a commit under a heading of one of those names, is compared with the file at that commit, with the commit line left out of both sides. A bold `**Status:**` line before the first heading after the title is part of the freeze record: it is left out of the comparison, and a status that differs from the frozen one is reported under the document without counting as an edit. Each document is listed under its own heading as `unchanged`, `appended` with the number of lines added after the frozen text, `CHANGED` with the lines added and removed and the first difference, `pending` where the line holds a placeholder, or `unknown commit` where the repository does not hold the commit or the file is not in it. A changed document exits 1; `pending` and `unknown commit` exit 2 and are counted in the summary. A repository with no `PREREG.md` and no such document reports as before.
- **[prereg] `prereg freeze` dates the plan outside the repository with OpenTimestamps, and `prereg timestamp` completes and checks the date.** A freeze is a digest recorded in the repository, and whoever holds the repository can rewrite its history, delete it and push it again; every check that reads the repository passes afterwards. The freeze now also sends the digest, with a random nonce so no calendar learns it, to four public OpenTimestamps calendars, and keeps the proof beside the plan as `PREREG.md.ots`. Within hours the calendars commit it into a Bitcoin block, and `prereg timestamp` completes the proof and reports the block's date, checked against two block explorers. `prereg check` reports the proof with no network and fails on a proof of another digest. A freeze that cannot reach two calendars still freezes and says so. An empty `PROVENANCE_CALENDARS` names no calendar, which keeps a test suite off the network.
- **[prereg] `prereg register` and `prereg link` take a frozen plan through OSF registration, and `prereg freeze --osf --attach PATH` registers a shared file with it.** `--attach` uploads a file, such as a `CONTEXT.md` several plans point at, into the draft's storage, which OSF archives into the registration; the log records each file's sha256, and the push fails if OSF reports a different hash for what it received. `register` submits the draft the log recorded at the freeze and requires `--embargo YYYY-MM-DD` or `--immediate`, with no default, because an immediate registration is public. It refuses a plan changed since its freeze, a draft made from an earlier freeze and a draft already registered. `link --anonymous` creates a view-only link that hides the contributors, for double-blind review; the log records the link's id and not its key. Every write to OSF shows what it will send and asks for a phrase naming it on `/dev/tty`, never stdin, and a process with no terminal is refused before any request. `freeze --osf` now finishes every check that can refuse, the confirmation included, before it writes the freeze. Updates to a registration are made in OSF's web interface and are not part of this command.

### results-cli

#### Changed

- **[results-cli] `results init` writes a `.results/.gitignore` that ignores only the lock files.** The ledger and its anchor are then committed with the project by default. `results verify` reported an untracked ledger as a record nobody else can check, and nothing made tracking it the default. A committed ledger is public with the repository, so a run's `note` is written as a commit message would be. A project whose own `.gitignore` lists `.results/` is unaffected until that line is removed. ([#80](https://github.com/elliottower/reproducible-science/pull/80))

#### Added

- **[results-cli] `results timestamp` dates the ledger's head with OpenTimestamps, and `results verify` reports a chain rewritten after it was stamped.** The anchor file catches truncation and a hand-edited line, and not the ledger and its anchor rewritten together, since whoever can write one can write the other. A proof of the head, kept under `.results/timestamps/` and named by the length and head it covers, dates every earlier event through the chain. `results verify` reads the proofs with no network and fails with `TIMESTAMP CONTRADICTS THE CHAIN` when a proof's head no longer matches the chain at its length, which is the rewrite the anchor alone cannot see. A damaged chain is refused rather than stamped.

### reproducible-science

#### Fixed

- **[reproducible-science] A quotation occurring more than once is reported as ambiguous.** `citations` returns `ambiguous` for a passage found twice, and 0.4.2 had no mapping for it, so `repro verify` reported `evidence.error ... KeyError: 'ambiguous'`. It is now `extraction=invalid` with reason `quotation_ambiguous`, flattening to `not_found`, the stages an ambiguous row selector takes. It is kept apart from `passage_ambiguous`, which says a document states two different numbers: a passage written twice contradicts nothing, and the fix is a `prefix` or `suffix` in the record. ([#88](https://github.com/elliottower/reproducible-science/pull/88))

#### Changed

- **[reproducible-science] The `repro` mod says when a project has no manifest.** A project with no `repro.yaml` at or above its top was drawn with three rows and no `repro` row, which read the same as a project with nothing to check. It now gets the fourth row as `repro: no manifest`, as a project with no ledger reads `results: no ledger`.
- **[reproducible-science] The plugin hooks, the mod and the freeze cross-check read a plan frozen whole.** `prereg freeze` now records a freeze in `.prereg/<name>.json` beside the file and writes nothing into it. The hook that speaks before an analysis runs under an unfrozen plan stays silent where that record exists; the hook that reports a frozen plan changed compares a plan or an amendment with the digest in its record; the cross-check of the freeze a claim names reads the commit from the record as well as from a status line; and the mod refuses an `Edit` or `Write` to any file with a freeze record, amendments included, while an amendment still in draft is edited freely. The mod's `prereg` field no longer counts the log line of `prereg check` as a plan.
- **[reproducible-science] `repro verify --regenerate` is removed; `repro reproduce` replaces it.** `repro verify` no longer executes anything, and its report no longer carries `regenerations`. The old flag compared the regenerated output's bytes and reported `diverged` for any difference, including a re-run that wrote every number the manuscript prints into a file ordered differently. The `regenerations` key in `repro.yaml` keeps its name and shape, so a manifest written for the flag runs under the new command unchanged. In the library, `verify()` loses its `regenerate` parameter, `Policy.regeneration_diverged` becomes `regeneration_changed` and `regeneration_failed`, and re-runs are assessed with `Policy.assess_reproduction`.

#### Added

- **[reproducible-science] `repro`, a Claude Code mod for research sessions.** The plugin's hooks speak only in a project that already keeps a ledger or a plan, and cannot refuse anything. The mod refuses an edit to a frozen `PREREG.md`, notes a manuscript edited or an analysis run with no ledger behind it, puts the three gates and the state of the project's records in the system prompt, shows that state in a row above the prompt with one field per tool, pins a warning under the prompt when a frozen plan was edited, the ledger does not verify or runs were recorded with nothing sealed, and adds `/repro-status`. It follows the project whose files a session touches, whatever folder the session started in. Installed separately (`/plugin install repro@reproducible-science`): it uses the function-hooks API, which is early access. ([#81](https://github.com/elliottower/reproducible-science/pull/81))
- **[reproducible-science] `repro verify` reads values from Excel workbooks, Parquet, Feather and Arrow, Stata, SPSS, R data frames, HDF5 and NetCDF.** These formats were `format_unsupported`. A new `sheet` locator addresses a workbook by sheet, column and key predicate. A `table` locator addresses Parquet, Feather, Arrow, `.dta`, `.sav` and an `.rds` data frame through the same row resolution as delimited text, so a predicate matching two rows is ambiguous in every format. An `array` locator addresses an HDF5 dataset or a NetCDF variable by path and index, and NetCDF values are unpacked and a fill value is absent. Each reader is an optional extra (`sheets`, `parquet`, `stata-spss`, `rds`, `hdf5`, `netcdf`). Without one the check is `unchecked` and names the extra, and a file that is not what its suffix says is `unchecked` as unreadable. An `.rds` is parsed by `rdata` without starting R, and pickles are refused by name because reading one runs code. ([#90](https://github.com/elliottower/reproducible-science/pull/90))
- **[reproducible-science] The `repro` mod shows what `repro verify` found, and each row says what it counted.** A project with a `repro.yaml` at or above its top gets a fourth row above the prompt: `repro: 56/56 checks verified`, one check per assertion. A pinned file that changed is named beside the count, so checks read from a file that is not the declared one are never shown as plainly verified. A project with no manifest keeps three rows. The `results` row is now `6/6 runs sealed, 17 claims bound`: the runs recorded after inputs were sealed over all runs, so a run recorded over nothing sealed lowers the first number, and runs whose id begins `smoke_`, `prefreeze_`, `test_` or `dryrun_` are test runs and are left out. The `citations` row reads `63/63 quotes found`. The warning line names a manuscript number that disagrees with its artifact (`1 number mismatched`), with quotations worded apart; a pinned quotation that is not in its source after `/repro-verify` (`1 quotation not found`), counted from the `not found` line of `citations verify` so an unchecked quotation is not reported as missing; and a number bound to a test run (`1 claim on test runs`). A manifest under another name or below the top of the project is not found.
- **[reproducible-science] The `repro` mod's rows name the next command.** A row whose tool has a step still to take shows the command directly after it: `citations: none pinned  →  citations pin`, `repro: no manifest  →  repro manifest init`, an unfrozen draft at `prereg freeze`, a ledger with no runs at `results seal`. A project with nothing set up shows one hint, `repro init`. A row with something to report carries no hint.
- **[reproducible-science] `repro audit` runs the four tools over a clone of somebody else's repository.** `repro audit <url-or-path> [--commit SHA]` clones the repository into a cache directory at that commit (default: the remote's HEAD) and runs `prereg check`, `results verify --files`, `citations verify`, `citations audit` on each tracked `.bib` file and `repro verify` over the clone. It prints one row per check and writes `<name>_audit.json` and `<name>_audit.log`: the commit and tree audited, the installed version of each tool, counts read from the repository's own files, and each step's command, exit code and output. A check that could not be made (a source not on this machine, a registry that did not answer) and a check with nothing to read are reported apart from one that failed, and the command exits 1 for a failure, 2 when a check could not be made or nothing was established, and 0 otherwise. Nothing is written into the audited repository, `--offline` skips the steps that reach a registry, and `--target` takes a YAML file that pins a commit and tree, names unusual paths, or adds steps.
- **[reproducible-science] `repro init` with no name sets up an existing project.** Run inside a project, it works at the git root, or in the working directory outside a repository, and creates whichever of four records are missing: a plan (`prereg new .`), a results ledger (`results init`), a citations library with a `claims/` directory (`citations init`), and a starter `repro.yaml`. It prints one line per record, `created` or `already present`, and the next step for each record it created. A record that exists is never edited, so a second run changes no file. A plan written by hand as `prereg*.md` counts as present, and no library is made where `$CITATIONS_HOME`, a `.citations/` above or the per-user library already governs the project. `repro init <name>` scaffolds a new directory as before and now also writes a starter `repro.yaml` in it.
- **[reproducible-science] `repro manifest init` writes a starter `repro.yaml` for an existing project.** Run at or below the top of a project, it writes the manifest at the git root, or in the working directory outside a repository, and refuses to overwrite one. It pins the files named on the command line by sha256, each with an id, a path relative to the manifest and a media type. With no file named it pins the data files the adapters read at the shallowest level of `results/`, `paper/artifacts/`, `outputs/` and `data/` that holds any, at most 20, and a manuscript when exactly one of `paper`, `manuscript` or `main` with a `.tex`, `.md` or `.txt` suffix exists, and it prints the list as a guess to edit. It writes two example claims, a `metric` for the first number in a pinned JSON or YAML file and a `quote` for a line of a pinned text source, each checked by the engine before it is written, so the manifest passes `repro verify` as written. An example with nothing to point at is written as a YAML comment. A manifest with no claim declared still fails `repro verify` with `report.empty`. `repro verify` in a project with no manifest names this command.
- **[reproducible-science] `repro reproduce` runs a manifest's declared commands again and checks that the manuscript's numbers still hold.** Each record under `regenerations` runs in a directory holding only its declared inputs, and every claim that reads its output is checked against the file it wrote, by the comparison `repro verify` uses and at the precision the manuscript prints. A record has one of five outcomes: `reproduced` (every number still holds, whether or not the bytes match), `changed` (a number is now different, printed with its old value, its new value and the value the manuscript prints), `unchecked` (the output was written and a number could not be read from it), `failed` (the command did not finish, or finished and wrote nothing) and `not_rerun` (skipped with `--skip` or `--only`, or an input is not the one the record names). A record that reads the output of one that did not reproduce runs over the pinned copy and names it. Each invocation appends what it observed to `.repro/reproductions.jsonl`: the environment, the command, exit code and duration, the digest of every input and output, the files written and not declared, and both values of every number. No host, user or absolute path is recorded. The command exits 1 when a number changed or a command failed.

### provenance-core

No significant changes.

## 0.4.2 — 2026-08-29

### citations

#### Fixed

- The plugin's hook never ran. `hooks.json` listed its event at the top level, where the loader
  reads only `hooks` and `modules`, so the plugin reported `failed to load` and no hook was ever
  registered — from the file's first commit through 0.4.1. The events now sit under `hooks`.
  Anyone who installed this plugin expecting drift to be reported on every edit was not getting it.

### prereg

#### Fixed

- The plugin's hook never ran. `hooks.json` listed its event at the top level, where the loader
  reads only `hooks` and `modules`, so the plugin reported `failed to load` and no hook was ever
  registered — from the file's first commit through 0.4.1. The events now sit under `hooks`.
  Anyone who installed this plugin expecting drift to be reported on every edit was not getting it.

### results-cli

#### Fixed

- The plugin's hook never ran. `hooks.json` listed its event at the top level, where the loader
  reads only `hooks` and `modules`, so the plugin reported `failed to load` and no hook was ever
  registered — from the file's first commit through 0.4.1. The events now sit under `hooks`.
  Anyone who installed this plugin expecting drift to be reported on every edit was not getting it.

### reproducible-science

#### Fixed

- The plugin's two hooks never ran. `hooks.json` listed `PostToolUse` and `PreToolUse` at the top
  level, where the loader reads only `hooks` and `modules`, so the plugin reported `failed to load`
  and neither hook was ever registered — from the file's first commit through 0.4.1. The events now
  sit under `hooks`, and all four plugins in this workspace had the same defect.

  The suite passed throughout, because `test_plugin_hooks.py` parsed `hooks.json` itself and asked
  the runtime nothing. A test now asserts the top-level shape for all four plugins and fails on the
  shape that shipped.

### provenance-core

No significant changes.

## 0.4.1 — 2026-08-29

### citations

#### Fixed

- A quotation pinned to a `.py` source was graded `unchecked` rather than resolved. `.py` was
  absent from `TEXT_SUFFIXES`, so the file went to `pdftotext`, which answered `Syntax Error:
  Couldn't read xref table` and left every quotation in it unchecked — reported as a source the
  reader could not open, when nothing there needed a PDF reader at all. Python sources are now
  read directly off disk, and any claim quoting one should be re-verified. ([#54](https://github.com/elliottower/reproducible-science/pull/54))

### prereg

No significant changes.

### results-cli

No significant changes.

### reproducible-science

#### Added

- A `PreToolUse` hook that says a registered plan was never frozen, before the analysis runs
  instead of after it. `frozen_plan_changed.py` notices a plan edited after its freeze; nothing
  noticed a plan carrying no freeze at all, so the mechanism engaged only for authors who had
  already opted in. The new hook reads the command about to run, and where that command invokes
  an analysis under a directory holding a `PREREG.md` with no `**Plan sha256:**` line, it says
  so. It never denies the call and stays silent when there is no plan, when the plan is frozen,
  and when the command is not a run. ([#53](https://github.com/elliottower/reproducible-science/pull/53))

### provenance-core

No significant changes.

## 0.4.0 — 2026-08-29

### citations

#### Fixed

- **[citations] A `.tex` source is read with `detex` rather than `pdftotext`.** A `.tex` with no declared `extract_cmd` got the PDF reader, which answered `Syntax Error: Couldn't read xref table`, and every quotation in it graded `unchecked` until an author declared `detex` by hand — for the commonest manuscript format in this domain, with `detex` already among the default extractors. ([#36](https://github.com/elliottower/reproducible-science/pull/36))
- **[citations] An `ambiguous` outcome is printed.** The checker could return it and the report had no column for it, so it was counted and never shown: the table stopped summing to the number of quotations above it, and a run whose only problem was ambiguity read as clean. ([#39](https://github.com/elliottower/reproducible-science/pull/39))
- **[citations] `citations build` keeps the citations of a paper whose bibliography it could not read.** Records are rewritten whole from the bibliographies, so a paper contributing none — an import with no repository on this machine, a path that moved — lost its `cited_by` entry from every record another paper also cites. Measured on this repository's own library, one such paper bled seven citations per rebuild, silently. ([#40](https://github.com/elliottower/reproducible-science/pull/40))
- **[citations] A rebuild keeps a pinned artifact it cannot repin.** `local` and `sha256` name the copy that was read and hashed, and both were filled only from a paper's own directories — so a pin the library established itself, for a work no paper's `claims/` covers, was dropped on every rebuild without being reported. ([#43](https://github.com/elliottower/reproducible-science/pull/43))
- **[citations] The command list matches the commands.** Four CLIs documented their subcommands in a module docstring that nothing compared to the parser: `citations` advertised a `bib` command that has never existed and omitted `pin` and `projects`, `prereg` omitted `setup`, `results` omitted `reanchor`, and `repro` omitted four.
- A page assertion the declared extractor cannot be asked about is reported rather than dropped.

  A page is verifiable only where this module can request one page on its own terms, which means
  no declared `extract_cmd`: an arbitrary program has no page flag, and asking `pdftotext` for
  page 4 of a source whose author declared `detex` would run a PDF reader over something they just
  said is not a PDF. That reasoning still holds. What did not hold was doing it in silence.

  A record asserting `page: 3` under a declared `pdftotext -layout` had the assertion dropped and
  nothing said so: 154 page assertions in one audited claim, where page 9999 on a three-page
  document graded identically to the correct page. The new `page unchecked` warning does not change
  a verdict; it makes the omission visible, which is the difference between a check that passed and
  a check that never ran.

  A plain-text source is exempt. It has no pages, so a page recorded against one is an inapplicable
  field rather than an unverified assertion.
- An extraction that fails is cached, where only a successful one was. `functools.lru_cache`
  stores a value on a normal return and stores nothing when the call raises, so the cache around
  `extract` memoized every reading it managed and none of the ones it could not, and a source no
  extractor could read was re-attempted once per quotation rather than once per document.

  Measured on a sixteen-claim corpus whose sources all declared an extractor that printed nothing:
  2,210 poppler invocations for 14 unique artifacts, 158 times the work the corpus requires, and
  21 minutes of wall clock of which 95% was the repeated subprocess. The same run now takes 14.6
  seconds.

  `reading_with` had the same shape and matters more, because the second-opinion path reaches it
  on every `not found`: a document no reader could open was re-attempted by every reader, once per
  quotation. `extract.cache_clear` and `reading_with.cache_clear` keep working -- the memoization
  moved underneath them and the handles are delegated, since both were public and a caller
  managing the cache should not have to know which function holds it.
- An extractor that writes a file *beside* the source is reported. The existing check hashes the
  artifact before and after, which catches a renderer that overwrites the file it was given and
  cannot see one that writes a sibling -- the commoner shape, since `pdftotext -layout X.pdf` with
  no trailing `-` writes `X.txt` and prints nothing.

  Thirty-two such files accumulated in one audited repository over three weeks, unnoticed because
  the directory is gitignored. Nothing was corrupted there, but a `.txt` pinned as a source beside
  a same-stem PDF would have been silently replaced by this tool's own output, and every quotation
  would then have resolved against text the checker wrote.

  Narrowed to files sharing the source's stem rather than watching the whole directory, so an
  unrelated process writing there cannot trip it. Nothing is deleted: the file is named in the
  report and left where it is.
- The corpus size behind `readers.PREFERRED` is the one the measurement recorded. The README and
  `readers.py` justified preferring pypdf over pdfplumber with "1,792 passage checks", a number
  that appears in no artifact: `research/pdf-readers/results.json` records 1,593 checks over 80
  documents for the quotations corpus and 458 over 132 for the sampled one, and `verify.py` cited
  1,593 for the sibling claim in the same commit. Both now read 1,593, and both carry the
  agreement rates the artifact holds -- 92.7% against 90.2% -- so the sentence can be checked
  rather than believed.

  The preference itself was correct and is unchanged. What was wrong was the evidence cited for
  it, which is the failure these tools exist to catch.
- `fold` drops combining marks instead of composing them. A renderer typesets `naïve` as a dotless
  i carrying a combining diaeresis, which is how LaTeX writes it, while the quotation is typed with
  the precomposed letter; composing leaves those two different strings and the passage reads as
  absent. Seven quotations from one paper failed on that alone. The dotless `ı` and the dotted
  capital `İ` are mapped explicitly, since no normalization form reaches either.

  `skeleton` absorbs a hyphen joining two word characters, at least one a letter, together with any
  whitespace after it -- `prefix-matching` against `prefixmatching`, `non- sparse` against
  `nonsparse`, `pythia-1.4b` against `pythia1.4b` -- and an underscore, which is a subscript the
  extractor has already flattened. The bounds are the point: a minus sign is preceded by a space or
  by nothing, never by a word character, so `-0.42` and `0.42` stay distinct, and `5-3` is left
  alone where a range and a subtraction are indistinguishable.

#### Changed

- **[citations] A claims file states whose reading a characterization is, and the report says how many were not measured.** `verify` resolves the strings in `quotes` against the pinned bytes; nothing reads `statement`. A file whose quotation is exact and whose statement overreaches passed every check, and the report said nothing about the second object. `Interpretation` carries a required `whose`, and the report counts readings, those attributed to a party other than the source, and those marked contested — all as unchecked, because this package cannot measure them. ([#30](https://github.com/elliottower/reproducible-science/pull/30))
- A `not found` on a paginated source consults the remaining readers before it stands. `not found`
  is an accusation against the manuscript -- the source was read and the passage is not in it --
  and one reader was making it.

  `pdftotext -layout` preserves a page's visual geometry, so on a two-column paper it interleaves
  the columns and shreds every sentence spanning the gutter. Measured on one such paper: 110 of
  its 160 quotations read as absent under `-layout` and 157 resolve under pypdf, from a correctly
  pinned source with nothing wrong with the quotations.

  Whichever reader answers is recorded as a fallback naming the one that missed it, so a rescued
  passage never reads like one the declared reader found. Where no reader finds the passage, the
  detail names every reader that looked. The escalation is on the failure path alone: a passage
  the first reader resolves still costs one extraction, and `ambiguous` is never escalated, since
  a reader that merges columns could hide an occurrence rather than settle anything.
- A quotation is checked by counting its occurrences, where it was checked by testing whether the
  document contained it at all. A quotation points at one passage; a pointer resolving to three of
  them has identified none, and the page and section attached to it are then asserted about a
  passage nobody picked out. A passage occurring more than once is now `ambiguous`, a fifth state
  distinct from `indeterminate` -- the extractors disagreeing about what a document holds asks for
  a better reader, while a repeated passage asks for an anchor the author writes.

  `Quote` gains `prefix` and `suffix`, the W3C Web Annotation `TextQuoteSelector` neighbours. They
  are joined to the passage and counted in its place where it repeats, and are consulted nowhere
  else. Both default to empty, so a quotation that resolves uniquely is checked exactly as before.

  Counting respects token boundaries: `the catalog` inside `the catalogue` is a shared prefix and
  not the document saying it twice.

#### Added

- - **[citations] A PDF is readable without poppler, and every result names what read it.**
    `verify` shelled out to `pdftotext -layout` and returned `unchecked` where the binary was
    absent, so `pip install citations` could not check a PDF at all. Where poppler is missing or
    fails on a document, the chain now falls through to pypdf or pdfplumber and records the
    substitution as a fallback with its reason, so a result never rests silently on an extractor
    other than the one it names. A source declaring `extract_cmd` does not enter the chain: its
    author named the program that produces the text, so it runs or the check is `unchecked`.
    `citations verify --triangulate` asks every installed reader instead of one and reports
    disagreement as `indeterminate`, a fourth outcome that leaves the question open rather than
    asserting the passage is absent — extractors disagreeing is a fact about the readers, and
    `not found` is an accusation against the manuscript. ([#14](https://github.com/elliottower/reproducible-science/pull/14))
- - **[citations] A claims file's `extract_cmd` is read, and the report says what ran.** The
    field was declared on the model and documented in the claim-file example while
    `verify.extract` hardcoded `pdftotext -layout`, so a `.tex` manuscript reached a PDF reader
    and graded `unchecked` for every sentence in it. A source declaring `extract_cmd` is now
    read by the command it names: the source path replaces `{}` or is appended, and what the
    command prints to stdout is what the quotations resolve against. Every result carries the
    extractor and a sha256 of the text it produced, since a pin establishes that the bytes did
    not change and nothing about how they were read. The command is never handed to a shell —
    the declared string is split into a program and arguments — and only `pdftotext` and `detex`
    run unasked; anything else needs `citations verify --allow-extractor NAME`, written by
    whoever runs the check rather than by whoever wrote the file. A refused command and an
    uninstalled one are both `unchecked` and say which they are; neither makes the passage
    absent. ([#16](https://github.com/elliottower/reproducible-science/pull/16))
- A fetched document now records whether its length was checked against the extent Paperclip
  declared for it, on `Document.extent_verified` and in the `paperclip:` block a claims file
  carries. Where `tail -n 1` declares no last line the completeness check cannot run, and
  `lines` is then counted from what arrived rather than confirmed against what the source said
  it should be; the two cases were previously indistinguishable in the record.

  The field defaults to false, so anything that does not set it reads as unverified rather than
  claiming a check nothing performed. ([#18](https://github.com/elliottower/reproducible-science/pull/18))
- `citations coverage` asks the question `verify` cannot: is every quotation in the manuscript
  pinned at all? `verify` reads the claims files and takes no manuscript, so a quotation added to
  the paper and never pinned has no record, is checked by nothing, and leaves the report clean.

  ```console
  citations coverage paper/draft.tex --claims claims [--strict]
  citations coverage paper/draft.tex --claims claims --attribute
  ```

  Outcomes are `covered`, `uncovered` and `unresolvable`, reported separately rather than as a
  pass or a fail: a quotation too short to distinguish from noise, or one whose neighbouring
  source would not open, is undecided and not a defect in the manuscript. `--strict` fails on the
  undecided ones too, matching `verify`.

  `--attribute` additionally checks each quotation against the artifact of a source cited near it,
  which catches a passage credited to the wrong paper. It never reports a misattribution when any
  neighbouring source could not be read: the passage may belong to the one that would not open. ([#22](https://github.com/elliottower/reproducible-science/pull/22))
- **[citations] `citations pin` writes a quotation into a claims file and refuses one the source does not contain.** A claims file is written by hand and read by `verify` afterwards; between those two moments sat a passage transcribed from a viewer whose ligature or line-wrapped hyphen differs from what the extractor produces. That was reported later, over a corpus, against a file nobody had open. It is now refused at the moment of writing. ([#31](https://github.com/elliottower/reproducible-science/pull/31))
- **[citations] `citations projects` reports which project names nothing answers to, and `citations tags` groups records against a declared vocabulary.** Ninety records named `evaluation-scope` hours after that repository was renamed and nothing reported it, because `cited_by` is a free-text key no check compared against the projects that exist. Tags are declared on a paper in `papers.yaml` and reach records through `cited_by`, so a work a paper cites tomorrow carries them without anything being re-run. ([#38](https://github.com/elliottower/reproducible-science/pull/38))
- **[citations] A record can name the citation key a new bibliography should use.** `cited_by` records what each paper actually writes and those diverge honestly, since a key is part of a paper's own source. Naming the divergence without naming a winner left the reader to pick one, which is how the divergence started. ([#41](https://github.com/elliottower/reproducible-science/pull/41))
- - **[citations] `citations add` writes an entry into a `.bib` and refuses a key the file
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
- A `not found` says where the passage stopped matching, and what the source reads there.

  `not found` is an accusation against the manuscript: the source was read and the passage is not
  in it. It is usually wrong, and the cause is usually one character the document's text layer
  dropped -- a minus sign, an en dash, a hyphen falling on a line break where `fold`'s
  de-hyphenation removes a real one. Finding that meant a binary search for the longest prefix of
  the quotation the document still contains, done by hand, three times in one corpus.

  `divergence(quote, text)` does that search, and the report shows both sides at the point they
  part:

  ```text
  the first 155 characters are in the source and the rest is not
        quoted: ...tionality, e.g. vec('king') - vec('man') + vec('woman') = vec(
        source: ...tionality, e.g. vec('king') vec('man') + vec('woman') = vec('q
  ```

  with the repair named: split the quotation into adjacent fragments either side of the missing
  character, never truncate it to the part that matches, because a truncated quotation resolves
  and says something its source does not.

  Reported only where the prefix is substantial -- forty characters, or half the quotation. A
  shorter one matched by coincidence, and pointing at where it ran out sends a reader to a passage
  the quotation was never taken from. `packages/citations/README.md` collects the four causes.

### prereg

No significant changes.

### results-cli

#### Added

- **[results-cli] `results seal` accepts a directory and records it as a tree.** A dataset is a directory, so sealing one meant naming every file it contained, and a file added afterwards was simply absent from the record with nothing to notice. The seal looked complete and was not. A tree digest is order-independent and covers every path, and `verify` re-derives it the way it was recorded. ([#37](https://github.com/elliottower/reproducible-science/pull/37))
- **[results-cli] `results verify` says when the ledger is not in history.** `citations` reports a record that is not committed, because a pin nobody else can read is not evidence anyone can appeal to; `results` makes the same promise about its ledger and said nothing. Reported after the chain verifies, never blocking. ([#45](https://github.com/elliottower/reproducible-science/pull/45))

### reproducible-science

#### Fixed

- **[repro] `repro verify` no longer prints a blank line under a regeneration section that said
  nothing.** The separator was printed whenever a manifest declared a regeneration, and the
  ordinary state — not requested, since regeneration runs only under `--regenerate` — is the one
  state the section says nothing about. ([#26](https://github.com/elliottower/reproducible-science/pull/26))
- **[reproducible-science] `repro check` finds a paper's claims where papers keep them, and tells `citations` where they are.** A project holding sixty-one pinned quotations at `paper/prior_art/claims` was told no tool applied to it, because detection looked only at the repository root. A project with `claims/` at its root fared worse: the check ran `citations verify` with no claims directory, which reports nothing to check and exits 2, so it was reported as FAILED. ([#44](https://github.com/elliottower/reproducible-science/pull/44))
- **[reproducible-science] The cross-tool report names the claim it is about.** `results` records a claim's text under `claim`; this read `claim_id` and then `id`, neither of which it has ever written, so every claim printed as `?`. The tests wrote `claim_id` themselves, so the reader agreed with the fixtures and neither had to agree with the writer.

#### Changed

- **[reproducible-science] A tool is detected by what it can act on, not by a directory name.** `claims` is an ordinary word: a Python package and a knowledge-graph registry were both read as citations projects and then failed for holding no quotations. `prereg check` looks for a file named `PREREG.md`, while detection looked for a directory named `preregs`, so a directory of hand-named plans was reported as a project whose registrations were broken. An empty directory no longer counts as use. ([#45](https://github.com/elliottower/reproducible-science/pull/45))

#### Added

- **[repro] `repro demo` writes a worked example and runs the real workflow over it.** The first
  five minutes previously required reading the specification to find out what a manifest is for.
  `repro demo` scaffolds a self-contained project — twelve paired measurements, a stdlib analysis
  seeded so the same numbers come out on every machine, a manuscript stating one of them, and a
  `pin.py` that writes the manifest — then drives `results init`/`seal`/`run`/`claim` and
  `repro verify` over it, printing each command and what it actually returned.

  It then breaks the project twice, because a walkthrough where everything passes shows nothing
  about what the report keeps apart. A word no assertion reads is edited: every assertion still
  holds, the run fails on the pin alone, and the two decisions over that file come back marked
  non-authoritative. The manifest is re-pinned, the number the manuscript reports is changed, and
  the manifest re-pinned again — so the pin is clean and the comparison is the only thing left to
  fail. Both edits are restored, and the directory is left verifying, with a README naming three
  more failures worth producing by hand.

  Offline throughout, and it refuses a directory that already holds files unless `--force` is
  given, which removes only the files the demo itself writes. ([#26](https://github.com/elliottower/reproducible-science/pull/26))
- **[reproducible-science] `repro` runs the four tools, and `repro check` runs the ones a project uses in one pass.** Each tool keeps its own command; the delegation is a spelling. What only exists here is one pass over a project, one report and one exit code across every tool it actually uses, in place of four commands each with its own idea of a clean run. A tool the project does not use is reported as unused rather than as passing. ([#35](https://github.com/elliottower/reproducible-science/pull/35))

### provenance-core

#### Fixed

- `gitref` now runs git against the directory the caller names. Git resolves its repository from
  the environment before the working directory, so `cwd` alone never named one: under any git
  hook, which exports `GIT_DIR`, `commit(path)` and `is_dirty(path)` answered for whatever
  repository invoked the process. `repro.provenance.of_tree` is built on those calls, so a
  provenance record written from a hook named the wrong repository's commit and dirty state.

  Only the variables that relocate git are dropped -- `GIT_DIR`, `GIT_WORK_TREE`,
  `GIT_INDEX_FILE` and the rest of `gitref.REDIRECTS`. `GIT_SSH_COMMAND`, `GIT_COMMITTER_DATE`
  and the other variables that configure git once it knows where it is are untouched, and a
  caller passing no `cwd` still inherits everything. `gitref.clean_env()` exposes the same
  environment to callers that run git themselves.

  `results.timeline.freeze_timestamp` used `git -C`, which is a directory change and is outranked
  the same way; it now goes through `gitref`. ([#20](https://github.com/elliottower/reproducible-science/pull/20))

## 0.3.1 — 2026-08-26

Four corrections to `citations`, all of them defects introduced by the `extract_cmd` support
that shipped hours earlier in 0.3.0. Each was found by running the new code over real claim
sets, and each made a source unverifiable rather than merely awkward.

### Fixed

- **[citations] A source declaring that it needs no extractor was refused as a program named
  `none`.** `paperclip.source_block` writes `extract_cmd: none` for a pinned text artifact,
  because naming an extractor would claim a step that never ran; `verify` then read that as a
  command, refused it, and advised `--allow-extractor none` — running a program that does not
  exist. Every source written by `citations resolve --via paperclip` and `citations
  import-paperclip` came back `unchecked` in 0.3.0. The declaration is now recognized, and
  matched on its first word so the reason an author writes beside it (`none -- Markdown is read
  directly`) is read as the declaration rather than as a command. ([#24](https://github.com/elliottower/reproducible-science/pull/24))
- **[citations] A passage separated by U+2010 HYPHEN read as absent from a document containing
  it.** `fold` normalized the em dash, the en dash and the minus sign but not U+2010, which is
  visually identical to the ASCII hyphen and is what publishers emit: a source reading
  `patients‐in‐waiting` did not match a quotation typed with the ASCII hyphen, and the result was
  `not found` — an accusation against the manuscript — for a quotation that is verbatim correct. ([#24](https://github.com/elliottower/reproducible-science/pull/24))
- **[citations] An extractor that wrote to the file it was given damaged the artifact silently.**
  A declared `extract_cmd` is an arbitrary program handed a path, and nothing stopped it writing
  where it read: a renderer whose output filename matched its input overwrote the bytes the pin
  names, and the pin then failed against a file the checker itself had damaged. `verify` reads
  and never writes, so the artifact's digest is now taken before and after a declared command
  runs and a change is reported as a defect in the command. ([#24](https://github.com/elliottower/reproducible-science/pull/24))
- **[citations] A declared command that printed nothing reported `no text extracted`,** which is
  what a document holding no text also reports — the two facts the three-outcome model exists to
  keep apart, given one message. An empty stdout from a command that exited 0 now says so, and
  where the command is `pdftotext` without a trailing `-` it names that: `pdftotext FILE` writes
  `FILE.txt` and prints nothing, which is how ten sources in one claim set read as textless. #
  Changelog Every package in this workspace carries the same version and is released on the same
  day, so one file covers all four. Entries are scoped with a `[package]` prefix; unprefixed
  entries apply to the workspace as a whole. ([#24](https://github.com/elliottower/reproducible-science/pull/24))

## 0.3.0 — 2026-08-26

Corrections come first. Two of them changed what the tools reported: a confirmatory claim was
ordered against an exposure by comparing timestamp *strings*, so the answer depended on the
committer's time zone, and a provenance record written from inside a git hook named the wrong
repository entirely. A third, under Changed, is not a defect but will move results: a claims
file's `extract_cmd` was accepted and ignored, and is now run.

### Fixed

- **A release could ship packages pinned to different sibling series, and neither `bump` nor
  `check` could see it.** `scripts/versions.py` located the dependency array with a pattern
  ending at a line-initial `]`. That matched neither of the two forms the manifests actually use
  reliably: in `prereg`, a single-line array with no later array to close on, it did not match at
  all, so `bump 0.3.0` moved every package's version and left `prereg` requiring
  `provenance-core>=0.2,<0.3`; in `citations`, it ran past the array's own bracket to the one
  closing `classifiers`. `check` read the same way and reported lockstep. The array's end is now
  found by balancing brackets, and the wheel install that caught it is covered by a test. ([#23](https://github.com/elliottower/reproducible-science/pull/23))
- **[results] A freeze and an exposure were compared as strings, so the ordering depended on the
  committer's time zone.** `--frozen-at` resolved a commit through git's `%cI`, which carries a
  local UTC offset, and compared it with the ledger's UTC timestamp using `<` on the two strings
  — comparing the offsets rather than the instants. It passed on a machine four hours behind UTC,
  where the local hour is numerically smaller, and failed on a runner in UTC, where the ordering
  fell to whether `+` or `Z` sorts before `.`. Both are now parsed to instants before comparison.
  A claim recorded as confirmatory on a machine east of UTC should be re-checked. ([#5](https://github.com/elliottower/reproducible-science/pull/5))
- **[citations] Cleaning a BibTeX field deleted the argument of every markup command except
  `\emph`.** Braces were stripped before control sequences, so `\texttt{inspect\_ai}` became
  `\textttinspect\_ai` and the command pattern then matched through the start of the argument. A
  record naming the exact package versions an evaluation ran on was written out as *Python
  packages _ai 0.3.260 and _cyber 0.1.0*. Control sequences are now resolved first, and the
  whitespace after a command is kept where the result is displayed — removing it turned
  `Smith\etal Jones` into `SmithJones`. ([#8](https://github.com/elliottower/reproducible-science/pull/8))
- **[provenance-core] `gitref` ran git against the repository the environment named, not the
  one the caller did.** Git resolves its repository from
  the environment before the working directory, so `cwd` alone never named one: under any git
  hook, which exports `GIT_DIR`, `commit(path)` and `is_dirty(path)` answered for whatever
  repository invoked the process. `repro.provenance.of_tree` is built on those calls, so a
  provenance record written from a hook named the wrong repository's commit and dirty state.

  Only the variables that relocate git are dropped -- `GIT_DIR`, `GIT_WORK_TREE`,
  `GIT_INDEX_FILE` and the rest of `gitref.REDIRECTS`. `GIT_SSH_COMMAND`, `GIT_COMMITTER_DATE`
  and the other variables that configure git once it knows where it is are untouched, and a
  caller passing no `cwd` still inherits everything. `gitref.clean_env()` exposes the same
  environment to callers that run git themselves.

  `results.timeline.freeze_timestamp` used `git -C`, which is a directory change and is outranked
  the same way; it now goes through `gitref`. ([#20](https://github.com/elliottower/reproducible-science/pull/20))
- Test helpers across `prereg` and `results` ran git with an inherited environment, which
  wrecked the checkout they ran in. Under
  `pre-commit`, which exports `GIT_INDEX_FILE` while it stashes, their `git add -A` staged into
  the *outer* worktree's index and left every tracked file there staged as deleted -- a wrecked
  checkout produced by a passing test, with `pytest -n auto` workers racing on the one index.
  They now build their environment with `gitref.clean_env()`.

### Changed

- **[citations] A claims file that declares `extract_cmd` now behaves differently, and existing
  ones may need editing.** The field was accepted and ignored: every source was read by
  `pdftotext -layout` or, for a `TEXT_SUFFIXES` file, straight off disk. It is now run. A
  repository that declared a command which is not a per-source extractor will see its
  quotations move — a batch regeneration script that prints a summary and ignores the path
  yields `not found` for every passage, and a command outside the default allowlist yields
  `unchecked` until `--allow-extractor` names it. Both were found in real claim sets on the
  upgrade. Check `citations verify` before and after: a source whose bytes on disk are already
  the text being quoted should declare no `extract_cmd` at all, or `none`. ([#16](https://github.com/elliottower/reproducible-science/pull/16))

### Added

- **[results] `results coverage` reads a manuscript and says which of its numbers are bound.**
  Given a paper and a sealed run, it enumerates every numeric token, sorts each into traceable
  (table cells, measurements, parameters, equation content), untraceable (bibliographic and
  structural furniture), or reported-separately (figure axes, dense lines, orphans, bounds,
  extraction failures), and reports how many of the traceable ones a claim already binds. The
  third group is never folded into the other two: a limit of the scanner is not a property of
  the article. ([#3](https://github.com/elliottower/reproducible-science/pull/3))
- **[results] A plan frozen before the results were seen protects a confirmatory claim.**
  `results claim --confirmatory` refused whenever its run postdated an `outcomes seen` event,
  which treats exposure as decisive. Exposure is evidence that contamination was possible;
  propagation is what threatens a confirmatory reading, and a plan already committed cannot be
  reached by an exposure that follows it. `--frozen-at <commit>` names a commit containing the
  frozen plan; where its commit date precedes the first exposure the claim records as
  confirmatory with `after_outcomes_seen` false, and `verify` lists it separately rather than
  silently among the rest. ([#4](https://github.com/elliottower/reproducible-science/pull/4))
- **[citations] Full text through Paperclip, pinned by digest.** `citations resolve --via paperclip <doi>` fetches a source's full text from [Paperclip](https://paperclip.gxl.ai), writes it to `sources/paperclip/` and pins those bytes by sha256; `citations import-paperclip <repo>` does the same for every paper in a Paperclip paper repo and carries its committed claims across as statements. Verification stays offline against the pinned copy, so Paperclip never decides whether a quotation matches. An identifier with no open-access full text, a document that arrives incomplete, and a missing `citations[paperclip]` extra all leave the source unpinned, so their quotations read `unchecked` rather than `not found`. ([#10](https://github.com/elliottower/reproducible-science/pull/10))
- **[citations] A PDF is readable without poppler, and every result names what read it.**
  `verify` shelled out to `pdftotext -layout` and returned `unchecked` where the binary was
  absent, so `pip install citations` could not check a PDF at all. Where poppler is missing or
  fails on a document, the chain now falls through to pypdf or pdfplumber and records the
  substitution as a fallback with its reason, so a result never rests silently on an extractor
  other than the one it names. A source declaring `extract_cmd` does not enter the chain: its
  author named the program that produces the text, so it runs or the check is `unchecked`.
  `citations verify --triangulate` asks every installed reader instead of one and reports
  disagreement as `indeterminate`, a fourth outcome that leaves the question open rather than
  asserting the passage is absent — extractors disagreeing is a fact about the readers, and
  `not found` is an accusation against the manuscript. ([#14](https://github.com/elliottower/reproducible-science/pull/14))
- **[citations] A claims file's `extract_cmd` is read, and the report says what ran.** The
  field was declared on the model and documented in the claim-file example while
  `verify.extract` hardcoded `pdftotext -layout`, so a `.tex` manuscript reached a PDF reader
  and graded `unchecked` for every sentence in it. A source declaring `extract_cmd` is now
  read by the command it names: the source path replaces `{}` or is appended, and what the
  command prints to stdout is what the quotations resolve against. Every result carries the
  extractor and a sha256 of the text it produced, since a pin establishes that the bytes did
  not change and nothing about how they were read. The command is never handed to a shell —
  the declared string is split into a program and arguments — and only `pdftotext` and `detex`
  run unasked; anything else needs `citations verify --allow-extractor NAME`, written by
  whoever runs the check rather than by whoever wrote the file. A refused command and an
  uninstalled one are both `unchecked` and say which they are; neither makes the passage
  absent. ([#16](https://github.com/elliottower/reproducible-science/pull/16))
- **[repro] A `correspondence` assertion compares two artifacts, and a `prose` locator addresses
  a value in a document.** Every other kind compares an artifact against a literal written in the
  manifest, so a claim a document makes about the code beside it required transcribing one side
  into `reported`, where nothing checks it: rewriting each such field to the measured value
  passes a manifest whose documents are still wrong. A correspondence reads both sides and
  compares them, privileging neither — when they disagree the decision reports both values and
  names neither as wrong. A side that does not extract makes the comparison impossible rather
  than false, so a gap on one side reports as `not_found` and never as `mismatch`.

  The `prose` locator addresses the value between two literal anchors in a document's extracted
  text. No pattern searches for a number: the author declares where the value sits, which is why
  it is an address rather than a recovery. `form: cardinal_word` reads an English cardinal
  written out; without it, a spelled-out number is refused as `number_as_word` rather than
  reported as missing. ([#17](https://github.com/elliottower/reproducible-science/pull/17))
- **[citations] A fetched document records whether its length was checked** against the extent Paperclip
  declared for it, on `Document.extent_verified` and in the `paperclip:` block a claims file
  carries. Where `tail -n 1` declares no last line the completeness check cannot run, and
  `lines` is then counted from what arrived rather than confirmed against what the source said
  it should be; the two cases were previously indistinguishable in the record.

  The field defaults to false, so anything that does not set it reads as unverified rather than
  claiming a check nothing performed. ([#18](https://github.com/elliottower/reproducible-science/pull/18))
- **[citations] `citations coverage` asks the question `verify` cannot: is every quotation in
  the manuscript pinned at all?** `verify` reads the claims files and takes no manuscript, so a quotation added to
  the paper and never pinned has no record, is checked by nothing, and leaves the report clean.

  ```console
  citations coverage paper/draft.tex --claims claims [--strict]
  citations coverage paper/draft.tex --claims claims --attribute
  ```

  Outcomes are `covered`, `uncovered` and `unresolvable`, reported separately rather than as a
  pass or a fail: a quotation too short to distinguish from noise, or one whose neighbouring
  source would not open, is undecided and not a defect in the manuscript. `--strict` fails on the
  undecided ones too, matching `verify`.

  `--attribute` additionally checks each quotation against the artifact of a source cited near it,
  which catches a passage credited to the wrong paper. It never reports a misattribution when any
  neighbouring source could not be read: the passage may belong to the one that would not open. ([#22](https://github.com/elliottower/reproducible-science/pull/22))
- **[repro] Every decision records the extraction toolchain and the digest of what it
  produced.** `backend_version` is a protocol string naming a backend's interface, so a
  `pdftotext` upgrade that resolved a ligature differently changed an extracted passage while
  the artifact's digest held and the report read `backend_version: "1"` on both sides of it.
  A decision now carries `tool` and `tool_version` — the binary's version as it prints it, or
  the installed distribution's for the format adapters — and `extraction_digest`, the sha256
  of the whole extracted text for a quotation and of the extracted value for a number. The
  version says why a reading changed; the digest catches a change from any cause, including a
  rebuilt binary reporting the same version. A version or digest that was sought and not
  obtained is recorded as `unknown`, so it stays distinguishable from one never sought. The
  fields are provenance: no outcome moves, and whether a changed toolchain should break a pin
  is left to policy.

## 0.2.0 — 2026-08-24

First release from the monorepo. The four packages previously released separately from their
own repositories; they now share one version, one lockfile and one release.

Several entries below are corrections to results the tools reported. They are listed first
because a verifier that reports a clean run it did not earn is worse than one that fails.

### Fixed

- **[citations] A quotation matched a source that contradicted it.** The fallback used when a
  verbatim match fails stripped every non-alphanumeric character, so `p < 0.05` resolved
  against a source reading `p = 0.05`, and `-0.42` against `0.42`. It now removes whitespace
  and nothing else, which is what a PDF extractor actually mangles.
- **[citations] A source edited after being pinned still passed.** Every quotation was checked
  against the file on disk and nothing compared it to the recorded digest, so a changed source
  produced a clean run. A broken pin now fails the run and is reported before the quotation
  results, because it changes how they should be read.
- **[citations] `--strict` did not fail on unresolved quotations.** A deleted source, an
  unpinned one, an unparseable claims file and a missing `pdftotext` all left a build green
  while nothing had been verified.
- **[citations] BibTeX entries were split with a regex** that dropped or merged entries
  containing nested braces. Entries are now separated by counting braces.
- **[results] The ledger could be extended after being tampered with.** `append_event` built
  on a chain already reported as edited and re-anchored over the evidence, so a damaged
  ledger verified clean from the next ordinary command onward. It now refuses.
- **[results] Truncating the ledger and re-anchoring was a two-command clean bill of health.**
  `reanchor` now refuses a chain reported as truncated, which is the cheapest tampering there
  is: no line has to be forged, so the hash chain stays intact and only the count disagrees.
- **[results] `verify --files` reported a deleted sealed file as `ok`**, and reported a path
  sealed under several different hashes as `ok` when the file matched any one of them.
- **[prereg] `freeze` proceeded when there was no commit to name.** `git()` returns empty on
  any non-zero exit, so a missing binary, a locked index and a directory outside a repository
  all read as success, and a freeze recorded a commit-shaped string in place of a commit.
- **[prereg] The log was editable after freezing.** The plan hash deliberately stops at the
  log, which left the only record of what changed after registration freely deletable while
  `check` still reported the plan unchanged. Entries are now chained, with an anchor
  recording the length so a removal from the end is visible.
- **[prereg] `check` passed at a repository root when a plan below it was never frozen**, so
  whether an unfrozen registration passed CI depended on which directory it ran from.
- **[repro] A structured array element resolved as a single value.** A two-field record
  stringified as `(0.91, 0.02)` and was reported as one extracted value, so a manuscript
  reporting `0.91` could verify against a record rather than a number.
- **[repro] A passage found on the wrong page reported as verified.** The page was recorded as
  a warning, and no policy reads decision warnings, so the assertion was unenforceable.
- **[repro] Duplicate artifact and claim ids silently kept the last declaration**, which could
  drop a broken pin from the report entirely and leave the strict policy passing with no
  violations at all.
- **[repro] Duplicate keys in JSON resolved to whichever came last**, so one artifact could
  hold two values for one quantity and address one of them with nothing said about the other.

### Added

- **[repro] Conformance fixtures now pin the reason and the artifact validity**, not only the
  outcome. Four cases share the outcome `unchecked` and three share `not_found`; without the
  reason, a defect in the tool and a fact about the manuscript were indistinguishable.
- **[repro] A `broken_pin` conformance case**, which the fixture set named in its skip list
  but never contained.
- **Coverage is measured and gated at 70%.** Most suites drive a CLI in a real subprocess,
  which coverage does not follow by default, so the CLI modules reported 0–18% while their
  tests passed.
- **Dependency floors are resolved in CI** (`--resolution lowest-direct`), which found two
  declared minimums that could not be installed at all.
- **Lockstep versioning is enforced** by `make versions`: every package carries one version
  and pins its siblings to that series.

### Changed

- **Restructured as a uv workspace.** One lockfile, four packages, one release.
- **Python 3.11 is now required.**
- **[citations] [repro] Raised `pyyaml` to `>=6.0.2` and `pydantic` to `>=2.9`.** The previous
  floors resolved to versions that fail to build on current Python.
