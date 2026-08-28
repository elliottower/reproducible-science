`fold` drops combining marks instead of composing them. A renderer typesets `naïve` as a dotless
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
