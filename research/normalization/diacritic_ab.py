"""One printed word, three encodings, and a matcher that reconciles none of them.

`pdftotext` renders an accented letter as a spacing accent followed by a dotless i --
`na¨ıve` for `naïve` -- and the other extractors produce their own variants. `verify.fold`
normalizes NFKC, which composes a combining mark onto the letter before it but does nothing
for an accent that arrives *before* its letter: NFKC expands the spacing accent into a space
plus a combining mark, welding a space into the middle of the word. The manuscript is right,
the extraction is legible to a human, and the quotation does not resolve.

Two candidates are measured here rather than argued about:

    broad    strip spacing accents, map dotless i, then NFKD and drop every combining mark.
             This is the fix as first proposed. It reconciles the encodings and makes accented
             and unaccented spellings interchangeable along the way.
    narrow   map dotless i, move a spacing accent onto the letter it precedes, then NFKC.
             The accent survives as an accent, so the encodings reconcile and nothing else
             becomes equal to anything.

Three measurements, and a fold change should have to pass all three: the encodings reconcile,
nothing that was distinguishable stops being so, and no quotation in a real corpus changes
state for a reason nobody read.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import unicodedata

from citations import verify as V
from citations.exceptions import ClaimFileError
from citations.models import load_claim_file

#: Spacing accents an extractor emits in place of a combining one, with the combining mark
#: each stands for. The ASCII backtick is deliberately absent: it is ordinary punctuation in a
#: quotation about code, and reading it as a grave accent would rewrite the passage.
COMBINING = {
    "¨": "̈",
    "´": "́",
    "¯": "̄",
    "¸": "̧",
    "˘": "̆",
    "˙": "̇",
    "˚": "̊",
    "˛": "̨",
    "˜": "̃",
    "˝": "̋",
}

ACCENT_THEN_LETTER = re.compile(f"([{''.join(COMBINING)}])([A-Za-zıİ])")

#: Every form of one printed word that reaches the matcher from one corpus of PDFs.
ENCODINGS = {
    "precomposed": "naïve",
    "combining": "naïve",
    "spacing accent, dotless i": "na¨ıve",
    "spacing accent, dotted i": "na¨ive",
}

#: Pairs that are different passages and must stay different. The last two are the failure the
#: `skeleton` docstring records: an earlier normalization made a reversed inequality and a
#: flipped sign read as quoted verbatim.
MUST_STAY_DISTINCT = [
    ("résumé", "resume"),
    ("Kästner", "Kastner"),
    ("naïve", "naive"),
    ("Cohen´s kappa", "Cohens kappa"),
    ("p < 0.05", "p = 0.05"),
    ("-0.42", "0.42"),
]


def _tail(s: str) -> str:
    """Everything `verify.fold` does after its normalization step, unchanged."""
    s = re.sub(r"[\x00-\x08\x0b\x0e-\x1f\x7f]", " ", s)
    s = s.replace("’", "'").replace("‘", "'")
    s = s.replace("“", '"').replace("”", '"')
    s = s.replace("—", "-").replace("–", "-").replace("−", "-")
    s = re.sub(r"-\s*\n\s*", "", s)
    return " ".join(s.split()).lower()


def broad_fold(s: str) -> str:
    s = s.translate({ord(c): "" for c in COMBINING} | {ord("ı"): "i", ord("İ"): "I"})
    s = unicodedata.normalize("NFKD", s)
    return _tail("".join(c for c in s if not unicodedata.combining(c)))


def narrow_fold(s: str) -> str:
    s = s.replace("ı", "i").replace("İ", "I")
    s = ACCENT_THEN_LETTER.sub(lambda m: m.group(2) + COMBINING[m.group(1)], s)
    return _tail(unicodedata.normalize("NFKC", s))


CANDIDATES = {"today": V.fold, "broad": broad_fold, "narrow": narrow_fold}


def reconciles() -> dict:
    """Does each candidate reduce the encodings of one word to one string?"""
    return {
        name: {
            "distinct_forms": len({fold(s) for s in ENCODINGS.values()}),
            "folds_to": sorted({fold(s) for s in ENCODINGS.values()}),
        }
        for name, fold in CANDIDATES.items()
    }


def conflates() -> dict:
    """Which pairs each candidate makes equal that the current one keeps apart."""
    return {
        name: [
            {"a": a, "b": b, "equal": fold(a) == fold(b), "equal_today": V.fold(a) == V.fold(b)}
            for a, b in MUST_STAY_DISTINCT
        ]
        for name, fold in CANDIDATES.items()
    }


def corpus(root: pathlib.Path):
    """Every claims file under `root` whose source is present and pins clean."""
    for claims_dir in sorted(root.glob("*/claims")) + sorted(root.glob("*/*/claims")):
        if "/.git/" in str(claims_dir):
            continue
        for path in sorted(claims_dir.glob("*.yaml")):
            try:
                claim_file = load_claim_file(path)
            except ClaimFileError:
                continue
            artifact = claim_file.artifact()
            if artifact is None or V.check_pin(artifact, claim_file.source.sha256).state != "ok":
                continue
            quotes = [
                (name, q.text, q.page)
                for name, c in claim_file.claims.items()
                for q in c.quotes
                if q.text
            ]
            if quotes:
                yield path, artifact, claim_file.source.extract_cmd, quotes


def over_corpus(root: pathlib.Path) -> dict:
    """Run every quotation under each candidate and record every state that moved.

    The extraction is cached across the candidates and only the folding caches are cleared, so
    the two passes differ in one function and nothing else. A quotation is checked once per
    distinct (document digest, passage): two repositories keeping the same claims file against
    their own copy of one PDF would otherwise count one change as two.
    """
    baseline = V.fold
    seen: set[tuple[str, str]] = set()
    changes: list[dict] = []
    checked = documents = 0
    try:
        for path, artifact, cmd, quotes in corpus(root):
            digest = V.sha256(artifact)
            fresh = [(n, t, p) for n, t, p in quotes if (digest, t) not in seen]
            seen.update((digest, t) for _, t, _ in fresh)
            if not fresh:
                continue
            documents += 1
            checked += len(fresh)

            V.clear_caches()
            outcomes: dict[str, list] = {}
            for name, fold in CANDIDATES.items():
                V.fold = fold
                V.skeleton.cache_clear()
                outcomes[name] = [V.check_one(t, artifact, p, cmd) for _, t, p in fresh]
            V.fold = baseline

            for i, (name, text, page) in enumerate(fresh):
                today = outcomes["today"][i]
                for candidate in ("broad", "narrow"):
                    got = outcomes[candidate][i]
                    if today.state == got.state and sorted(today.warnings) == sorted(got.warnings):
                        continue
                    changes.append(
                        {
                            "candidate": candidate,
                            "claim_file": str(path),
                            "claim": name,
                            "passage": text,
                            "page": page,
                            "today": {"state": today.state, "warnings": sorted(today.warnings)},
                            "candidate_result": {
                                "state": got.state,
                                "warnings": sorted(got.warnings),
                            },
                        }
                    )
            print(f"{documents:>4}  {artifact.name[:46]:<48}{checked:>6} checked", flush=True)
    finally:
        V.fold = baseline
        V.clear_caches()

    resolved = dict.fromkeys(("broad", "narrow"), 0)
    lost = dict.fromkeys(("broad", "narrow"), 0)
    for change in changes:
        was, now = change["today"]["state"], change["candidate_result"]["state"]
        if was != "found" and now == "found":
            resolved[change["candidate"]] += 1
        elif was == "found" and now != "found":
            lost[change["candidate"]] += 1
    return {
        "documents": documents,
        "passage_checks": checked,
        "newly_resolved": resolved,
        "newly_unresolved": lost,
        "changes": changes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claims-root", type=pathlib.Path)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    args = parser.parse_args()

    report = {
        "question": "Can the matcher reconcile one printed word's encodings without loosening?",
        "encodings": dict(ENCODINGS),
        "reconciles": reconciles(),
        "conflates": conflates(),
        "over_corpus": over_corpus(args.claims_root) if args.claims_root else {},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "over_corpus"}, indent=1))
    if report["over_corpus"]:
        summary = {k: v for k, v in report["over_corpus"].items() if k != "changes"}
        print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
