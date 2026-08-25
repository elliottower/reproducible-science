# A catalog of reproducibility defects

Each entry is a defect class these tools have caught in real work, with the instance that
produced it. The purpose is a stable identifier: a defect with a number can be searched for,
recurred against, and closed, where the same defect described in prose each time reads as a
new problem every time.

Entries are numbered `RD-nnn` and never renumbered. A class that turns out to be wrong is
marked withdrawn and keeps its number.

| | |
|---|---|
| **Pinning and extraction** | RD-001 – RD-005 |
| **Repository structure** | RD-006 – RD-011 |
| **Manuscript** | RD-012 – RD-015 |
| **Tooling** | RD-016 |

---

## Pinning and extraction

### RD-001 — Quotation ends at a word the source breaks across lines

**Detected by** `citations verify` (`not found`, or `truncated` where a prefix still matches).

A quotation copied out of a PDF ends on the first half of a hyphenated word, because that is
where the line ended. The verifier rejoins the word before comparing, so the source no longer
contains the fragment. Extending the quotation through the word does not repair it either: at
that point the source holds the rejoined form, not the hyphenated one.

The only form that matches is one trimmed to before the broken word.

**Observed.** A pin ended `...from a publicly-`, against a source reading `publicly-\naccessible`.
`fold()` applies `re.sub(r"-\s*\n\s*", "", s)`, so the source became `publiclyaccessible` and
both `publicly-` and `publicly-accessible` failed. Three pins in one file carried this.

### RD-002 — Line numbers interleaved into words

**Detected by** `citations verify` (`truncated`).

Legislative and regulatory documents print line numbers in the margin, which a text extractor
places inline. A word broken across two numbered lines reaches the extractor with the number
inside it, so no quotation spanning that break can match.

**Observed.** `technology` in a congressional bill extracted as `tech16 nology`. The repair is
to end the quotation before the break, since the intervening number is not in the document as
a reader sees it.

### RD-003 — Pin weaker than the quotation the manuscript prints

**Detected by** comparing the pinned string against the manuscript's own quoted text.

The pin verifies, so nothing reports an error, but it covers less than the sentence the paper
prints. The paper's quotation is then unpinned in its final clause — the part most likely to
carry the qualification a reader would check.

**Observed.** A pin ended `the importance of the omitted procedure` where both the source and
the manuscript read `procedure(s)`. The plural is the substantive part: it is what makes the
standard's test apply to a set of omitted procedures rather than to one.

### RD-004 — Verified evidence the manuscript never cites

**Detected by** intersecting the citation keys in `claims/` with those cited in the `.tex`.

An orphan pin is not an error and not stale. It is evidence gathered, checked, and then not
used, which is worth knowing because the decision to leave it out should be deliberate.

**Observed.** Four verified quotations recording a published capability score corrected from
`pass@4` 0.4% to 1.48%, the original figure having been a `pass@1` measurement. On topic for
the paper holding it, cited nowhere in it.

### RD-005 — A source named by hash and by nothing else

**Detected by** checking each pin for a field naming where the source can be obtained.

A content hash establishes that two parties hold the same bytes. It does not tell a reader
where to get them. A pin carrying only a hash and a path into the author's filesystem is
checkable by the author and by nobody else.

**Observed.** Forty-eight pins, none carrying a URL. Twenty-three were resolvable from the
bibliography, seven more from the citation library's own records, two from arXiv identifiers
recorded in `note` fields, and six by fetching the candidate page and confirming a distinctive
string from the pinned text appeared on it.

---

## Repository structure

### RD-006 — A split that separates pins from the sources they resolve against

**Detected by** running `citations verify` after any move of `claims/`.

`Claims.artifact()` resolves `local:` against the parent of the claims directory. Moving
`claims/` to another repository therefore repoints every pin at a directory that is not there,
and the failure is total and silent until something verifies.

**Observed.** A repository split to remove non-redistributable sources from a public artifact
carried `claims/` across and left `reading/` behind. All 48 pins broke at once. The sources
were intact and every hash still matched; only the path root had moved.

**Repair.** A gitignored symlink from the new repository to the old, which is the arrangement
the citation library already uses for its own artifacts: bytes live in one place, everything
else points at them, nothing is copied.

### RD-007 — A figure computed by globbing every repository on the machine

**Detected by** regenerating a figure on a machine whose other repositories have changed.

A census that globs `~/*/claims/*.yaml` makes every published number in one paper a function
of the state of every other project on disk. A change in an unrelated repository moves a
figure the paper prints, and the paper's own verification reports drift that has nothing to do
with the paper.

**Observed.** A repository split in one project moved four figures in a different project's
paper and failed `repro verify --policy strict` there. The drift was real and the numbers were
correct; the coupling is the defect.

### RD-008 — The same directory counted twice

**Detected by** a census whose total exceeds the number of distinct records.

Copying a directory rather than moving it leaves two copies, and any tool that enumerates by
glob counts both. The two then diverge, and the newer one is not necessarily the one a reader
finds.

**Observed.** A `claims/` directory present in both a working repository and the public one
split from it. The census read 413 where the paper printed 366, the difference being exactly
the 48 duplicated pins. The public copy was the newer, carrying URL fields the other lacked.

### RD-009 — An ignore rule defeated by a suffix

**Detected by** listing tracked files against the intent the ignore file states.

`reading/**/*.pdf` excludes `document.pdf` and does not exclude `document.pdf.bak`. The rule
reads as a statement of policy and functions as a pattern match, and the gap between the two
is invisible until something is listed.

**Observed.** A `.gitignore` carrying the comment *"Copyrighted. Fine on disk for reading;
must not be redistributed"* above `reading/**/*.pdf`, with a 3.6 MB third-party PDF tracked
under a `.pdf.bak` name.

### RD-010 — Untracking is not removal

**Detected by** `git log --all -- <path>` after `git rm --cached`.

Removing a file from the index removes it from the working tree of future clones and leaves it
in history, recoverable by anyone with the repository. For a file excluded on licensing
grounds this is the difference between compliance and its appearance.

**Observed.** The PDF of RD-009, untracked at HEAD and still present at an earlier commit.
Removing it for real requires rewriting history.

### RD-011 — A rename that does not reach the index pointing at it

**Detected by** grepping a citation library for repository names that no longer exist.

Cross-references keyed by repository name go stale on rename, and nothing fails: the records
are still valid, they simply describe a repository nobody can find.

**Observed.** Eighty-two library records keyed to a repository name three weeks after the
rename, and zero keyed to the current one.

---

## Manuscript

### RD-012 — Numerals left behind by an added case

**Detected by** grepping every numeral that counts the study's own units, and reading each hit.

Adding a case updates the tables, which are generated, and leaves the prose, which is not.
Automated replacement is the wrong repair, because the same numeral legitimately counts other
things in the same document.

**Observed.** A fifth record added to an audit left `four` in seven places, including a section
heading and a sentence that announced five claims and then listed four. Fourteen further
occurrences of `four` in the same document were correct and had to be read to establish it —
four claimant parties, four coupled samples, twenty-four surveyed reports, a four-year remedy.

### RD-013 — A contributions list restating the paragraphs above it

**Detected by** reading the list against the preceding section.

Each item paraphrases a paragraph the reader has just read, so the section costs a page and
adds nothing. It is invisible in drafting because the list is written last, from the prose,
which is exactly what makes it redundant.

**Observed.** A four-item list whose second item gave a result stated eight lines earlier in
the same words. Removing the list recovered most of a page from a paper one page over its
limit.

### RD-014 — A bibliography entry type the style file does not define

**Detected by** reading `bibtex` output rather than only the `.log`.

`bibtex` reports an undefined entry type as a warning and renders the entry anyway, dropping
whichever fields the style has no rule for. The build succeeds, the citation resolves, and a
field the author supplied is silently absent from the output.

**Observed.** `@software` under a style file defining no such type. The entry rendered, and
the DOI did not appear in it.

### RD-015 — A self-citation that de-anonymizes through its URL

**Detected by** reading the rendered bibliography of a blind submission for links to
author-controlled hosts.

Citing one's own work in third person is required rather than prohibited, and a name in a
reference list is not a disclosure. A URL pointing at the author's own account is, and it
arrives through the bibliography rather than through the body, where anonymization passes
usually look.

**Observed.** A software citation printing a repository URL containing the author's username.
The repair is to cite the archived identifier, which is the citable form and names no account.

---

## Tooling

### RD-016 — A tool implementing a superseded version of the instrument

**Detected by** comparing the tool's vocabulary against the instrument the paper defines.

A tool written alongside a paper encodes the instrument as it stood that week. The paper's
instrument then changes and the tool does not, so it validates against a design the paper no
longer describes while continuing to pass its own tests.

**Observed.** A checker enforcing a sixteen-criterion structure after the paper it accompanied
had replaced that structure with six dimensions over three operations. Every test passed.
