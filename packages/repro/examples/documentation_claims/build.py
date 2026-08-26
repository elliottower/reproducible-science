"""Declare the specification's own fixture count as a correspondence, and pin both sides.

The sentence in `docs/SPEC.md` and the output of `ls -1 .../cases` are both artifacts. Neither
number is written here. `build.py` writes anchors and a pointer; what sits between the anchors
and what sits at the pointer are read at verification time, and the only way to make the claim
pass is to edit one of the two documents.

That is the whole difference from a `metric`, which would need `reported: "25"` -- this file's
transcription of a sentence the manifest quotes but does not read.

    python3 probe.py && python3 build.py
    repro verify docclaims.yaml --policy publication
"""

from __future__ import annotations

import os
import pathlib
import subprocess

import yaml
from repro import Digest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = pathlib.Path(
    subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=HERE,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
)

#: The anchors bracket the value in the sentence
#: "`packages/repro/tests/conformance/` holds 25 fixtures, each with canonical expected JSON."
#: They are literal text, matched after the normalization a quotation is matched under.
BEFORE = "holds"
AFTER = "fixtures, each with canonical expected JSON"


def pin(identifier: str, path: pathlib.Path, media_type: str, base: pathlib.Path = HERE) -> dict:
    """Declared relative to the manifest, so the file is committable and machine-independent."""
    return {
        "id": identifier,
        "path": os.path.relpath(path, base),
        "media_type": media_type,
        "digest": {"algorithm": "sha256", "value": Digest.of_file(path).value},
    }


def manifest(spec: pathlib.Path, probe_pointer: str) -> dict:
    return {
        "schema_version": "repro/1",
        "project": "the specification's claim about the suite beside it",
        "artifacts": [
            pin("spec", spec, "text/markdown"),
            pin("probe", HERE / "probe.json", "application/json"),
        ],
        "claims": [
            {
                "id": "spec-fixture-count",
                "registration": "not_applicable",
                "registration_note": "an exhaustive count over a declared directory; no "
                "outcome was selected from alternatives, so no plan could have fixed one",
                "where": "SPEC.md 9",
                "text": "The specification states the number of fixtures the conformance "
                "suite holds.",
                "evidence": [
                    {
                        "kind": "correspondence",
                        "name": "fixture-count",
                        "sides": [
                            {
                                "name": "stated",
                                "artifact": "spec",
                                "locator": {
                                    "kind": "prose",
                                    "before": BEFORE,
                                    "after": AFTER,
                                    # The specification writes the count as a numeral. The
                                    # revision this example also checks writes it as a word,
                                    # and asks for the conversion there rather than here.
                                    "form": "decimal",
                                },
                            },
                            {
                                "name": "measured",
                                "artifact": "probe",
                                "locator": {"kind": "tree", "pointer": probe_pointer},
                            },
                        ],
                    }
                ],
            }
        ],
    }


def main() -> int:
    out = HERE / "docclaims.yaml"
    document = manifest(ROOT / "docs" / "SPEC.md", "/probes/fixtures_at_head/value")
    out.write_text(yaml.safe_dump(document, sort_keys=False, width=110))
    print(f"  wrote {out.name}: 1 claim over {len(document['artifacts'])} artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
