"""Draw the article sample, deterministically and without a language's RNG.

A seed alone does not fix a sample: `random.shuffle` is an implementation detail and two
languages seeded identically produce different orders. Ordering by `sha256(seed || key)`
depends on nothing but the seed and the frame, so anyone can reproduce the draw.

Run before any article is opened. Writes the ordered frame and the selected identifiers so
both are frozen alongside the registration.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys

SEED = "20260824"
SAMPLE_SIZE = 60
RESEARCH_TYPES = ("replication", "reproduction")

HERE = pathlib.Path(__file__).parent


def field(block: str, name: str) -> str:
    match = re.search(rf'\n\s*{name}\s*=\s*[{{"]([^}}"]*)', block, re.I)
    return match.group(1).strip() if match else ""


def entries(bibliography: str) -> list[dict]:
    blocks = [b for b in re.split(r"\n(?=@\w+\s*\{)", bibliography) if b.lstrip().startswith("@")]
    out = []
    for block in blocks:
        if field(block, "type").lower() not in RESEARCH_TYPES:
            continue
        out.append(
            {
                "key": re.search(r"@\w+\s*\{\s*([^,]+)", block).group(1).strip(),
                "doi": field(block, "doi"),
                "type": field(block, "type"),
                "year": field(block, "year"),
                "domain": field(block, "domain"),
                "code_swh": field(block, "code_swh"),
                "code_url": field(block, "code_url"),
                "code_doi": field(block, "code_doi"),
            }
        )
    return out


def order_key(entry: dict) -> str:
    """Position in the permutation: sha256 of the seed and the article's DOI."""
    identifier = entry["doi"] or entry["key"]
    return hashlib.sha256((SEED + identifier).encode()).hexdigest()


def main(bibliography_path: str) -> int:
    text = pathlib.Path(bibliography_path).read_text(errors="replace")
    frame = entries(text)
    ordered = sorted(frame, key=order_key)
    for position, entry in enumerate(ordered):
        entry["position"] = position
        entry["order_key"] = order_key(entry)

    payload = {
        "seed": SEED,
        "permutation": "sha256(seed || doi), ascending",
        "bibliography_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "frame_size": len(frame),
        "sample_size": SAMPLE_SIZE,
        "selected": [e["key"] for e in ordered[:SAMPLE_SIZE]],
        "ordered_frame": ordered,
    }
    out = HERE / "frame.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"  frame {len(frame)}, selected {SAMPLE_SIZE}")
    print(f"  wrote {out}  sha256 {hashlib.sha256(out.read_bytes()).hexdigest()[:16]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
