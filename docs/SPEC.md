# The evidence contract, v1

Draft. The version marker exists so a manifest can say which revision it was written against.

## 0. Scope

**This specifies the verification of evidence assertions, not of scientific claims.**

An evidence assertion is a proposition about an artifact: *this passage occurs in this file*,
*this file holds this value at this location*. A verifier here establishes whether that
proposition holds against bytes with a known hash.

It does not establish that the evidence supports the sentence citing it. A source can contain
a quotation verbatim while the quotation fails to support the claim it is offered for, and a
passage can be absent while the claim is true and supported elsewhere. Entailment between
evidence and claim is the subject of the claim-verification literature (FEVER, SciFact) and is
addressed there with model-based methods. Nothing in this document produces a judgment about
it.

This is why the outcome vocabulary is `match` and `mismatch` rather than `supported` and
`refuted`. Those name a semantic relation; a byte comparison does not establish one.

## 1. Objects

| object | frozen | what it is |
|---|---|---|
| `Digest` | yes | a content address: `sha256` and 64 lowercase hex characters |
| `ArtifactRef` | yes | a file the manifest names, pinned or not |
| `Evidence` | yes | an assertion about one artifact, two, or a declared list, discriminated on `kind` |
| `Claim` | yes | a manuscript statement and the evidence offered for it |
| `Manifest` | yes | one project's artifacts and claims |
| `Decision` | yes | the outcome of evaluating one assertion |
| `DecisionSide` | yes | what one side of a two-sided assertion read, and where |
| `DecisionMember` | yes | what one member of an aggregate read, and where |
| `VerificationReport` | yes | every decision, and the state of every artifact |
| `Assessment` | yes | a policy's verdict on a report |

Everything is frozen. A decision that can be edited after the fact records nothing, and a
manifest whose path can be reassigned resolves relative artifact paths against whichever
directory was set last.

Every `Claim` has a `digest` over its identity, text, and location. Every `Decision` names the
claim digest it evaluated, so a stored decision cannot silently remain attached to text that
has since been edited.

## 2. Artifacts and pins

`ArtifactRef` carries a `digest` or does not. The two cases are reported separately, and an
unpinned artifact is never treated as verified: no hash was recorded, so nothing about the
file is confirmed.

| state | `Validity` | meaning |
|---|---|---|
| digest matches | `authoritative` | the file is the file that was pinned |
| digest differs | `broken_pin` | the file read is provably not the file declared |
| no digest | `unpinned_artifact` | nothing about the file is confirmed |
| no file | `artifact_absent` | nothing is at the declared path, so no assertion against it read anything |

Pins are resolved before any evidence is read. Decisions computed against a broken or unpinned
artifact still run and are still reported, marked with that validity, because a diagnostic is
more useful than a blank — but they are not authoritative and a policy may reject the report
on the pin alone.

An artifact declares its digest once. Evidence refers to an artifact by id and never repeats a
digest, so there is one source of truth per file.

## 3. Evidence kinds

### 3.1 `quote`

```yaml
kind: quote
artifact: paper-source
text: "Model A exceeded Model B by 3.2 percentage points"
prefix: "In the held-out split, "   # optional: the text immediately before the passage
suffix: " on the primary metric"    # optional: the text immediately after it
section: "Results"      # recorded, never verified
page: 4                 # checked where the artifact is read page by page
```

Assertion: this passage occurs in the extracted text of this artifact, after the passage and
the text are normalized the same way. Unicode is decomposed to NFKD and combining marks are
dropped, so a ligature becomes its letters and an accented letter matches its unaccented form:
`Krzyżosiak` matches `Krzyzosiak`. Dotless `ı` and dotted `İ` become `i` and `I`. Curly
quotation marks become straight ones, and the em dash, en dash, minus sign and U+2010 hyphen
become `-`. A hyphen at a line break between two letters is removed with the break and any other dash at
a line end is kept, runs of whitespace collapse to one space, and case is ignored. A control character becomes a space and is not deleted, because
deleting one welds the words on either side into one appearing in neither text.

A passage that does not occur under that normalization is looked for once more with all
whitespace, underscores, and any hyphen joining two word characters removed. One found only
that way is `verified` and carries the warning `normalized`. Other punctuation is kept in both
passes, so `p < 0.05` does not match `p = 0.05` and `-0.42` does not match `0.42`.

`page` is checked where the artifact is read page by page and the passage matched under the
first normalization: a passage found on another page is `comparison=mismatch`, reason
`wrong_page`. Where neither holds — the artifact is a text file, or the passage matched only
with spacing ignored — the passage is `verified`, the decision carries the warning
`page_unchecked`, and its detail says why the page was not checked.

A passage occurring more than once is `extraction=invalid`, reason `quotation_ambiguous`, for the
reason an ambiguous row selector is: no occurrence is taken as the one meant. The record says
which occurrence it quotes with a `prefix` or `suffix` naming the text on either side.

`prefix` and `suffix` are the W3C Web Annotation `TextQuoteSelector` neighbours: the text
immediately before and immediately after the passage, either or both, kept as written with
their surrounding whitespace and normalized as the passage is. They are consulted only where
the passage occurs more than once, and the assertion resolves where exactly one occurrence
carries them; where none or several do it stays `quotation_ambiguous`, and a passage that
occurs once is checked without them.

### 3.2 `metric`

```yaml
kind: metric
artifact: results
name: delta
reported: "3.20"                          # a string, always
pointer: /comparisons/primary/delta       # RFC 6901
mode: printed_precision                   # or absolute | relative
tolerance: "0"                            # a string; ignored for printed_precision
conversion: percent                       # optional; or fraction (§3.7)
places: 2                                 # optional; printed_precision only (§3.8)
```

Assertion: this artifact holds this value at this location.

**`reported` is a string** because YAML parses `3.20` to the float `3.2`, discarding the
precision the manuscript chose, and because binary floats do not represent decimal fractions
exactly. Parsed with `decimal.Decimal`.

**`pointer` is an RFC 6901 JSON Pointer** because a dotted path cannot distinguish a mapping
key containing a period from a nesting level, nor list index `0` from mapping key `"0"`.
Specifying an escape grammar for a new selector language is work already done.

| mode | agrees when |
|---|---|
| `printed_precision` | the stored value, rounded half-even to the precision `reported` prints, equals `reported`. A paper printing `3.2` is not contradicted by `3.20001`; one printing `3.20000` is. A stored value exactly halfway between two printed values agrees with either (§3.8). |
| `absolute` | \|stored − reported\| ≤ tolerance |
| `relative` | \|stored − reported\| ≤ tolerance × \|reported\| |

### 3.3 `table`

```yaml
kind: table
artifact: results-csv
name: c-index
reported: "0.648"
column: accuracy
where: {model: VAECox}      # or: row: 2
delimiter: ""               # inferred from suffix, then from the header
mode: printed_precision
tolerance: "0"
```

Assertion: this table holds this value in this cell.

Most published result artifacts are delimited tables rather than JSON, so this is the variant
a manuscript's own tables usually need.

A cell is named by its column and by exactly one of two row selectors. `where` selects the row
whose named columns hold the given values; `row` is a zero-based index among data rows.
**`where` is preferred**, because a row index silently addresses a different cell when a table
is reordered or a row inserted, and a reordered table is precisely the case a checker exists to
notice.

| situation | reported |
|---|---|
| `where` matches no rows | `extraction=absent`, reason `row_absent` |
| `where` matches more than one | `extraction=invalid`, reason `row_ambiguous` |
| the column is not in the header | `extraction=absent`, reason `column_absent`, listing the columns that are |
| both `row` and `where`, or neither | `extraction=invalid`, reason `row_selector_invalid` |
| the cell holds no number | `extraction=invalid`, reason `value_not_numeric` |

An ambiguous selector is reported rather than resolved to the first match, since resolving it
would make the answer depend on row order.

The delimiter comes from the file suffix where one is known, and from the header line
otherwise. Suffix first: a `.tsv` whose header contains commas is still tab separated, and
sniffing it would split every row in the wrong place.

### 3.4 `correspondence`

```yaml
kind: correspondence
name: fixture-count
sides:
  - name: stated
    artifact: spec
    locator: {kind: prose, before: "suite holds", after: "fixtures", form: cardinal_word}
  - name: measured
    artifact: probe
    locator: {kind: tree, pointer: /probes/fixtures/value}
mode: printed_precision     # or absolute
tolerance: "0"
```

Assertion: these two artifacts hold the same value.

A side may carry a `conversion` (§3.7), and is then compared as converted.

Every other kind compares an artifact against a literal written in the manifest. A claim a
document makes about the code beside it has an artifact on both sides: `docs/SPEC.md` states a
fixture count, and `ls -1 packages/claims/tests/conformance/cases` returns one. Expressing that
with a `metric` requires transcribing one of the two into `reported`, and no assertion reads
the transcription — rewriting every `reported` field to the value the command measured, leaving
the quoted sentences untouched, passes a manifest whose documents are still wrong.

Exactly two sides, each with a name, an artifact, and a locator. The two must not address the
same value, since an assertion comparing a value with itself holds whatever the file contains.
The names are the author's and the engine attaches no meaning to them.

**Neither side is the reference.** A disagreement reports both values and says which artifact
each came from; it does not say which is wrong, because nothing in a byte comparison establishes
whether a specification or a suite is in error. `relative` is rejected for the same reason: its
tolerance is a fraction of the reported value, and there is no reported value to take a fraction
of. `printed_precision` compares at the coarser of the two precisions, so a sentence printing
one decimal agrees with a file holding four, and the outcome does not depend on which side the
manifest wrote first. NaN and the infinities have no precision for either side to be coarser
than, so a non-finite value on either side is `value_not_numeric` before any comparison, as it
is for a one-sided assertion.

**What it cannot establish.** Three limits, in decreasing order of how often they bite.

A prose claim usually carries no number. *The scanner reads the directory flat*, *the field is
honored*, *the walk skips symlinks* are propositions about behavior, and expressing one means
inventing a count — of matched files, of call sites — so the assertion then checks the encoding
rather than the proposition. A correspondence reaches a documented claim only where the document
states a quantity.

The subject of such a claim is usually a repository, and a repository is not a file a manifest
can declare: `Digest.of_file` addresses one file, so the directory a count is taken over cannot
be pinned as an input. The measured side is therefore an artifact holding a command's output,
pinned like any other, while the input to that command is not pinned at all. §7.6 puts declared
inputs in an empty directory so that a command needing an undeclared file fails; a command whose
subject cannot be declared reads it by absolute path and the record reports `reproduced` on
grounds nothing checked. **A correspondence over a repository makes no reproducibility claim,
and a manifest should declare no regeneration for one rather than collect a guarantee it has not
earned.** Closing this needs an artifact identified by a digest over a directory, which this
revision does not define.

Both sides being read does not make either side right. Two artifacts agree or they do not, and a
document and a script can agree on a number that is wrong.

### 3.5 `aggregate`

```yaml
kind: aggregate
name: accuracy
reported: "0.914"
statistic: mean             # or median | min | max | sum | count
count: 3
members:
  - {artifact: seed-0, locator: {kind: tree, pointer: /accuracy}}
  - {artifact: seed-1, locator: {kind: tree, pointer: /accuracy}}
  - {artifact: seed-2, locator: {kind: tree, pointer: /accuracy}}
mode: printed_precision     # or absolute | relative
tolerance: "0"
conversion: percent         # optional (§3.7), applied to each member
places: 3                   # optional (§3.8)
```

Assertion: the printed value is this statistic of the values these members hold.

A sentence reporting a mean over ten seeds, bound with a `metric` to one run's file, rests on
that run. The manifest reads the same whether the run is the typical one or the best of the
ten, and the other nine files are read by nothing. An `aggregate` names every member, and the
assertion is checked only where every member holds a number.

A member is an artifact and a locator of §3.6, so a member resolves to exactly one scalar by
the rules every other value does. Members may name one artifact each or several addresses in
one: ten values in one JSON array are ten members, `/scores/0` to `/scores/9`. No locator
resolves to a list, and an aggregate does not add one, since a member that is a whole array
is a set whose length the manifest does not state.

**`count` is required and must equal the number of members.** The manuscript's "ten seeds" is
then a declared quantity, and a member deleted from the list leaves a manifest that states
ten and lists nine. That manifest does not load. Neither does one listing the same artifact and
locator twice, which would count one value two times.

| statistic | computed |
|---|---|
| `mean` | the sum of the values divided by `count` |
| `median` | the middle value in sorted order, or half the sum of the two middle values where `count` is even |
| `min`, `max` | the least and the greatest value |
| `sum` | the sum of the values |
| `count` | the number of members, each of which holds a number |

The set is closed. A standard deviation is not in it: it is a square root, which no exact
decimal or rational holds, and it names two quantities until `sample` or `population` is said.

**A conversion is applied to each member, and places and ties are as for one value.** A
declared `conversion` converts each member's value, exactly, before the statistic is taken, so
ten stored fractions printed as a mean percentage are bound with `conversion: percent`. It is
rejected with `count`, since how many members there are is in no unit. `places` is what §3.8
defines, checked after every member has resolved. A statistic exactly halfway between two
printed values agrees with either, decided by the function that decides it for a single value,
and the decision records the tie.

**The statistic is exact, and is rounded once.** Each stored value is parsed as a decimal and
held as a rational, and the statistic is computed over rationals: a mean of three values is
the exact quotient, with no binary float formed and no decimal division rounding it at a
context's precision. The comparison is the one §3.2 defines, on that exact value. Under
`printed_precision` the statistic is rounded half-even to the precision `reported` prints and
must equal `reported`; under `absolute` and `relative` the exact difference is compared with
the tolerance. Members holding `0.264` and `0.099` have a mean of exactly `0.1815`, which is
an exact tie at three places, so `0.181` and `0.182` both agree and the decision says so; the
same mean in binary floating point is a hair below the boundary, where it is no tie and only
`0.181` would agree.

| situation | reported |
|---|---|
| a member's artifact is not declared | `unchecked`, reason `artifact_undeclared` |
| a member's file is not on disk | `unchecked`, reason `artifact_missing`, naming the path |
| a member's file cannot be parsed | `unchecked`, reason `artifact_unreadable`, naming the member |
| a member's format has no adapter | `unchecked`, reason `format_unsupported` |
| a member's locator does not resolve | `extraction=absent` or `invalid`, with that member's reason |
| a member holds no finite number | `extraction=invalid`, reason `value_not_numeric` |
| `count` differs from the number of members, or a member is listed twice | the manifest does not load |

**A statistic over the members that did resolve is never taken.** Where any member fails, no
comparison is made, the decision carries the first failing member's reason, and its detail
names every member that failed by its position in the list and its artifact:
`member 4 of 10 (seed-3): /accuracy does not resolve in seed-3.json`. The assertion's validity
is the weakest of its members' artifacts.

A decision records one `DecisionMember` per member, in the order the manifest lists them, with
the artifact digest, the locator digest, the value extracted and its digest, and the value
converted where a conversion is declared. It records the
`statistic` and `computed`, the value compared: written exactly where it is a terminating
decimal, and otherwise rounded half-even to three places past the precision the manuscript
prints. The decision-level extraction digest covers every member's, in order.

**What it cannot establish.** That the members listed are all the runs there were. An author
who ran twelve seeds and lists the best ten states `count: 10` and passes. The assertion binds
the printed value to the declared set, and which runs belong in the set is the author's
declaration, as an address is.

### Kinds that are not here

`protocol` was specified as a third kind and is not one. Its integrity check is the artifact
pin, which every artifact already carries; its content check — that a registered document
states a given hypothesis — is a `quote` against the plan. What remains distinct about a
protocol is temporal: whether a confirmatory run postdates its registration. That is read from
a run record (§7) and is not an evidence kind.

## 3.6 Locators

A locator says where a value sits. JSON Pointer works because JSON has one tree data model and
a pointer resolves to at most one value; it says nothing about table keys, multidimensional
indices, or database rows. Rather than extend one syntax to cover every file, the contract is
a discriminated union whose variants address each format the way that format already addresses
itself.

| kind | addresses | identity |
|---|---|---|
| `tree` | JSON, and YAML restricted to a JSON-compatible tree | RFC 6901 pointer |
| `table` | CSV, TSV, PSV; Parquet, Feather, Arrow; Stata, SPSS; an R data frame (`.rds`) | column plus a predicate matching exactly one row |
| `table_position` | the same, by row index | column plus position, carrying a warning |
| `sheet` | an Excel workbook (`.xlsx`, `.xls`) | sheet, column, and a predicate matching one row |
| `sqlite` | a database file | table, column, and a predicate matching one row |
| `array` | `.npy`, `.npz`, HDF5, NetCDF | array name or dataset path plus a multidimensional index |
| `prose` | a document, as text | two literal anchors bracketing the value |

Every variant enforces one invariant: a locator resolves to **exactly one scalar**. Zero is
absent, two or more is ambiguous, a container is not a value, and no backend takes the first
match. A format with no adapter — MATLAB, RData, SAS — reports `format_unsupported` and stops,
as does a pickle, which no adapter opens because reading one runs code. No backend falls back to searching a file for the printed number, which would find
it wherever it appears and call that verification.

`prose` is the one variant addressing a format that has no addressing scheme of its own. A
sentence is not a tree, a table, or an indexed array, so the address is the text on either side
of the value: `before` is the literal that precedes it and `after` the literal that follows,
and the value is the run of non-whitespace characters between them.

```yaml
locator: {kind: prose, before: "suite holds", after: "fixtures", form: cardinal_word}
```

With no `after`, the value is the whole run up to the next whitespace. With one, it is the
whole run where `after` begins past it, and otherwise the run cut at the first place inside it
where `after` begins. A character printed against the value is therefore removed by naming it.
A cell of a printed table is glued to its divider, `| 7| 0.318| 0.107|`, and is addressed by
the row's leading cells and the divider; a number closing a sentence, `3.14.`, by the full
stop.

**An anchor never splits a number.** `after` may not begin, and `before` may not end, inside
a number: digits, with a decimal point, a grouping comma or underscore, or an exponent between
them. `after: "8"` over `0.318 rows` reads nothing where a cut would read `0.31`, the first
full stop of `3.14.` is passed over for the second, and `before: "0.3"` does not read `18`. An
occurrence refused this way yields no value, so where no other occurrence resolves the
assertion is `passage_absent` and its detail names the number the anchor would have split.
Digits attached to a preceding letter, as in `v0.5` or `H10`, are a name and not a number, so
`before: "v0."` reads `5`. A sign belongs to its number unless a digit or a letter precedes
it: `before: "x=-"` reads nothing from `x=-0.42`, and `before: "10-"` still reads `12` from
`10-12`.

```yaml
locator: {kind: prose, before: "| 7|", after: "|"}      # 0.318
```

With `after` omitted the same cell is the run `0.318|`, which is `value_not_numeric`. Nothing
is stripped that the locator did not name.

Two alternatives were available and are worse under this document's own rules. A capture-group
pattern is a string expression language, which §3.6 rejects for predicates: it needs a dialect,
an escaping grammar, and a backtracking bound. A braced template — `holds {n} fixtures` — needs
an escaping grammar for the brace, and LaTeX sources are full of braces. Two literal anchors
need neither, and they make the author state the address rather than describe a number to
search for.

Anchors are matched against the text a `quote` resolves against, under the same normalization,
so an anchor and a quotation over one document cannot disagree about what the document says.
Whitespace at an anchor boundary is ignored, on the grounds that normalization collapses it
everywhere else. An anchor pair selecting two occurrences of one value resolves to that value;
selecting two *different* values is `passage_ambiguous`. A repeated count is ordinary prose and
a document stating two counts is a defect, which is the distinction a `quote` cannot draw:
a quotation is satisfied by any occurrence, so editing one of two statements of a number leaves
the assertion satisfied by the other.

`form` says how the selected text is read as a number. Under `decimal`, the default, digits are
parsed and nothing is converted. Under `cardinal_word`, an English cardinal below one hundred
written as one word is read as that number: `eighteen` is 18. **The conversion is declared, not
inferred.** Under `decimal` a recognized cardinal is refused with `number_as_word` rather than
converted, because reading a word as a number is a semantic decision and the engine makes none
on its own. The bound is not arbitrary: the value is one run of non-whitespace characters, and
every cardinal above ninety-nine is several words, so `one hundred and forty-five` is not
addressable this way whatever the table holds. `form` is part of the canonical locator, so the
decision digest binds what the manifest authorized.

Predicates are typed key-value mappings, not a string expression language: a string predicate
needs a parser, coercion rules, and an escaping grammar, and every implementation would
disagree about the edges. In a delimited file, predicate values are compared as text and never
coerced, so `"001"` and `1` address different rows. YAML is read with duplicate mapping keys
rejected, since a file that resolves one way with nothing said about the other is not
addressable.

`value` is the evidence kind that carries a locator, and addresses every format in the table
above:

```yaml
kind: value
artifact: results-db
name: n
reported: "480"
locator: {kind: sqlite, table: runs, column: n, where: {split: test}}
mode: printed_precision
tolerance: "0"
```

`metric` and `table` evidence remain as shorthand for the two commonest locators and resolve
through the same adapters, so a manifest never chooses between a convenient spelling and a
supported one.

Locators are canonicalized — sorted keys, no whitespace, no coercion — and hashed. A decision
records that digest beside the artifact digest, so it binds how a value was addressed as well
as what was read: a selector edited after the fact changes the record even where the file does
not.

## 3.7 Conversions

A file stores 0.042 and the manuscript prints 4.2, as a percentage. Without a declared
conversion the two cannot be bound, and an author's alternatives are to transcribe 4.2 into a
second file or to leave the number unchecked.

```yaml
kind: metric
artifact: results
name: attrition
reported: "4.2"
pointer: /attrition
conversion: percent
```

`conversion` is an optional field of `metric`, `table`, `value` and `aggregate` (§3.5), and of
each side of a `correspondence`. It takes one of two names.

| conversion | the file stores | the manuscript prints | converted value |
|---|---|---|---|
| `percent` | a fraction, `0.042` | a percentage, `4.2` | stored × 100 |
| `fraction` | a percentage, `4.2` | a fraction, `0.042` | stored ÷ 100 |

**The set is closed.** There is no multiplier and no expression. An assertion that states its
own arithmetic can make any stored value agree with any printed one, and nothing checks the
arithmetic. A name outside the set is a manifest that does not load.

**The stored value is converted exactly, and then compared.** Both conversions move the
decimal point two places and change no digit, so the converted value is an exact decimal at
any number of digits: no binary float is formed and no rounding happens in the conversion.
The comparison of §3.2 then runs on the converted value. Under `printed_precision` the
converted value is rounded half-even to the precision `reported` prints, so a file holding
`0.0424` agrees with a manuscript printing `4.2` (4.24 rounds to 4.2) and a file holding
`0.0426` does not (4.26 rounds to 4.3). Rounding before converting would compare `0.0` with
`4.2` in both cases. Under `absolute` and `relative` the tolerance is in the unit the
manuscript prints: `tolerance: "0.1"` under `percent` is a tenth of a percentage point.

In a `correspondence` each side is converted under its own declaration, and the coarser of the
two precisions is found after converting. A stored `0.04` is 4 as a percentage, with no decimal
place, so a document printing `4.2` is rounded to it.

With no `conversion`, nothing is converted, and a manifest that declares none is serialized
without the field, so its digest is the one it had before the field existed. A stored value
that is not a finite number is `value_not_numeric` before any conversion.

A decision over one artifact records `extracted`, the value as stored; `conversion`, the name
declared; and `converted`, the value compared. A `DecisionSide` records the same three. The
conversion is not part of the locator, which says where a value sits and nothing about the
unit it is printed in, so the locator digest does not move when a conversion is declared.

## 3.8 Places and ties

**How a value is rounded.** Under `printed_precision` the compared value, which is the stored
value after any declared conversion, is rounded half to even to the precision of `reported`
and must then equal it. The precision is read off `reported` as written: `"3.20"` is two
decimal places and `"3.2"` is one.

**`places` declares that precision separately.**

```yaml
kind: metric
artifact: results
name: effect
reported: "4.2"
pointer: /effect
places: 1
```

`places` is an optional non-negative integer on `metric`, `table`, `value` and `aggregate`: the number of
decimal places the manuscript reports this value to, as the author states it. Where it is
declared, two things must hold.

1. `reported` is written to exactly that many decimal places. `"4.20"` under `places: 1` does
   not satisfy it, and neither does `"3.1"` under `places: 2`. Nothing is rounded to make it
   so: a rule that rounded to the declared places and left any further printed digit unread
   would pass a manuscript printing a digit nobody checked.
2. The compared value, rounded to that many places, equals `reported`. Given the first, this
   is the comparison §3.2 already makes.

A `reported` written to another number of places is `comparison=mismatch` with reason
`places_mismatch`, which flattens to `mismatch`. It is an outcome and not a manifest that
fails to load, for two reasons. The disagreement is between two statements about the
manuscript, a reporting convention and a printed cell, and a table declared to one place that
prints two is a finding about that table. And a manifest that does not load reports nothing,
so one such cell would hide every other assertion's result. The value is extracted first, so
an address that does not resolve, or a value that is no number, is reported as that.

`places` goes with `printed_precision` only. Under `absolute` and `relative` the comparison is
a difference against a tolerance and rounds nothing, so there are no places for it to be at,
and a manifest declaring `places` with either mode does not load. With a `conversion`, the
places are those of the converted value, which is the value printed. A `correspondence` takes
no `places`: neither side is the manuscript's printed value.

**An exact tie agrees with either neighbor.** A compared value exactly halfway between two
values at the printed precision, `4.25` at one place, has two correct roundings. Spreadsheets
and most hand calculation round half away from zero, to `4.3`; Python, R and IEEE 754 round half to
even, to `4.2`. A manuscript printing either has rounded its own number correctly, so both
verify, and a printed value that is neither neighbor is a `mismatch`.

A tie is decided on the digits and nothing else: the digits of the compared value past the
printed precision are a 5 followed only by zeros, or they are not. No float is formed and no
value is within a tolerance of a tie, so `4.2500001` is not one: it rounds to `4.3` under
either rule, and `4.2` is a mismatch. The conversion of §3.7 is applied first, so a stored
`0.0425` under `percent` is the tie `4.25`. Ties are met under `printed_precision` only, with
or without `places`, and by a `correspondence` at the coarser of its two precisions.

Away from a tie the two rules give the same answer, so nothing else about the comparison
changes. There is no option naming a rounding rule: a manifest could then only be right about
which software produced each number, and the manuscript does not say.

A decision at a tie records it as `tie`, with `lower` and `upper`, the two neighbors, and
`printed`, the value the manuscript prints, so that an agreement reached by accepting both is
told from an ordinary one. `repro verify` prints `[exact tie: 4.2 or 4.3]` beside the
assertion, and `repro why` prints the tie above the printed value.

## 3.9 The value as stored

An adapter returns the stored value as text, and the comparison reads that text as an exact
decimal. What the text is depends on what the format holds.

| format | the value as stored |
|---|---|
| JSON, YAML | a number with a fraction or an exponent is the characters the file wrote for it, so `0.910` is `0.910`, `1e-7` is `1e-7`, and a value of twenty digits keeps all twenty; an integer is exact at any length; a quoted number is its text |
| delimited text | the characters of the cell |
| prose | the run of characters the anchors select in the extracted text |
| a format that stores numbers in binary: Parquet, Feather, Arrow, Stata, SPSS, `.rds`, a workbook, SQLite, `.npy`, `.npz`, HDF5, NetCDF | the shortest decimal that reads back as the stored number at the width it is stored in |

A tree file's number is never passed through a binary float. Read as one and printed back,
`0.910` became `0.91`, `9007199254740993.0` became `9007199254740992.0`, a value of twenty
significant digits became its nearest seventeen, and `1e400` became infinity. Three YAML forms
have no decimal spelling and are read as the number they denote: `.inf` and `.nan`, which are
`value_not_numeric`, and base-sixty `1:30.5`.

A binary format holds no trailing zeros to preserve, so none are recovered from one: a
double written from `0.910` is the double `0.91`.

Trailing zeros in a file are kept and shown. Whether they count as precision follows from the
comparison and not from the file. Against a literal, the precision is the manuscript's (§3.2):
a file holding `0.910` verifies a manuscript printing `0.91`, since `0.910` rounded to two
places is `0.91`, and a file holding `0.91` verifies one printing `0.910`, since the value it
holds is that one. In a `correspondence` neither side is the manuscript and the comparison is at
the coarser of the two precisions as written (§3.4), so there a file's trailing zeros are
precision: `0.910` against `0.914` disagree at three places, and `0.91` against `0.914` agree
at two.

## 4. Outcomes

A check must execute, extract, and compare. Each stage fails differently, and the report
records all three.

| stage | values |
|---|---|
| `execution` | `completed` · `unavailable` · `failed` |
| `extraction` | `extracted` · `absent` · `invalid` · `not_attempted` |
| `comparison` | `match` · `mismatch` · `not_applicable` |

Collapsing these is how a missing extractor becomes a quotation that failed to check out, and
how a file silent on a value becomes one that contradicts it.

| situation | execution | extraction | comparison | flattens to |
|---|---|---|---|---|
| passage present | completed | extracted | match | `verified` |
| two sides agree | completed | extracted | match | `verified` |
| two sides disagree | completed | extracted | mismatch | `mismatch` |
| one side does not extract | completed | absent or invalid | n/a | `not_found` |
| a statistic of the members agrees | completed | extracted | match | `verified` |
| a member does not extract | completed | absent or invalid | n/a | `not_found` |
| passage absent from a readable source | completed | extracted | mismatch | `mismatch` |
| passage present, on another page than the one declared | completed | extracted | mismatch | `mismatch` |
| passage occurs more than once | completed | invalid | n/a | `not_found` |
| pointer does not resolve | completed | absent | n/a | `not_found` |
| value is not a number | completed | invalid | n/a | `not_found` |
| value printed to other than its declared places | completed | extracted | mismatch | `mismatch` |
| independent readers disagree | completed | invalid | n/a | `not_found` |
| extractor not installed | unavailable | not_attempted | n/a | `unchecked` |
| artifact missing or unparseable | unavailable | not_attempted | n/a | `unchecked` |
| format no adapter reads | unavailable | not_attempted | n/a | `unchecked` |
| backend defect | failed | not_attempted | n/a | `error` |

`Outcome` is derived from the three stages and never assigned, so the flattening cannot drift
from what the stages say.

**Silence is not contradiction.** A results file with no `bootstrap_n` key does not assert
that the value differs from what the manuscript reports; it asserts nothing. That is
`extraction=absent`, flattening to `not_found`, distinct from both a value that disagrees and
a check that could not run.

**Two extractions still make one comparison.** A `correspondence` reads a value from each
of two artifacts before comparing them, and the stages report that as they report everything
else. Where one side extracts and the other does not, the comparison did not happen: that is
`extraction=absent` or `extraction=invalid` with `comparison=not_applicable`, flattening to
`not_found`, and never `mismatch`. A results file silent on a value does not contradict a
document stating it, and a document that never states the number does not contradict the file.
The decision carries the failing side's own reason — `pointer_absent`, `number_as_word` — and
names which side failed, so a gap on one side is not reported as a disagreement between two.
The extraction stage of a two-sided assertion is the weaker of its two sides, and its validity
is the weaker of its two artifacts.

**A reader is not the document.** A pin establishes that a file's bytes have not changed. It
establishes nothing about whether the program that read them produced the right text, and a
mangled extraction reads exactly like a passage that was never written: a two-column layout
flattened in the wrong order yields a confident `not found` against a manuscript that quotes
its source correctly. Where two independent extractors disagree about whether a passage is
present, the document is not determinate under the readers available, which is
`extraction=invalid` — the same stage as a cell holding no number, and for the same reason.
There was nothing well formed to compare. It is emphatically not `comparison=mismatch`, which
asserts that the source contradicts the manuscript.

Disagreement is therefore a property of the reading, not a milder verdict about the passage,
and every decision names the reader and version that produced the text it was checked against.
A backend that substitutes one extractor for another records the substitution: two decisions
that disagree because they were taken with different readers are otherwise indistinguishable
from two decisions that disagree about the document.

**Availability is a claim-level fact, not an outcome.** Whether a claim offers evidence cannot
be the result of checking evidence, because there is none to pass to a backend. `Claim`
carries `availability: offered | not_offered`; `not_offered` appears in the flattened view for
display and is never a `Decision`.

### 4.1 Reasons and warnings

`Reason` is a typed field carrying why an outcome obtained. Every value, with the outcome
it flattens to:

| reason | outcome | obtained when |
|---|---|---|
| `passage_present` | `verified` | the quoted passage occurs in the artifact |
| `value_match` | `verified` | the stored value agrees with the reported one, or two sides agree |
| `value_mismatch` | `mismatch` | the stored value disagrees with the reported one, or two sides disagree |
| `places_mismatch` | `mismatch` | `places` is declared and the reported value is written to another number of decimal places (§3.8) |
| `passage_absent` | `mismatch`, `not_found` | a quoted passage is not in an artifact that was read, which is `mismatch`; or a prose locator's anchors select nothing, which is `not_found` |
| `wrong_page` | `mismatch` | the quoted passage occurs, on another page than the one declared |
| `pointer_absent` | `not_found` | a JSON Pointer or an array index does not resolve |
| `row_absent` | `not_found` | a row predicate matches no row, or a row index is past the end |
| `column_absent` | `not_found` | the column is not in the table |
| `row_ambiguous` | `not_found` | a locator matches more than one value; no first match is taken |
| `row_selector_invalid` | `not_found` | a `table` assertion gives both `row` and `where`, or neither; or a locator leaves out or adds what the artifact's format needs, such as an `.npz` with no array named |
| `selector_not_scalar` | `not_found` | the locator resolves to a list or a mapping |
| `value_not_numeric` | `not_found` | the value addressed is not a finite number |
| `number_as_word` | `not_found` | the value is an English cardinal written out, under a locator that did not ask for one |
| `passage_ambiguous` | `not_found` | one pair of prose anchors selects two different values |
| `quotation_ambiguous` | `not_found` | the quoted passage occurs more than once and no `prefix` or `suffix` singles one occurrence out |
| `extractors_disagree` | `not_found` | two extractors that both read the artifact disagree about whether the passage is in it |
| `format_unsupported` | `unchecked` | no adapter reads the artifact's format |
| `extractor_missing` | `unchecked` | the program or package that reads the artifact is not installed, or produced no text |
| `artifact_missing` | `unchecked` | nothing is at the declared path |
| `artifact_unreadable` | `unchecked` | the file is there and could not be parsed |
| `artifact_undeclared` | `unchecked` | the assertion names an artifact id the manifest does not declare |
| `backend_defect` | `error` | the backend raised something unexpected |
| `not_offered` | `not_offered` | reserved for a claim offering no evidence; no decision carries it, since availability is a claim-level fact |

Four of these exist to keep apart cases that share an outcome and need different fixes.
`extractors_disagree` asks for a better reader rather than accusing the manuscript as
`passage_absent` does. `quotation_ambiguous` accuses nothing and asks for a `prefix` or
`suffix` on the quote assertion (§3.1), as it does where the two are given and single out no
occurrence. `passage_ambiguous` says the document states two numbers where the assertion
addresses one. `number_as_word` is distinct from `value_not_numeric` because the value is
there and a reader would call it a number, so an author told only that no number was found
goes looking for a broken anchor.

`Warning` is orthogonal to the outcome, and a decision may be `verified` and carry one:

| warning | on | says |
|---|---|---|
| `short` | `quote` | the passage is under 40 characters or ends on a comma or a connecting word, so the source may qualify it in the next clause |
| `truncated` | `quote` | every occurrence of the passage stops in the middle of a word or a number |
| `normalized` | `quote` | the passage matched only with spacing ignored (§3.1) |
| `wrong_page` | `quote` | the passage is on another page than the one declared; the decision is a `mismatch` with reason `wrong_page` |
| `page_unchecked` | `quote` | a `page` is declared and was not checked (§3.1) |
| `positional_address` | `table`, `value` | the cell is addressed by row index, which names another cell once the table is reordered |

`truncated` exists because *"an accuracy of 0.9"* genuinely occurs in a source reporting
**0.95**, so the passage is present and the reader is told a true thing that misstates the
result. `page_unchecked` is the one warning a policy reads (§6): the others qualify a check
that ran, and it says a declared check did not.

## 5. Backends

```python
class Backend(Protocol):
    kind: str
    version: str

    tool: str

    @property
    def tool_version(self) -> str: ...

    def check(
        self, claim: Claim, evidence: Evidence, paths: Mapping[str, pathlib.Path]
    ) -> Decision: ...
```

`paths` holds one entry per artifact the assertion names, keyed by id. Every kind but
`correspondence` and `aggregate` names one and takes it with `paths[evidence.artifact]`. It is a mapping rather
than a path because an assertion whose two sides are both artifacts has no single file to be
handed, and handing it one would make the engine choose a side before the backend has read
either. Widening this was not additive: a backend written against the earlier signature does
not satisfy the protocol.

Every decision names the backend and its version, because the same inputs can receive
different decisions after a backend upgrade and a stored decision that does not say which
backend produced it cannot be compared with a later one.

### 5.1 The extraction toolchain

`version` is the protocol version of the interface, written by hand. The program that turns
bytes into text or values is named separately, in `tool` and `tool_version`: the `pdftotext`
binary for a quotation, the installed distribution supplying the format adapters for a value.
Content addressing establishes that the bytes did not change and establishes nothing about how
they were read, so a `pdftotext` upgrade that resolves a ligature differently changes an
extracted passage with every digest in the manifest intact. A binary reports its version as it
prints it; a distribution reports `importlib.metadata`. A tool that cannot be interrogated is
recorded as `unknown`, never omitted: a field that disappears makes an uninterrogated
toolchain indistinguishable from an absent one.

`extraction_digest` records the sha256 of what the extractor produced — the whole extracted
text for a quotation, the extracted value for a number. The version string catches drift that
announces itself; the digest catches drift from any cause, including a rebuilt binary
reporting the same version and an environment that changes an encoding path. `unknown` where
the extraction produced nothing to hash. It establishes stability and not correctness: a first
extraction that reads a column wrong hashes perfectly and stays wrong.

A `correspondence` extracts twice, so it records a digest per side and one over both, in the
order the manifest declares the sides. The decision-level digest moves whenever either side's
extraction moves; which of the two moved is on the side. Leaving it `unknown` would say the
extraction was sought and not obtained, and it was sought twice. `tool` stays one field, which
is an approximation where the two sides are read by different programs: a `prose` side over a
paginated source reaches the same `pdftotext` a quotation does. The per-side extraction digest
is what catches a change in either program, since it moves whenever what a side read moves,
whatever did the reading. Naming a tool per side needs the adapters to report which one they
used, and this revision does not define that.

Both are provenance. Whether a changed tool version or a changed extraction invalidates a
stored decision the way a changed artifact does is a policy question, and §6 decides policy.

Exceptions are not interchangeable:

| raised | becomes | rationale |
|---|---|---|
| `BackendUnavailableError` | `execution=unavailable` | the toolchain is absent; the claim was not evaluated |
| `ArtifactUnreadableError` | `execution=unavailable` | the file exists and could not be parsed |
| anything else | `execution=failed` → `error` | a defect is a defect |

A `TypeError` must not become an abstention. Letting a programming error read as a benign
scientific outcome is the failure this document exists to prevent, one level up.

Backends do not print, and do not consult the network during verification.

## 6. Facts and policy

`verify()` returns facts and no verdict. Whether a project passes depends on what it is for:
an unchecked citation in a working draft is unremarkable, an unchecked confirmatory result in
a submission is not. Folding that judgment into the engine makes one project's standard
everyone's.

```python
report = verify(manifest)  # facts
verdict = PUBLICATION.assess(report)  # judgment
```

A `Policy` maps each outcome to `error`, `warning`, or `ignore`, with a separate map applied
to claims marked confirmatory. Three profiles ship:

| profile | mismatch | not_found | unchecked | not_offered | unpinned |
|---|---|---|---|---|---|
| `exploratory` | error | warning | warning | ignore | ignore |
| `publication` | error | error | warning | warning | warning |
| `publication`, confirmatory claims | error | error | **error** | **error** | — |
| `strict` | error | error | error | error | error |

The `error` outcome is an error under every profile, as is a broken pin. An artifact absent
from its declared path is a warning under `exploratory` and an error under the other two. A
`verified` quotation whose declared page was not checked (`page_unchecked`, §4.1) is graded as
the profile grades `unchecked` for that claim, under the rule `evidence.page_unchecked`.

Every policy requires at least one assertion to have been evaluated. A run that checked
nothing is not a pass, and without that condition a project with no evidence anywhere
satisfies every other condition trivially.

## 7. Ordering

A confirmatory claim asserts a preregistered outcome. Whether the run producing its evidence
postdates the registration is checked against a run record:

```yaml
runs:
  - id: confirmatory-run
    registered_plan: plan
    registered_at: 2026-08-01T14:00:00Z
    started_at: 2026-08-03T09:12:00Z
    outputs: [results]
```

Both timestamps must carry an offset. A naive timestamp compared against an aware one is
either a crash or a silently wrong ordering, so a manifest cannot express one.

A claim declares one of three registration states. `confirmatory`: it reports a preregistered
outcome, and the ordering check applies. `exploratory`: a plan could have fixed the outcome and
did not — the default, since a claim that says nothing about registration is exploratory rather
than exempt. `not_applicable`: no outcome was selected from alternatives, so registration has
nothing to bind, which is the case for an exhaustive deterministic measurement that reports
every result it produced. `not_applicable` requires a reason, on the same convention a
preregistration uses for an inapplicable heading, because a state that can be entered silently
is a way for any claim to opt out of being graded. A manifest written with `confirmatory: true`
or `false` still parses; `false` becomes `exploratory`, never `not_applicable`, since the
boolean never carried that distinction.

Each confirmatory claim reports one of four ordering states. `ordered`: every run producing
its evidence started after registration. `violated`: a run started first. `unchecked`: the
record does not settle it. `not_applicable`: the claim is not confirmatory.

An `unchecked` ordering carries a reason, because collapsing distinct conditions into one word
loses the only information that says what to fix: `no_run_record`, `no_evidence_offered`,
`no_registered_plan`, `registered_plan_unpinned`, `registered_plan_changed`,
`run_output_unlinked`, `run_output_changed`, `timestamp_missing`, `ambiguous_producing_run`. A
claim with no run record is `unchecked` and never `violated` — an absent record is not evidence
that a result predates its plan. `no_evidence_offered` is separate from `no_run_record`: a claim
that declares no evidence names no artifact, so no run could produce one, and a reader told the
run record is missing goes looking for a run that was never owed.

Every artifact a claim's evidence names must have a covering run. Taking the runs that produce
any one of them would let a run record for an incidental artifact order a claim whose number
came from an artifact with no run at all.

Where `registered_plan` names a declared artifact, that document is pinned, so a plan edited
after the fact to match results breaks its pin and the ordering reverts to `unchecked`. A plan
frozen by `prereg freeze` is never written to again: the freeze record, the log and each
amendment are separate files, so logging a deviation or amending the plan leaves the pin intact.

Two limits are structural. The registration timestamp is self-recorded, so the check
establishes internal consistency and not that a registration is contemporaneous with what it
claims. An outside timestamp closes that: `prereg timestamp` and `results timestamp` commit the
digest of the plan, the digest of each amendment and the ledger's head into a Bitcoin block
through OpenTimestamps, and the block's date bounds when each existed. `prereg freeze` always
attempts the timestamp, and one it could not make is reported by `prereg check` as owed until
`prereg timestamp` makes it. This check does not read those proofs; `prereg check` and
`results verify` do. And the check reads a declared run record rather than observing execution.

A run record says who attests to its `registered_at` in `registration_authority`, and a claim
takes the weakest authority among the runs that produced its evidence. The default is the
weakest, which is what an unqualified timestamp in a file is.

| authority | rank |
|---|---|
| `self_recorded` | 0 |
| `git_remote` | 1 |
| `osf` | 2 |
| `zenodo` | 2 |
| `trusted_timestamp` | 3 |

The authority is declared and nothing verifies it: the engine attaches a rank to each name
and no other meaning. No shipped profile requires one. A `Policy` with `minimum_registration_authority` set grades
an `ordered` confirmatory claim resting on a lower rank under the rule
`claim.registration_authority`, a warning unless the policy says otherwise.

OpenTimestamps is used because it needs no account and trusts no party beyond Bitcoin, and
because a proof names no one, so a stamp made during double-blind review identifies nobody. An
RFC 3161 timestamp authority or Sigstore's Rekor log would date a digest at once, where a Bitcoin
confirmation takes hours; the first trusts the authority's signing key, and the second ties each
entry to the signer's key.

## 7.5 Output formats

A renderer reads a report and an assessment and produces bytes. None computes anything, so two
renderers over one report always say the same thing.

`sarif` emits SARIF 2.1.0, which GitHub renders inline on a pull request. Two parts of that
format fit: `artifacts[].hashes` carries a sha-256 per file, so the digests a report was
computed against travel with it; and `result.kind` is separate from `result.level`, so a check
that could not run is `notApplicable` rather than a low-severity failure. Most report formats
cannot express that difference, and it is the one this document exists to preserve.

A policy raises a decision's `level` and never changes its `kind`: what happened does not depend
on what a project considers acceptable. A claim offering no evidence has no decision, and its
result is `informational` at the level `note` and `fail` where a policy grades it a warning or
an error.

`repro export sarif` writes a second log, from the check records of §7.10 and from nothing else,
for GitHub code scanning. It is a projection for display and loses what SARIF has no property
for; the whole record travels in each result's property bag under `repro/checkRecord`.

| `outcome` | in the log | by |
|---|---|---|
| `mismatch` | result, `kind: fail`, `level: error` | 3.27.9: `fail` is "a problem whose severity is specified by the level property" |
| `not-found` | result, `kind: fail`, `level: warning` | 3.27.10: `warning` is "a problem was found", `error` "a serious problem" |
| `error` | result, `kind: fail`, `level: error`, and a notification at `level: error` | 3.20.21: a notification at `error` "SHALL mean that the run failed" |
| `not-checked` | no result; a notification at `level: warning` | 3.58.6: "the analysis might be incomplete but the results that were generated are probably valid" |
| `match` | no result; with `--include-matches`, `kind: pass`, `level: none` | 3.27.9: "evaluated, and no problem was found". GitHub does not read `kind` and opens a `warning` alert for one, which is why it is not the default |

A `not-checked` assertion is not a result of any kind. `notApplicable` says the rule "does not
apply to the analysis target", which is false of a check that applies and did not run, and
`open` says the rule "was evaluated", which it was not. A notification is what the format has
for a condition of the run and not of the file. The outcome is read through `read_outcome`, so
a word the exporter does not know is `not-checked` and never a `pass`.

A result has one location: the line of the sentence, where the claim quotes one from a text
file that holds the passage exactly once, and otherwise the assertion's line in the manifest.
`partialFingerprints` carries a digest over the assertion's identity and what it declares, as
`reproAssertion/v1` and as `primaryLocationLineHash`, the one GitHub reads.

## 7.6 Regeneration

Ordering asks whether a confirmatory run followed its plan. That question has no meaning for a
measurement no plan could have registered: an exhaustive count over a declared corpus selects
no outcome, so nothing was there for a registration to fix. What can be asked of such a number
is whether it is still the output of the code that claims to produce it.

```yaml
regenerations:
  - id: figures
    command: [python, scripts/build_figures.py]
    inputs:
      - {artifact: corpus, digest: {algorithm: sha256, value: ...}}
      - {artifact: script, digest: {algorithm: sha256, value: ...}}
    output: {artifact: figures, digest: {algorithm: sha256, value: ...}}
    volatile: ["/generated_at"]
```

The declared inputs are copied into an empty directory and the command runs there, so a
command needing a file the manifest never declared fails, and a command that writes where it
was told to writes inside that directory. Every declared path is resolved and checked for
containment before it is used, since a path holding `..` otherwise lands outside.

This is a working directory, not a sandbox in the security sense: nothing stops a command
writing to an absolute path elsewhere. Running `repro reproduce` on a manifest you have not
read is running a program you have not read. That makes the record a claim about sufficiency and not only about provenance.

The verdict is about the numbers the manuscript prints, not the output's bytes. Where the
command writes the pinned bytes, the record reproduced. Where it writes other bytes, every
assertion that reads the output is put to the new file, by the comparison §5 defines and at the
precision the manuscript prints, and the record reproduced if each still holds. A re-run that
lists a directory in another order writes a different file holding the same values; calling
that a divergence reports a difference no reader can find in the paper. Whether the bytes
matched is recorded beside the verdict.

Five states.

| state | what happened |
|---|---|
| `reproduced` | re-ran, and every number the manuscript prints from the output still holds |
| `changed` | re-ran, and at least one number the manuscript prints from it is now different |
| `unchecked` | re-ran and wrote the output, but a number could not be read from it |
| `failed` | the command did not finish, or finished and wrote nothing |
| `not_rerun` | never executed: skipped, or an input is not the one the record names |

Each carries a reason. An input that changed yields `not_rerun` rather than `changed`, because
different inputs producing a different output is not a failure to reproduce, and the command
is not started. A command that exits 0 and writes nothing is `failed`: a clean exit is not
evidence that the work was done. An output with different bytes that no assertion reads is
`changed`, since its bytes are then all there is to compare. A number the manuscript already
printed differently from the pinned file, and which the re-run writes unchanged, is not
counted against the re-run; `repro verify` reports it.

The byte comparison is exact but canonical. An output carrying a timestamp or an absolute path
never reproduces byte for byte, so a record names those fields as `volatile` JSON Pointers and
they are removed before hashing; where a record names them, the digest it pins is the canonical
one. Naming the fields keeps the comparison exact everywhere else, which loosening the whole
comparison would not.

A record whose input is another record's output runs over the pinned copy of that output,
whatever happened to the record producing it. Where that record did not reproduce, at any
distance upstream, the dependent record names it in `rests_on`. An evaluation re-run over a
long training run's recorded checkpoint is worth having, and is not the same result as
re-running both.

Each invocation appends one object to `.repro/reproductions.jsonl` beside the manifest: when it
ran, the tool's version, the manifest's digest, the operating system, architecture and Python
version, the name and digest of a lockfile at the top of the project, GPU models and drivers
where there are any, the environment variables that bear on determinism, and per record the
command, its exit code and duration, the digest each input was pinned at and found at, the
digest the output was pinned at and produced at, the files the command wrote and did not
declare, and for each assertion the value in the pinned file, the value in the new file and the
value the manuscript prints, with the conversion the assertion declares (§3.7) and both stored
values under it. No field names a host, a user or an absolute path, and none
records who ran it, which the tool cannot observe.

Commands run only under `repro reproduce`. `repro verify` executes nothing: verifying a
manifest should never run what the manifest names. Commands are argv, never shell strings: a
shell string needs quoting rules, brings a shell's expansion with it, and turns a manifest into
something that can run anything. `--only` and `--skip` choose records by id, and a record left
out is reported `not_rerun`, never omitted.

Regeneration is orthogonal to registration. A `not_applicable` claim need not declare one —
methods statements and externally sourced facts are inapplicable without being script-generated
— and a confirmatory claim may declare both.

## 7.7 Staleness

`repro verify` passes a number that sits unchanged in its file after the data or the script
the file was computed from has been edited: the output is still the pinned one, and a pin says
nothing of what a file was made from. `repro stale` asks whether each file is still what a
recorded re-run produced. It executes nothing and writes nothing.

**The reference is the record of re-runs, not the manifest.** A regeneration record carries a
digest for each input and for its output, and a manifest rebuilt from the files on disk
rewrites them all, so they agree after a rebuild whether or not any command ran. What a rebuild
cannot write is `.repro/reproductions.jsonl` (§7.6). From it, only an entry whose command was
started is read, and only one whose state is `reproduced` is a re-run a file can be compared
with.

An entry says where its re-run happened where the environment said. Under GitHub Actions,
where `GITHUB_ACTIONS` is the string `true`, it carries a `witness` beside `environment`:
`kind` (`github_actions`), `repository`, `workflow`, `run_id`, `run_attempt`, `sha`, `ref` and
`runner_os`, each the runner's variable as the process was given it, and one that was not
given is left out. Any other run has no `witness` at all. The variables are copied and
nothing is checked against the service, so the entry states what the environment said, and
the run's page and log are what a reader checks it against. A regeneration and a finding each
carry the `witness` of the re-run they name, or null.

A regeneration is compared with its own re-runs first.

| state | of a regeneration, holds when |
|---|---|
| `current` | a re-run that reproduced ran the command the manifest declares now, read each declared input at the digest now on disk, and the output now on disk has the digest that re-run was compared against or the digest it wrote |
| `stale` | re-runs that reproduced are recorded and none of them satisfies that |
| `never_rerun` | the record holds no re-run of it that reproduced |
| `undetermined` | a declared input or the output is not on disk, the regeneration is upstream of itself, or a later re-run of the same command over the same inputs did not reproduce |
| `no_producer` | of a file only: no declared command writes it |
| `partly_outside_the_record` | of an assertion or a claim only: some of what it reads is `current` and the rest has no producer |

The output's digest is the one `repro reproduce` compares: the file's own, or the canonical
one where the record names `volatile` fields. `current` is a statement about the record. It
says the files are those a re-run that reproduced was made over, and not that the command
would reproduce now; an input the manifest does not declare is not compared.

A regeneration then takes the gravest state among its own and those of every regeneration
upstream of it, in the order `stale`, `undetermined`, `never_rerun`. A file takes the state of
the regeneration that writes it. An assertion takes the gravest state among the files it
reads, and a claim among its assertions; a file with no producer never outranks a finding.

Each difference is a finding with a cause, stated once at the regeneration where it is,
however many records and claims lie downstream.

| cause | state | the difference |
|---|---|---|
| `input_changed` | `stale` | an input's digest on disk is not the one the latest re-run that reproduced read |
| `command_changed` | `stale` | the declared command is not the one that re-run started |
| `output_changed` | `stale` | the output's digest on disk is neither the one that re-run was compared against nor the one it wrote |
| `upstream_stale` | `stale` | the regeneration matches its own re-run and one upstream of it is stale; the nearest is named with its distance |
| `input_missing` | `undetermined` | a declared input is not on disk |
| `output_missing` | `undetermined` | the output is not on disk |
| `cycle` | `undetermined` | the regeneration is upstream of itself, so it is compared with no re-run |
| `later_rerun_did_not_reproduce` | `undetermined` | a re-run matches, and a later one of the same command over the same inputs did not reproduce, so two witnessed runs disagree |

A regeneration whose declared digest for an input differs from that artifact's pin is listed as
`record_disagrees_with_pin`. It is noted and not graded.

A policy grades one violation for each regeneration that is `stale`, `never_rerun` or
`undetermined`, under the rule `staleness.` and the state. `stale` is a warning under
`exploratory` and `publication` and an error under `strict`; `never_rerun` and `undetermined`
are ignored, a warning, and an error. A file with no producer is counted and never graded.

## 7.8 One claim's account

`repro why <claim-id>` puts what `repro verify` and `repro stale` find for one claim side by
side. It evaluates nothing those two do not, executes nothing and writes nothing, and it
carries no verdict.

For each assertion the account holds the outcome and reason `repro verify` gives, and for
each file the assertion reads: whether the file matches its pin, the address the assertion
looks at, and the value stored there. For each file the claim rests on, the files it reads
and every file upstream of one, it holds the command that writes the file, the files that
command reads, the re-run the file was compared with, its state as §7.7 defines it, and each
finding. A `mismatch` is listed with what is established: the value at the address was read
and is not the printed one.

Then it lists what the record does not cover, each line with a kind.

| kind | the line says |
|---|---|
| `no_producer` | no command is recorded for a file, so its bytes are taken as given, pinned or not |
| `absent` | nothing is at a file's declared path |
| `broken_pin` | a file a command writes does not have the pinned bytes |
| `cycle` | a command is on a cycle of commands, so it is compared with no re-run |
| `never_rerun` | no re-run of a command that reproduced is recorded |
| `no_evidence` | the claim offers no evidence, so nothing was checked |
| `unchecked` | an assertion's outcome is `unchecked`, with its reason |
| `not_found` | an assertion's outcome is `not_found`, with its reason |
| `error` | an assertion's outcome is `error`, with its reason |
| `undeclared_inputs` | where a command is recorded: the inputs it declares are the author's list, and a file it reads and does not declare is invisible |
| `address` | where an assertion has an address: the address is the author's choice, and nothing checks that it holds the quantity the sentence means |
| `comparison` | where there is an assertion: a verified one says the declared value or passage is in the file, not that the analysis is right |

The last three hold of the design and not of the record, and an account closes on each that
applies. A claim id the manifest does not declare is an error naming the nearest ids.

## 7.9 The numbers a manuscript prints

`repro verify` reports on the claims a manifest declares, and the author chose which to
declare. `repro numbers` counts every number the manuscript's text prints, so the denominator
is the text's. It executes nothing, writes nothing and carries no verdict.

**Which text.** An artifact a claim reads its own sentence from: one a `quote` reads in a
claim that also offers an assertion of another kind, or one a `prose` locator reads. A `quote`
standing alone in its claim is a quotation from a source, and that source is not inventoried.

**What a number is.** The text is the one a quotation resolves against (§3.1). A number is
digits with an optional sign, grouping commas, a decimal point and an exponent: `2,364` is one
number, `12,13` is two, and `10-12` is two. A percent sign is kept with its number and is not
part of its value. A cardinal written as one word is a number with the value a `prose` locator
reads from it under `cardinal_word`.

Every number has exactly one standing, and none is dropped.

| standing | holds when |
|---|---|
| `bound` | a declared assertion accounts for this occurrence |
| `set_aside_with_a_reason` | it lies in a passage the manifest lists under `set_aside`, with the reason given there |
| `set_aside_by_rule` | a named rule below reads it as something other than a quantity |
| `unbound` | it is printed, and nothing in the manifest accounts for it |

**Bound.** An occurrence is bound where it lies inside a place the passage of a `quote`
occurs and an assertion of the same claim carries a `reported` value that is this number,
digit for digit, so `0.5` does not bind `0.50`; or where it lies in the value a `prose` locator
selects. The same digits reported by another claim bind nothing. An unbound number whose value
some assertion reports is marked `reported_elsewhere` where the value has two digits or a
decimal point, and counted apart where it is a single digit.

```yaml
set_aside:
  - artifact: manuscript
    text: "between 2019 and 2023"
    reason: the study period, a fact about the design and not a result
```

A `set_aside` entry names a passage, matched as a quotation is, and a reason, which is
required. Every number in each place the passage occurs is set aside unless an assertion binds
it, and each entry is listed with how many numbers it accounts for.

The rules are applied in this order, and the first that holds is the one named.

| rule | sets aside |
|---|---|
| `link` | digits inside a URL |
| `date` | each part of a date written `2026-10-13` |
| `document_identifier` | the number a document is known by, as in `rfc 6901` and `arxiv 2609.22111`, and the digits of a DOI |
| `name` | digits that are part of a name: a letter stands immediately before them, a hyphen or underscore joins them to a part holding a letter (`gpt-4`), or they open a run of letters and digits that holds more digits |
| `version_or_section` | digits joined by two or more full stops, `0.5.5` |
| `citation` | whole numbers from 1 up alone in square brackets, `[12]` and `[3, 7]` |
| `label` | the number of a section, figure, table, equation, appendix, chapter, page, algorithm, listing, theorem, lemma, proposition, corollary, definition, footnote, step or line, following that word |
| `list_marker` | a whole number of one or two digits alone in parentheses, `(1)` |
| `ordinal` | digits with `st`, `nd`, `rd` or `th` attached, `95th` |
| `year` | four digits from 1800 to 2099 with no sign, separator, decimal point or percent sign |
| `the_word_one` | the word `one`, a pronoun more often than a count; every other cardinal written as one word is counted |

## 7.10 The check record

Experimental, and this tool's own export format: `repro.check/0.1-experimental`. A field may
change before `1.0`, and every record names the version it was written under.

`repro export record` writes one JSON object per line, one per assertion, in the order the
manifest declares them. A record states an observation and no verdict: this checker, at this
version, read this file, with this digest, at this address, obtained this value, compared it
with the value the manuscript reports under this rule, and returned this outcome. It is
evaluated by the functions `repro verify` uses and by no others.

| field | holds |
|---|---|
| `record`, `checker`, `checked_at` | the record version, the tool's name, version and URL, when the check ran |
| `manifest` | its path and the sha256 of its bytes |
| `claim` | `id`, `text`, `where`, the claim digest of §1, its line in the manifest, and each passage its quote assertions name, with the line where a text file holds it exactly once |
| `assertion` | `kind`, `name`, its `position` among the claim's assertions of that kind and name, its `index` among all of them, and its line in the manifest |
| `check_type` | which proposition was checked; below |
| `reads` | per file read: artifact id, path, media type, `validity`, the pinned digest and the digest on disk, the `address`, the value `stored` there, that value `converted` where a conversion is declared, and the side for a `correspondence`. An `aggregate` has one entry per member |
| `printed`, `comparison` | the value as the manuscript prints it (the manifest's `reported`) or the passage a quotation asserts, and the `mode` and `tolerance` of §3.2, with the declared `places` and `conversion`, the `statistic` an `aggregate` computes, the `count` of its members and what it `computed`, and a `tie` where there was one |
| `outcome` | one of five words; below |
| `native_outcome`, `native_reason` | the `Outcome` of §4 and the `Reason` of §4.1, as this tool prints them |
| `stages`, `reader`, `warnings` | the three stages of §4, the backend and extraction toolchain of §5.1, the warnings of §4.1 |
| `history` | reserved; below |
| `execution` | only where a declared command writes a file the assertion reads: its state against the record of re-runs, and each command upstream with its argv, inputs, output and latest recorded re-run |

`validity` stays a fact about a file and its pin, as in §2, and is never folded into the
outcome. An `address` is the locator of §3.6 as written, tagged by its `kind`; a quotation's is
`passage`. No path is absolute, and no field is a boolean.

**`check_type` says what was checked.** Two tools can both report `verified` and have checked
different propositions: one compares a printed value with a stored one, another re-hashes a
file and never reads a value. The outcome alone does not say which, so the record does.
Closed.

| `check_type` | the proposition |
|---|---|
| `value-comparison` | a value the manuscript prints, against the value at an address in a file (`metric`, `table`, `value`) |
| `aggregate-comparison` | a value the manuscript prints, against a statistic computed over the values at several addresses (`aggregate`); no one stored value is the value compared |
| `passage-presence` | a passage occurs in a file (`quote`) |
| `correspondence` | the values at two addresses, in two files, agree |
| `artifact-identity` | a file's bytes are the bytes that were recorded; no value in it is compared |
| `lineage-check` | a file was produced by a recorded process from recorded inputs |
| `rerun-comparison` | what a command wrote when run again, against what it wrote before |
| `coverage-check` | whether something the manuscript states has a claim declared for it |
| `other` | a proposition none of the above names |

This tool emits the first four. The rest are reserved for a record written from another
tool's result, and nothing here writes one.

**`outcome` is five words defined by their preconditions**, and the checker's own word travels
beside it in `native_outcome`. `repro verify` prints what it always has.

| `outcome` | holds when | `native_outcome` here |
|---|---|---|
| `match` | every file was read, each address resolved, a comparison ran, and the two agreed | `verified` |
| `mismatch` | every file was read, each address resolved, a comparison ran, and the two differed | `mismatch` |
| `not-found` | the file was readable and an address did not resolve to exactly one value of the kind the assertion needs; nothing was compared | `not_found` |
| `not-checked` | no comparison occurred, because something it needed was absent or was skipped | `unchecked` |
| `error` | the tool failed | `error` |

The mapping is one function, total over `Outcome` by test and never by a default.

A schema says which fields a record may hold; `repro.record.validate` says which records are
possible, and refuses the rest: an `outcome` that is not what its `native_outcome` normalizes
to, or that the stages do not give; a `match` or `mismatch` against a file that was not read;
a `value-comparison` that is a `match` or `mismatch` without both the stored and the printed
value, a `correspondence` without the value on each side, a `passage-presence` without the
passage; a comparison under a declared conversion without the converted value; an
`aggregate-comparison` without its statistic, its count, every member's value or what was
computed; a match on a tie that prints neither of the tie's two values; a stored value on a record that is `not-checked` or an `error`; a pair of values on a
check type that compares none; a `validity` the two digests do not bear out.

**Unknown stays unknown.** A `native_outcome` from a checker not known to emit it, a
`check_type` of `other`, and an address `kind` this version has not seen are kept as written
and never read as success: `repro.record.read_outcome` gives `not-checked` for a `match` it
does not understand, and every exporter reads the outcome through it. A `match` under an
unknown native word is refused by the validator outright.

A claim that offers no evidence has no assertion, so no record. `repro verify` reports it.

The JSON Schema generated from the model is `docs/schemas/repro.check-0.1-experimental.schema.json`.

### Relation to `.repro/checks.jsonl`

Two models, told apart by name: `repro.record.ExportRecord` is one check written out for
another program, and `repro.models.CheckRecord` is one entry of the stored history, holding the
`CheckedAssertion`s a `repro verify --record` found changed.

A project may also keep a history, `.repro/checks.jsonl`, to which `repro verify --record`
appends what an assertion said each time a check found it changed. A check record is the
other thing, the present check written out for another program. It is derived when `repro export` runs, from the manifest and
the files, and this command stores nothing and reads no history.

The two describe some of the same facts, under the same names where the shapes allow:

| fact | check record | `.repro/checks.jsonl` |
|---|---|---|
| the assertion's identity | `claim.id`, `assertion.kind`, `assertion.name`, `assertion.position` | `claim_id`, `kind`, `name`, `position` |
| the claim as it read | `claim.digest` | `claim_digest` |
| the value or passage | `printed` | `printed` |
| when | `checked_at` | `checked_at` |
| the tool's outcome and reason | `native_outcome`, `native_reason` | `outcome`, `reason` |
| the bytes read | `reads[].on_disk`, per `reads[].artifact` | `digests`, a mapping from artifact to digest |
| where it looked | `reads[].address`, the locator as an object | `address`, the same locator as one line of text |

`position` follows one rule in both, so a record joins to its history on the four identity
fields. Three shapes differ on purpose. A record groups what belongs to the claim and to the
assertion, because it carries more of each than a history line does. `outcome` in a record is
the normalized word, so the tool's own is `native_outcome`. And a file read is an object, not
a digest in a mapping, because a record also states the pin and the `validity` of each file,
and the address is an object so that a program can read it without parsing a sentence.

`history`, where present, is a pointer into that record: how many states it holds for the
assertion and when the last was recorded. Nothing writes it yet. Once both are in one tree the
shared fields should come from one model, an assertion identity and a declared state that
`CheckedAssertion` and `ExportRecord` both embed; that is a follow-up to these two changes and
is not done by either.

## 7.11 RO-Crate export

Experimental, as the record of §7.10 is, and a projection of that record and of nothing else.

`repro export ro-crate` writes the check records as an RO-Crate 1.3 metadata document,
`ro-crate-metadata.json`, whose root is the directory the manifest is in. It reads records
only, so a file that no record names is not in the crate: an artifact that no assertion reads,
and that no command upstream of one reads or writes.

| in the record | in the crate |
|---|---|
| a file read, or a command's input or output | a `File` at its declared path, with `sha256` for the bytes on disk, `encodingFormat`, the pinned digest and the `validity` of §2; under a `#` identifier where it is absent or outside the project |
| the manifest | a `File` with its `sha256` |
| the claim | a schema.org `Claim` |
| the checked assertion | a `CheckAction` whose `instrument` is the checker and whose `object` is the claim |
| the address and the stored value | a `PropertyValue` naming the file, with the locator of §3.6 as canonical JSON |
| a declared command | a `HowTo` holding its argv, its declared inputs and its declared output |
| its latest recorded re-run | a `CreateAction` as Process Run Crate 0.6 describes one: `instrument`, `object`, `result`, `startTime`, `endTime`, `actionStatus` |

RO-Crate has no term for the address inside a file, for a printed value against a stored one,
for the check type or for the outcome. Those are terms of a profile of this tool's own,
`https://reproducible.science/ro-crate/claim-check/0.1/`, version `0.1-experimental`, declared
with `conformsTo` on the root data entity and mapped in `@context`. The profile's page defines
each term. Conformance to Process Run Crate is declared only where the records hold a re-run.

The projection loses nothing: `repro.export.rocrate.from_ro_crate` reads a crate back into the
records it was written from, for every record this version understands. A `match` it does not
understand is written `not-checked`, as §7.10 requires of every exporter, with its
`native_outcome` kept as written. No date in the document is taken when it is written, so the
same records give the same bytes.

A record carries no license, and RO-Crate requires the root data entity to have one, so the
crate says in words that none is stated. A check refers to the commands upstream of what it
reads and does not restate them.

## 8. What this composes with

| layer | prior art | relation |
|---|---|---|
| entity/activity/agent provenance | W3C PROV-O | export target; no ontology defined here |
| signed ordered attestation | in-toto, SLSA | wraps a report where external attestation is needed |
| packaging at rest | RO-Crate 1.3, Process Run Crate 0.6 | export target: `repro export ro-crate`, §7.11 |
| content-addressed pipelines | DVC | complementary; no claim model there |
| claim-to-evidence entailment | FEVER, SciFact, CliniFact | a different relation; see §0 |
| repository artifact auditing | adduce | interoperates via manifest format and rule entry point |
| agent trace graphs | LEDGER | exposes claim-support paths; returns no verdict |
| results shown on a pull request | SARIF 2.1.0, GitHub code scanning | export target, from the check records; lossy (§7.5) |

The contribution is §3 and §4: one contract spanning quotations, reported values, and values
read from two artifacts at once, and a three-stage outcome that separates a value that
disagrees, a value that is absent, and a check that never ran.

## 9. Conformance

An implementation conforms when:

1. It reports the three stages separately and derives the flattened outcome from them.
2. A missing toolchain yields `execution=unavailable`, never `completed`.
3. A backend defect yields `execution=failed`, never `unavailable`.
4. A pointer that does not resolve yields `extraction=absent`, never `comparison=mismatch`.
5. `reported` is compared as a decimal at its printed precision, never as a binary float.
6. Every decision names the claim digest, artifact digest, backend, backend version,
   extraction toolchain, that toolchain's version, and the digest of what it produced. A
   decision over two artifacts names the artifact digest, the locator digest and the
   extraction digest of each side, since one field cannot hold two, and a decision over a
   list of members names them for each member.
7. A version or digest that was sought and not obtained is recorded as `unknown`, never
   omitted, so it stays distinguishable from one that was never sought.
8. A broken pin marks every decision against that artifact non-authoritative.
9. The engine returns facts and computes no verdict.
10. No library entry point prints, exits, or mutates global state.
11. A two-sided assertion with one side unresolved yields `not_found`, never `mismatch`, and
    carries the failing side's reason.
12. A spelled-out number is converted only where the locator declares `cardinal_word`, and
    refused with `number_as_word` otherwise.
13. A stored value is converted only where the assertion declares a `conversion`, exactly and
    before the comparison, and the decision names the conversion and records both values.
14. A compared value exactly halfway between two values at the printed precision agrees with
    either, the decision records the tie, and a value that is not exactly halfway is rounded
    half to even.
15. Where `places` is declared, a `reported` written to another number of decimal places is a
    `mismatch` with reason `places_mismatch`, whatever the artifact holds.
16. An aggregate is compared only where every member it declares resolves to a finite number,
    its statistic is computed exactly and compared by the rule of a single value, ties
    included, and its decision records what each member read. A statistic over fewer members
    than were declared is never a match.

Conformance is executable: `packages/claims/tests/conformance/` holds 36 fixtures, each with
canonical expected JSON. They cover `verified`, `mismatch`, `not_found`, `unchecked` and
`not_offered`, the pointer-escaping and undeclared-artifact cases, an unpinned artifact, a
broken pin, five table-addressing cases, six over `correspondence` and the prose locator —
two sides agreeing, two sides disagreeing, one side that does not resolve, a spelled-out number
refused, one pair of anchors selecting two different values, and a prose value against a
literal — and four over a printed table read as text: a cell bound by the row's leading cells
and its divider, the same cell with no `after`, which is not a number, a leading anchor the
document does not hold, and a trailing anchor that would split the number. Those four also
declare the three stages of §4, as do two over a conversion: a stored fraction that agrees
with the printed percentage beside the same address with no conversion declared, which does
not, and a stored fraction that rounds to another percentage at the printed precision; and
two over §3.8: a value exactly halfway between two printed values, asserted once as each
neighbor and once as neither, and a value printed to two places where one is declared; and
three over an `aggregate`: a mean with no finite expansion that agrees at the printed
precision, the best run printed as the mean, and a member that does not resolve where the
mean of the others is the printed value.

Each fixture declares its outcome, its reason, and the validity of every artifact. The outcome
alone cannot tell a defect in the tool from a fact about the document: three cases share
`unchecked` and twelve share `not_found`, and only the reason separates an undeclared artifact
from an absent file, or an ambiguous anchor pair from a number written as a word.

Two rows of §4 have no fixture: `error`, which needs a backend defect, and the
extractor-missing form of `unchecked`. Neither is producible from a file on disk alone, so
they are exercised by the test suite rather than by the corpus. The expected JSON records the
flattened outcome; the three stages are asserted in the suite.
