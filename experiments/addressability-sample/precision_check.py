"""Estimate how many confirmations are coincidence, by confirming values that cannot be real.

A confirmation says a printed value occurs somewhere in the artifact. It does not say the
artifact holds *that* value: `3` occurs in any repository, and finding it is not evidence.
There is no ground truth to measure against -- nobody has labelled which of a paper's numbers
its data really contains -- so the false-positive rate is estimated against decoys instead.

A decoy is built from a real value by shifting every digit by a fixed amount, which preserves
the shape exactly (digit count, decimal places, magnitude) while producing a quantity the
paper never printed. Decoys colliding with any number the paper does print are discarded, so
what remains cannot be confirmed except by chance.

If real values in a tier confirm at rate `p` and shape-matched decoys confirm at rate `q`,
then `q / p` estimates the share of that tier's confirmations that are coincidence, and

    precision ~= 1 - q / p

Shifting is used rather than sampling so the estimate is reproducible without a seed, and
because near-miss perturbations (adding one to the last digit) would land on neighbouring
cells of the same table and overstate the collision rate.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from confirm_numbers import (BINARY, COMPRESSORS, MANUSCRIPT, TIERS, TRACEABLE,  # noqa: E402
                             build_index, collect, strength)

#: Digit shifts used to build decoys. Nine per value, which is enough that a tier of any
#: useful size has hundreds of trials behind its rate.
SHIFTS = range(1, 10)


def decoys(printed: str) -> list[str]:
    """Same shape and same leading significant digit, different quantity.

    Target-decoy competition rests on the Equal Chance Assumption: an incorrect match must be
    as likely against a decoy as against a real value. Shifting every digit violates it.
    Reported values are not uniform over leading digits -- one article's run 19 per cent on 1
    and 25 per cent on 9, being accuracies clustered in the nineties on a Benford-like tail --
    while every-digit decoys come out flat at 11 per cent each, a total variation distance of
    0.24. An artifact drawn from the same domain is dense where the real values are dense, so
    flat decoys land where it is sparse, match too rarely, and every precision figure computed
    from them reads high.

    Holding the first significant digit fixed and moving the rest preserves leading digit,
    magnitude and digit count, and changes only the information the match actually turns on.
    """
    out = []
    first = next((i for i, c in enumerate(printed) if c.isdigit() and c != "0"), None)
    for shift in SHIFTS:
        digits = []
        for index, character in enumerate(printed):
            if not character.isdigit() or index <= (first if first is not None else -1):
                digits.append(character)
                continue
            digits.append(str((int(character) + shift) % 10))
        candidate = "".join(digits)
        if candidate != printed and strength(candidate) == strength(printed):
            out.append(candidate)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scan")
    parser.add_argument("repo")
    args = parser.parse_args()

    root = pathlib.Path(args.repo)
    groups = collect(root)
    index, _ = build_index(
        groups["data"] + groups["spreadsheet"] + groups["binary"] + groups["compressed"]
        + groups["code"], root)

    records = [r for r in json.loads(pathlib.Path(args.scan).read_text())["records"]
               if r["kind"] in TRACEABLE]
    for record in records:
        record["strength"] = strength(record["printed"])
    printed_anywhere = {r["printed"] for r in records}

    print(f"\n  {args.scan}  against  {args.repo}")
    print(f"  {len(index):,} distinct values indexed; {len(groups['manuscript'])} "
          f"manuscript files excluded\n")
    print(f"    {'tier':10}{'values':>8}{'real hit':>10}{'decoys':>9}{'decoy hit':>11}"
          f"{'precision':>11}")

    overall = {"real": [0, 0], "decoy": [0, 0]}
    for tier in TIERS:
        row = [r for r in records if r["strength"] == tier]
        if not row:
            continue
        real_hits = sum(1 for r in row if r["printed"] in index)
        trials = [d for r in row for d in decoys(r["printed"]) if d not in printed_anywhere]
        decoy_hits = sum(1 for d in trials if d in index)

        overall["real"][0] += real_hits
        overall["real"][1] += len(row)
        overall["decoy"][0] += decoy_hits
        overall["decoy"][1] += len(trials)

        p = real_hits / len(row)
        q = decoy_hits / len(trials) if trials else 0.0
        precision = max(0.0, 1 - q / p) if p else float("nan")
        print(f"    {tier:10}{len(row):>8}{p:>10.0%}{len(trials):>9}{q:>11.1%}"
              f"{precision:>11.0%}" if p else
              f"    {tier:10}{len(row):>8}{p:>10.0%}{len(trials):>9}{q:>11.1%}{'--':>11}")

    p = overall["real"][0] / max(1, overall["real"][1])
    q = overall["decoy"][0] / max(1, overall["decoy"][1])
    print(f"\n    pooled: real {p:.0%}  decoy {q:.1%}  "
          f"=> {1 - q / p:.0%} of confirmations survive the null" if p else "")
    print("    (pooled figure is reported for completeness; the per-tier rates are the"
          " ones that mean anything)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
