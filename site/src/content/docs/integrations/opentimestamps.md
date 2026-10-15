---
title: OpenTimestamps
description: prereg and results date a digest against Bitcoin through the OpenTimestamps calendars.
---

A digest written into a repository shows only that the repository agrees with itself: whoever
holds the repository can rewrite its history. `prereg freeze` and `results timestamp` send a
digest to the OpenTimestamps calendars, which commit it into a Bitcoin block within a few hours.
A complete proof needs no calendar to check.

## Reads

- `prereg freeze`: the digest of the frozen file.
- `results timestamp`: the digest of the ledger's head. Each ledger line names the hash of the
  one before it, so a proof of the head dates every earlier event.
- To complete a proof: the calendars, and the block's merkle root from two block explorers,
  blockstream.info and mempool.space.

## Writes

- `PREREG.md.ots` beside the plan, and one proof per frozen amendment.
- `.results/timestamps/NNNNNN-<head>.ots`, added and never replaced.

## Command

```bash
prereg freeze                # the stamp is requested as part of the freeze
prereg timestamp             # hours later: complete the proof and report the block
results timestamp
```

`prereg check` and `results verify` read the proofs with no network.

## Refuses or never does

- There is no flag to freeze without a timestamp. A freeze made with no network still succeeds,
  and the timestamp is reported as owed until `prereg timestamp` makes it.
- Only the digest leaves the machine, with a random nonce appended first, so a calendar does not
  receive the file's hash.
- A stamp is refused unless at least two calendars accept it. Completing a proof never
  contacts a calendar outside the `opentimestamps` library's whitelist.
- Two explorers that disagree about a block are an error, not a vote.
- `results timestamp` does not stamp a ledger whose chain does not verify, and writes nothing
  when no calendar answers.
- A forced re-freeze keeps the earlier proof under its own digest.

## Does not claim

A timestamp bounds when a digest existed. It does not show when work began, or that an
experiment was not run before the plan was frozen.

## The other project

[opentimestamps.org](https://opentimestamps.org/).

Not affiliated with or endorsed by OpenTimestamps.
