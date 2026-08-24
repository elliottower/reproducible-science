# Audit findings, 2026-08-24

Four independent audits of the workspace. Every finding below was confirmed by execution
against the code as it stood, not inferred. Ticked items are fixed with a regression test that
fails against the old behaviour.

Severity 1 means the tool reports something false — a check that passes when it should fail,
or a defect in the tooling emitted as a scientific finding. Those are the reason this project
exists, so they are not "bugs" in the ordinary sense.

## Severity 1 — the tool certifies something false

| | finding | where |
|---|---|---|
| [x] | The normalized fallback stripped every non-alphanumeric character, so `p < 0.05` matched a source reading `p = 0.05`, and `-0.42` matched `0.42` | citations/verify.py |
| [x] | A quotation folding to the empty string matched every source (`"" in doc`) | citations/verify.py |
| [x] | Duplicate artifact ids drop every declaration but the last; a broken pin vanishes from the report and `strict` passes with zero violations | repro/verify.py |
| [x] | Regeneration compares the produced file against the record's own declared digest, never against the pinned artifact, so a record can declare its own answer | repro/regenerate.py |
| [x] | A no-op command "reproduces" an output that was copied in as its own input | repro/regenerate.py |
| [x] | `Path.relative_to` is lexical, so an absolute artifact path containing `..` escapes the sandbox on both the read and write side | repro/regenerate.py |
| [x] | `compare_decimal` reports two identical values as a mismatch beyond 28 significant digits — a tool defect emitted as a contradicted manuscript | repro/verify.py |
| [x] | Duplicate CSV column names resolve to the last silently; a duplicated predicate column reports a present row as absent | repro/resolve.py |
| [x] | Duplicate JSON keys resolve last-wins, while YAML raises for exactly this | repro/resolve.py |
| [x] | A failed `page` assertion is reported `verified`; no policy reads decision warnings | repro/verify.py |
| [x] | A confirmatory claim spanning several artifacts is `ordered` when only one has a producing run | repro/verify.py |
| [x] | An undeclared `registered_plan` is never pin-checked, so an unpinned plan yields `ordered` — and declaring it scores worse | repro/verify.py |
| [x] | Reusing a `run_id` defeats the confirmatory-claim guard and `verify` reports all checks passed | results/cli.py |
| [x] | `reanchor` launders a truncated ledger to "chain intact" — `TRUNCATED` omitted from the refusal list | results/cli.py |
| [x] | An edited last line becomes permanently invisible after the next append | results/ledger.py |
| [x] | The preregistration Log section is outside the hash and freely deletable | prereg/cli.py |
| [x] | `freeze --force` logs `nothing run` even directly after a `results seen` entry | prereg/cli.py |
| [x] | Marker-prefixed lines inserted after a freeze are not covered by the hash | prereg/cli.py |
| [x] | The audit response cache is trusted unconditionally, so a forged cache file verifies a fabricated bibliography entry offline | citations/audit.py |

## Severity 2 — a check that cannot fail, or fails for the wrong reason

| | finding | where |
|---|---|---|
| [x] | A malformed claims file is skipped and `--strict` still exits 0 | citations/cli.py |
| [x] | `unchecked` and `unpinned` never fail `--strict`; a deleted source or a missing `pdftotext` passes CI | citations/verify.py, cli.py |
| [x] | Common BibTeX closing-brace styles drop entries and merge fields across entries | citations/audit.py, build.py |
| [x] | `resolve` matches on title alone when a record has neither author nor year | citations/resolve.py |
| [x] | `freeze` outside a git repository reports success and records a commit-shaped string | prereg/cli.py |
| [x] | `check` at a repo root exits 0 when a plan was never frozen | prereg/cli.py |
| [x] | `--osf` drops a heading whose capitalization differs, silently | prereg/osf.py |
| [x] | A `canon_version` mismatch leaves the status `INTACT` and is never printed | results/ledger.py |
| [x] | `verify --files` keys by path, so only the most recent seal of a path is checked | results/cli.py |
| [x] | An unreadable or directory artifact path crashes the whole run instead of producing a report | repro/verify.py |
| [x] | Negative array indices are unchecked: `-99` becomes a backend defect, `-1` silently resolves | repro/resolve.py |
| [x] | Policy severities collide on `claim_id/kind`, so an error-level mismatch can render as a warning | repro/renderers/sarif.py |
| [x] | A regression is verified against whatever revision is checked out, and counts are labelled with the pinned commit | repro/regression.py |
| [x] | `EntryStatus.usable` ignores `dirty` | repro/corpus.py |
| [x] | The adduce rule passes at confidence 1.0 without consulting `UNPINNED_ARTIFACT` | repro/integrations/adduce.py |
| [x] | A missing output digest is reported as `INPUT_UNPINNED` | repro/regenerate.py |
| [x] | Two declared inputs outside the root sharing a basename overwrite each other in the sandbox | repro/regenerate.py |
| [x] | `urlopen` in `prereg/osf.py` has no timeout | prereg/osf.py |
| [x] | `audit.py` reads `.bib` without `errors=`, so a latin-1 file raises | citations/audit.py |

## Severity 3 — documentation asserting what the code does not do

| | finding | where |
|---|---|---|
| [ ] | The manuscript says ordering is unimplemented; it is implemented, called and graded | paper/DRAFT_v2.md |
| [ ] | "Every figure stated in Section 6 is checked this way" — 16 claims, many §6 numbers unchecked | paper/DRAFT_v2.md |
| [ ] | The §6.2 warning counts (213 / 155 / 8) have no producing artifact: the counter is never incremented | scripts/generate_figures.py |
| [ ] | The abstract says thirteen fixtures; the paper, the spec and the repository say eighteen | paper/DRAFT_v2.md |
| [ ] | "two, three, and five errors" — strict returns seven | paper/DRAFT_v2.md |
| [ ] | "365 content-addressed sources" — 366 declared, 355 pinned | paper/DRAFT_v2.md |
| [ ] | SPEC §7 names `inverted`/`undeclared`; the code, the SARIF ids and the policy keys say `violated`/`unchecked` | docs/SPEC.md |
| [ ] | SPEC claims the regeneration sandbox confines writes; it sets a working directory | docs/SPEC.md |
| [ ] | SPEC's `Reason` and `Warning` vocabularies omit values the code defines; the validity table omits `artifact_absent` | docs/SPEC.md |
| [ ] | SPEC §9 / §6.1 conformance accounting does not match the fixture set; no `error` or `broken_pin` fixture exists | docs/SPEC.md, tests/conformance |
| [ ] | CODEBOOK §6's worked example of the comparison rule is backwards, in a pinned registration | experiments/.../CODEBOOK.md |
| [ ] | `make hooks` passes explicit `--hook-type` flags, so the commit-msg hook is never installed | Makefile, CONTRIBUTING.md |
| [ ] | "a green `make qa` locally means a green pull request" — three CI steps are outside `qa` | CONTRIBUTING.md |
| [ ] | `packages/repro/README.md` documents a `verify` that shells out to three tools, and a quick start that cannot succeed | packages/repro/README.md |
| [ ] | `README.md` documents a top-level `plugins/` directory that no longer exists | README.md |
| [ ] | `scripts/README.md` credits a superseded script and the wrong section for the resolver figures | scripts/README.md |
