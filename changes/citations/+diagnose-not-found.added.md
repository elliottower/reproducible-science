A `not found` says where the passage stopped matching, and what the source reads there.

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
