# Backlog

## The plan

Decided 2026-08-27. One distribution, one CLI, one state directory, many
independently usable capabilities. The order below exists because several of these
steps move files, and moving files under unmerged work costs more than waiting.

**Phase 0 -- preserve what is finished.** Land the branches carrying completed
correctness work before anything relocates: `fix/include-following-and-digests`
(the `citations coverage` include walk and six digest sites),
`pin-the-extractor` (the extraction toolchain record), `citations-coverage`.
Tag the last five-package state so it can be checked out after the move.

**Phase 1 -- consolidate, in bisectable commits.** Not one mega-commit. A
candidate branch produced in one pass is fine; an unreviewable single diff is not.

1. Move modules into one `src/repro/` tree. No behaviour changes, imports only.
2. One `pyproject.toml`. Four publish workflows and four tag patterns deleted.
3. One CLI: `repro citations verify`, `repro results seal`, `repro prereg freeze`,
   composed under `repro check`.
4. One state directory `.repro/`, replacing whatever each tool creates today.

Each step is its own commit and leaves the suite green.

**Phase 2 -- the contract.** `outcomes.py` stops being propagation and becomes an
import. `citations` reports `extraction: absent` because it uses the same enum,
not because someone kept two copies in step.

**Phase 3 -- the manuscript binder.** `\result{key}{value}`, the `.clm`
handshake, the proposals layer, claim-versus-occurrence. Blocked until the phases
above settle, and blocked on one thing found by the demo: `citations` cannot read
`.tex` at all today -- `TEXT_SUFFIXES` omits it, so a LaTeX manuscript routes to
`pdftotext`, returns nothing, and grades every quotation `unchecked`.

### Naming, decided

Distribution `reproducible-science`; command `repro`; import `repro.citations`,
`repro.results`, `repro.prereg`. Internal modules are purpose-named -- `objects`,
`outcomes`, `store`, `ledger`, `schema`. Not `core`, not `common`, not `utils`,
which accumulate whatever has no other home. Extras only for genuine dependency
weight: `reproducible-science[pdf]`.

### The rule for ever splitting again

Publish a separate distribution only when one of these holds: it has an
independent maintainer community; it releases on its own schedule; other projects
depend on it without depending on this one; it implements a stable external
protocol; it carries dependencies inappropriate for the main install; or it can
evolve without coordinated schema changes here. None of the five first-party
packages clears that bar today.

### Keep the model small

Six types, not fifty: `Artifact`, `Rendition`, `Claim`, `Evidence`, `Observation`,
`CheckResult`, with `Evidence` a union of quote, metric, table-cell and file
variants. Preregistration is not evidence and should not be forced into that
hierarchy -- it shares artifacts, digests and outcomes while owning
`Registration`, `Amendment`, `OrderingConstraint`.

### Keep import-linter after the merge

Package boundaries currently prevent bad imports mechanically; module boundaries
must replace that protection explicitly rather than inherit it. Capability modules
depend on `objects`, `outcomes`, `store`, `schema`; `manuscript` and `export`
depend on public capability APIs; `cli` depends on everything; nothing below
depends on anything above it.

### Not yet examined

How the adjacent validity-coding CLI and the decision-scope work tie in. Both are
separate repositories with their own commands, and whether they become capability
modules, plugins, or stay independent is an open question.

Everything decided or raised in the design session of 2026-08-27, so none of it
depends on anyone's memory. Ordered by what blocks what, not by preference.

## Buildable now, nothing blocks them

**Zenodo deposit builder.** Promote `scripts/build_zenodo_deposit.py` from
`cross-design-evidence-discordance` into the library. The domain knowledge is
already written down and hard-won: never zip `paper/` (it carries cover letters
and per-reviewer manuscript versions into a public archive); exclude `.results`
(sealed run hashes stay local), peer review, third-party data available from its
own repository, and build output; name the zip for the repository with no version
suffix, because Zenodo versions the record; cite the **concept** DOI, never the
version DOI; relate sibling deposits with `references`/`isReferencedBy`, never
`isPartOf` and never `isSupplementTo` (which invites the reading that self-deposits
corroborate each other). The script must refuse to overwrite an existing archive,
assert no `paper/` entry leaked in, and report file count and size against the
previous deposit. adduce's equivalent is 21 lines with `[AUTHOR REVIEW REQUIRED:
Lastname, Firstname]` in it; this is not the same category of thing.

**Venue adapters.** ACM Artifact Appendix, NeurIPS and ACL checklists. These
encode what a venue asks for, which is stable across years and tedious to
reconstruct. Every generated answer must be marked a draft: a generated appendix
that reads as authored is the same defect as an inferred claim counted as verified.

**Zero-config first run.** `adduce check .` works on any repository; `repro verify`
requires a hand-written manifest. That single difference is most of the adoption
gap. `repro check .` with no manifest should report what it could check and offer
to scaffold rather than refusing.

**Manifest scaffolder.** Draft candidate claims from a repository, as adduce does
-- but write them to the proposals layer, never into the canonical file. adduce
puts drafts in its authoritative manifest and marks them `status: draft`, so its
source of truth contains guesses. Keeping guesses out entirely is the better
boundary and it costs nothing.

**GitHub Action**, with the score ratchet idea but not the score. See below.

## The contract work

**Propagate the outcome vocabulary.** `repro/core/outcomes.py` implements the
three-stage model -- execution, extraction, comparison, reported separately,
because "collapsing them is how a missing extractor becomes a quotation that
failed to check out." `docs/SPEC.md` describes it as the shared contract. Exactly
one of four packages implements it, and the package doing the most verification by
volume -- `citations`, 5,686 quotations -- does not. Move the vocabulary into the
shared layer and make all four speak it. Until then `citations verify` should at
least say in its output that it cannot distinguish extractor drift from an absent
quotation.

**Rendition pinning.** `Result.extraction_digest` is computed at verify time and
never written down, so a later run has nothing to compare against. Its own
docstring already argues the case: "The artifact's pin establishes that the bytes
did not change; this establishes that the reading of them did not, which a pin
cannot." Record `extraction.sha256` (gates), plus tool, version, argv, platform,
locale and time (diagnostics only -- gating on platform would fail an identical
rendition reproduced on another OS). Store the extracted text as an immutable
derived artifact so verification works offline with no extractor installed.
Backfilled records must be marked as a baseline: re-extracting today cannot
establish what was read months ago.

**`repro` must become the umbrella it claims to be.** It declares `citations`,
`prereg`, `results-cli` and `provenance-core` as dependencies and imports them in
2, 0, 0 and 2 files. It is currently the fifth sibling, not the integrator. One
`repro check` should run the whole workflow -- plan frozen, inputs sealed, runs
recorded, quotations resolving, assertions holding -- and report one status. Keep
the four separately publishable; someone who wants quotation checking should not
inherit a ledger. When a sibling is imported standalone and the umbrella is
installed, say so once.

## Blocked on the manuscript binder

**`\result{key}{value}` and the `.clm` handshake.** The compiler writes each
declared occurrence and its printed value to a build artifact; the tool joins on
keys and never parses prose. This is what lets the core stop interpreting LaTeX.
Wrap the value rather than the sentence, so several claims can live in one
sentence and the printed number can be checked against the run. A bare
`\claim{key}` marker remains available for a qualitative assertion. Ship
`\providecommand` fallbacks so a co-author without the package still compiles, and
an identical PDF.

**Proposals layer.** `evidence.proposals/` holding agent suggestions; acceptance
and rejection are ledger events. This is the operational meaning of declared
versus inferred.

**Claim versus occurrence.** One claim, many appearances -- abstract, results,
caption, conclusion -- with `values_must_agree`. This catches an abstract saying
8.3% while the results section says 8.4%.

**`0 inferred bindings counted as verified`** as a line in `check` output. Inferred
evidence may help an author and can never contribute to a verified-coverage number.

**Front-end adapters** for Markdown, Typst, Quarto and Jupyter. Cheap once the
sidecar is format-neutral; each is a way of writing the same declaration. Blocked
only because there is no declaration syntax yet.

**Claim views** -- author, reviewer, machine, public -- so a maximally expressive
sidecar does not become an unreadable wall.

## Packaging: one package, one CLI

Decided 2026-08-27, not yet done. Five published packages -- `citations`,
`prereg`, `results-cli`, `repro`, `provenance-core` -- release in lockstep from
one tag with one changelog, share only hashing primitives, and require a user to
learn four command names. `repro` declares the other four as dependencies and
imports them in 2, 0, 0 and 2 files, so the designated integrator is really a
fifth sibling.

Collapse to one distribution:

- One package. All source ships; `provenance_core` becomes an internal module
  rather than a published package.
- One CLI with subcommand namespaces -- `repro check`, `repro citations verify`,
  `repro results seal`, `repro prereg freeze` -- so the ecosystem is discoverable
  from `repro --help` instead of requiring a user to already know that four
  commands exist.
- Extras reserved for genuinely optional third-party dependencies, `repro[pdf]`
  for pypdf and pdfplumber. Not for splitting first-party code: an unimported
  module costs nothing, so an extra that gates one buys ceremony and no benefit.

Two things this fixes structurally rather than by discipline. The umbrella can no
longer declare dependencies it does not use, because there is nothing to declare.
And the shared vocabulary stops being a propagation project -- one codebase, one
`outcomes.py`, every caller importing the same names because they are in the same
tree. The layering that `import-linter` currently enforces across packages it
enforces equally well across modules.

The cost is that `pip install citations` stops working for anyone who has it. The
packages are two months old with few users and already release together, so the
break is cheap now and expensive after any promotion. That is the same reasoning
as fixing the contract before it has consumers, and it points the same way: do it
before the audience arrives, not after.

## Deliberately not doing, with reasons

**A composite score.** adduce's 54/100 and its tiers are hand-weighted and
uncalibrated, and its "reviewer time to first result" is an additive constant
table with no timing data behind it. Importing that would import the
heuristic-presented-as-measurement problem this project exists to name. A verdict
per assertion is the product.

**Context fingerprints for semantic drift.** Recording normalized prefix, value and
suffix to flag `semantic_review_required` re-introduces a heuristic through the
back door and will fire on every reflow. If the author rewrote the sentence, the
author knows.

**Git notes as primary storage.** Not fetched by default, which the proposal that
raised them concedes. Fine as replication, wrong as a home.

## Waiting on a second instance

**`prereg freeze --brief <file>`.** Hash a constraint artifact into the freeze
record, so the brief that bounded a blinded predictor and the freeze it constrains
live in one record instead of split across `prereg` and `results seal`. A real
ergonomic gain, and it does not overclaim: the record would say a named file
existed at freeze time, which is what a hash can carry. Enforcement stays where it
is, in how the predictor was run.

Held because n=1. `knockout-epistasis-dynamics` needs it; nothing else does yet,
and a flag shaped around one project's workflow is a guess about the second. The
protocol is a composition of shipped primitives and needs no flag to follow, so
nobody is blocked in the meantime. Build it when a second project reaches for the
same pattern and the two disagree about what the brief is.

## Smaller, recorded so they are not lost

- `citations coverage` over-reports on scare quotes: the LaTeX quotation marks around a
  scare-quoted term are counted as quotations. On one real paper this turned one
  genuine unpinned quotation into a report of seventeen. Belongs in `DEFECTS.md`.
- Six inline `hashlib.sha256(text.encode())` sites were replaced with
  `provenance_core.sha256_of_text`; two remain in standalone hook scripts that
  cannot import the package, and both already name UTF-8 explicitly.
- `results`' claim binding is a heuristic: `--location` is stored and never
  parsed, and a number counts as bound if its printed form appears in any claim
  string. The manuscript-addressing gap is shared with adduce, not unique to it.
- `provenance_core/digests.py` justifies itself with "a platform whose default
  encoding is not UTF-8", but `str.encode()` defaults to UTF-8 in CPython 3
  regardless of locale. The consolidation is still right; the stated reason is not.

- `research/pdf-readers/bench_real_corpus.py` records the corpus root as it was
  given: line 29 reads `CORPUS_ROOT` from the environment, line 140 writes
  `str(ROOT)` into the artifact. The run behind `real_corpus_by_reader.json` was
  invoked with an absolute path, so the artifact carries a home directory and a
  private repository name in `/corpus/root`, and two `pdf-extract` panic strings
  carry a cargo registry path under the same home. The default is the relative
  `"corpus"`, so re-running it from the corpus directory records a relative root
  and the artifact stops naming a machine. Not urgent: the file is byte-identical
  to the copy the paper repository pins (`4bdb0228`), that repository is private,
  and the anonymized drop substitutes both strings before its manifest is built.
  Re-running changes the six per-reader counts the manuscript prints, so it waits
  until nothing is pinned to them.

## Relationship to adduce

MIT, by Harshil Chudasama, released 2026-08-04, and it ships a `CITATION.cff`.
`repro` already registers as an adduce rule. It is a repository-hygiene linter
with a good packaging story: 78 rules, 17 categories, checklist and appendix
drafting, six archival exports, an `applies_to` gate, and refuse-to-overwrite
discipline. Its claim traceability is not competitive and its own documentation
says so -- claims are the first ten keyword-proximity regex hits, `where` is inert,
`\input` is not followed despite a docstring claiming otherwise, and nothing in the
check path is hashed. Take the ideas, cite the source where an idea is taken.
