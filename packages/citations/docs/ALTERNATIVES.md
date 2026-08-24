# Why these practices, and what was rejected

Companion to `BEST_PRACTICES.md`. Every recommendation there was chosen over something, and
several were chosen over an earlier version of itself. This records the reasoning so a later
reader can overturn a decision on its merits rather than rediscovering the argument.

---

## One file per experiment, not five

**Rejected:** `PREREG.md` + `TIMELINE.md` + `AMENDMENTS/` + `DEVIATIONS.md` + `MANIFEST.sha256`,
with a vocabulary distinguishing amendments from deviations.

**Why.** Git already hashes every file, so the manifest restates what `git show <sha>:file`
proves. The timeline is the log. Amendments and deviations differ only in whether results had
been seen, and that is one column — so filing them in separate directories records the same fact
twice and adds a decision the author must get right each time.

The deeper problem is that a five-file system has five ways to fall out of sync, and the failure
is silent. A researcher who forgets to update `TIMELINE.md` has a repository that lies. One
append-only file has one failure mode: you forgot to append, which is visible as a gap.

**The strongest counter.** Separate files are easier to diff and easier for a script to parse.
True, and it would matter at scale — but a study has perhaps ten log lines, and a human reading
one file beats a script parsing five.

**What survives from the rejected design:** the results-access column. That idea was the good one.

---

## OSF headings, not a bespoke template

**Rejected:** keeping the existing house format, which already covers most of the same ground
under better-reading names.

**Why.** The existing format is genuinely good — the `msms-subspace-collapse` pre-registration
has an integrity protocol, a frozen threshold, a separated exploratory phase, and an appended
deviation recording that its own criterion failed. That last item is the behavior no template
produces and no tooling enforces.

But it is bespoke, which means each new document re-decides what to include. Two OSF headings
are missing from the house format and both map onto errors that actually occurred:
*Foreknowledge of data or evidence* would have forced a declaration on results that were reused
as if confirmatory, and *Inference criteria* turns a hoped-for outcome into a committed threshold.

Adopting the headings costs nothing and removes the per-document decision.

**The strongest counter.** Twenty-seven headings for a small study is heavy, and most will read
N/A. Fair — but an explicit N/A is information, and a heading you skipped is indistinguishable
from one you never considered.

**Not done:** retrofitting fifty-one existing documents. Converting a year of work to a template
is the theater this document exists to prevent.

---

## AsPredicted's eight questions

**Rejected as the default, kept as an option.**

**Why.** AsPredicted is lighter, widely used, and honest for a small study. It was not chosen as
the default because it lacks a foreknowledge field, and foreknowledge is the specific thing that
goes wrong here — exploratory results existing before a plan is written.

Use it when a study genuinely has eight questions' worth of content. Do not use the heavier
template as a way of looking rigorous.

---

## OSF registration for the plan, not a git tag

**Rejected:** signed git tags as the freeze mechanism.

**Why.** A signed tag is cryptographically sound and free, and it is the native git answer. It
fails on the only axis that matters: the author controls the repository. A reviewer discounting
"you could have rewritten this" is discounting exactly the property a tag cannot supply. The
value of registration is not cryptographic — it is that someone else holds a dated copy.

**Where tags still earn their place:** naming freeze commits so `git show prereg/I3:...` resolves
by name rather than by remembered hash. Do that, but do not mistake it for attestation.

---

## Not cryptographic timestamping

**Rejected:** OpenTimestamps, RFC 3161 timestamp authorities, a continuous stamping tool that
hashes every script and dataset at creation.

**Why.** A timestamp proves a lower bound — this existed by T. It cannot prove an upper bound —
that the work did not start earlier. The failure mode the field actually names is
pre-registering after results are known, and that is entirely compatible with a valid timestamp
on the pre-registration: you run the experiment, see the answer, write the plan, stamp it.

Continuous stamping of scripts and data is stronger, because it establishes an ordering — plan,
then code, then results. But it still cannot exclude an unstamped earlier run. You cannot prove
a negative about your own private activity, and no anchor changes that.

**Worth knowing:** the ML literature names this (*PARKing*, preregistering after results are
known) and reaches for pre-registration as the remedy rather than cryptography.

**The strongest counter, and it holds:** continuous stamping is nearly free and makes fraud more
expensive. Adopt it if you like. Just never describe it as proof of no peeking, which is the
claim it invites and cannot support.

---

## Not "because a reviewer will ask"

**Rejected reasoning**, not a rejected practice.

Pre-registration is close to dead as an ML norm. The workshop series collapsed — seventy-three
proposals in 2020 to twenty-two in 2021, and results-stage follow-through from twenty-three
papers to three. `preregister.science` has been untouched since 2022 and no ML venue offers
Registered Reports. TMLR is the pointed case: pre-registration was pitched to it directly and it
chose to change acceptance criteria instead.

So "a reviewer will ask" is false, and building a practice on it would be building on a norm that
does not exist.

**The reason that survives:** a paper arguing for validity standards that does not meet them has
a self-consistency problem, and would have one even if nobody ever checked. That reason does not
depend on anyone asking.

**Consequence:** do not advertise it. One sentence in methods. A paper that markets its own rigor
invites an audit of the rigor instead of the result.

---

## Three platforms, not one

**Rejected:** consolidating onto OSF alone, and separately, cutting Zenodo entirely.

**Why the plan and the code split.** They want opposite properties. A revisable prediction is not
a prediction, so the plan must freeze. Code legitimately iterates — bugs, dependency breaks,
tolerances derived from fixtures — so freezing it once would be absurd. One mechanism for both
forces a bad choice.

**Why not OSF alone.** OSF is file storage, not a git remote; mirroring loses the commit history
that makes freezes checkable. Its GitHub addon exists because they know this.

**Why Zenodo survived a cut.** It was nearly dropped on the grounds that OSF registrations
already snapshot code and mint a DOI. The argument that kept it: arXiv and bioRxiv are community
reading lists, and posting imposes a cost on every reader in the field. Zenodo is an archive and
imposes on nobody. For exploratory or AI-heavy work wanting a citable dated record without
claiming a field's attention, that distinction is real.

**Correction to a claim made in its favour:** a published Zenodo deposit cannot be deleted, and
files cannot be edited — only superseded, with the old version permanently resolvable. This was
offered as an advantage and is the opposite. It is also why the tool works: a timestamp you can
revise establishes nothing.

---

## The claims/audits split

**Rejected:** one record per claim holding both the extraction and the judgment.

**Why.** They have different standing. Verbatim quotations with a pinned sha256 are checkable by
anyone holding the PDF, and reusable by someone who rejects every verdict. Statuses and verdicts
are contestable and ours. Merged, a reader cannot tell which parts they are being asked to trust.

The split was verified lossless before adoption: every key landed on exactly one side, and all
2,940 quotations still resolved afterwards.

**The strongest counter.** Two files per claim is more to maintain. Answered by having the loader
rejoin them, so every consumer still sees one object.

---

## The quote gate, and its known hole

**Adopted**, with a limitation that must be stated rather than hidden.

The gate catches fabrication: quotations that do not exist in the artifact they cite. It cannot
catch misinterpretation — a real, resolving quotation attached to a claim it does not support.

**And it is defeatable by truncation.** A pinned substring ending before a qualifying clause
verifies a claim its source contradicts. Observed: `"We trained 50"` resolves while the source
continues `"...each for 2, 4, and 8 layered variants and 5 refits each for 12 layered
(GPT2-small)"`. The record claimed fifty; the truth was five.

This is a measurement-validity failure in the verification apparatus itself, which is why it is
documented rather than quietly patched.

---

## Things deliberately not built

**A provenance timeline of AI contribution.** Conflates two separate questions — were decisions
fixed before outcomes, and how was AI used. The first is answered by the log; the second by one
methods sentence.

**A Claude Code plugin for timestamping.** Would have wrapped a mechanism that does not support
the claim it implies. See above.

**A central freeze registry across experiments.** Superseded by per-folder freezes plus a
generated index. A central file must be kept in sync with N folders, and that is a job which will
eventually not get done.

**Migrating research repositories to stripped-down clean copies.** Tried on three, reverted. The
paper repositories needed it because they were unshippable. Research repositories are different:
the experiments, data and pre-registrations are the substance, so a copy holding only the paper
is a different artifact rather than a tidier one — and the copies dropped pre-registrations,
which is the failure this whole document exists to prevent.
