"""A worked example that passes, and then fails on purpose.

`repro demo` writes a small project and runs the real workflow over it: seal the inputs, run
the analysis, record the claim, verify the evidence. Every line under a `$` is a command that
ran in the demo directory, and what follows it is what that command printed. Nothing is
simulated, so the ledger and the manifest left behind are the ones the commands wrote.

Then it breaks the project twice, because a walkthrough where everything passes says nothing
about what the tool is for. The two it produces are the two facts the report keeps apart:

  * a **broken pin**. One word of the discussion is edited. No assertion reads that sentence,
    every assertion still holds, and the run fails anyway -- the file that was read is provably
    not the file that was declared.
  * a **mismatch**. The number the manuscript reports is changed and the manifest re-pinned, so
    the pin is clean and the comparison is the only thing left to fail. The manuscript states
    one number and the run holds another.

Collapsing the two into one red line is the confusion this package exists to prevent, and a
demo that only ever passes never shows the difference. Both edits are undone at the end, so the
directory is left exactly as it was scaffolded, and verifying.

**This module prints, and belongs to the command-line surface rather than the library.**
Conformance rule 10 in `docs/SPEC.md` -- no library entry point prints, exits, or mutates
global state -- governs the engine, the policy and the renderers, all of which return values.
A walkthrough is a transcript; it is written where `cli.py` is written, and sits directly under
`repro.cli` in the layer graph.

Offline and deterministic throughout. The analysis draws from a seeded generator and reads no
clock, so `results.json` has the same bytes on every machine -- which is what lets the
manuscript state the number as a literal and lets a regeneration record pin the output.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys

from repro.exceptions import ReproError

# --------------------------------------------------------------------------------- templates

DATA_CSV = """\
subject,before,after
s01,0.412,0.455
s02,0.388,0.419
s03,0.501,0.577
s04,0.447,0.481
s05,0.365,0.430
s06,0.520,0.548
s07,0.478,0.527
s08,0.394,0.451
s09,0.433,0.470
s10,0.509,0.531
s11,0.462,0.528
s12,0.401,0.437
"""

ANALYSIS_PY = '''\
"""Compute the effect this project reports, from `data.csv` and a fixed seed.

Standard library only, no network, and no clock. A manuscript that states a number as a
literal needs that number to be the same number on every machine, or a check that the two
agree is a check on the hardware. The bootstrap therefore draws from `random.Random(SEED)`
rather than from the module-level generator, which carries whatever anything else imported
into the process has already drawn from it.

    python analysis.py
"""

from __future__ import annotations

import csv
import json
import pathlib
import random

HERE = pathlib.Path(__file__).resolve().parent
DATA = HERE / "data.csv"
OUT = HERE / "results.json"

SEED = 8675309
RESAMPLES = 2000


def paired_differences(path: pathlib.Path) -> list[float]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [float(row["after"]) - float(row["before"]) for row in csv.DictReader(handle)]


def mean(values: list[float]) -> float:
    return sum(values) / len(values)


def bootstrap_interval(values: list[float], seed: int, resamples: int) -> tuple[float, float]:
    """The 2.5th and 97.5th percentiles of the resampled means."""
    rng = random.Random(seed)
    n = len(values)
    means = sorted(mean([values[rng.randrange(n)] for _ in range(n)]) for _ in range(resamples))
    return means[int(0.025 * resamples)], means[int(0.975 * resamples)]


def main() -> int:
    differences = paired_differences(DATA)
    low, high = bootstrap_interval(differences, SEED, RESAMPLES)
    effect = {
        "delta": round(mean(differences), 4),
        "ci_low": round(low, 4),
        "ci_high": round(high, 4),
    }
    results = {
        "bootstrap": {"resamples": RESAMPLES, "seed": SEED},
        "effect": effect,
        "n": len(differences),
    }
    # Sorted keys and a trailing newline, so two runs of this script produce the same bytes and
    # a digest over the output means something. No `generated_at`: a timestamp would make the
    # file differ from itself on every run, and the manifest would have to declare the field
    # volatile to get an exact comparison back.
    OUT.write_text(json.dumps(results, indent=2, sort_keys=True) + "\\n")
    print(
        f"wrote {OUT.name}: delta {effect['delta']} "
        f"[{effect['ci_low']}, {effect['ci_high']}] over n={len(differences)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

PIN_PY = '''\
"""Write `repro.yaml`: pin every file by content, and declare what the manuscript claims.

Run this after the analysis, and again after editing any file the manifest names. A pin is a
sha256 over the bytes, so an edited file stops matching the digest recorded for it and
`repro verify` reports that before it reads a single number out of the file.

The effect size is transcribed nowhere here. The manuscript states it in prose, `results.json`
holds it at a pointer, and the `correspondence` reads both at verification time -- so the only
way to make that claim pass is to edit one of the two documents. The second claim uses a
`metric`, which does need the number written into this file, where nothing checks the
transcription against the manuscript that prints it.

    python pin.py
"""

from __future__ import annotations

import hashlib
import pathlib

import yaml

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "repro.yaml"

#: id -> (path relative to this file, media type). The id is what evidence refers to, so a file
#: renamed here keeps every assertion that names it.
FILES = {
    "data": ("data.csv", "text/csv"),
    "analysis": ("analysis.py", "text/x-python"),
    "results": ("results.json", "application/json"),
    "paper": ("paper.md", "text/markdown"),
}


def digest(identifier: str) -> dict:
    """The same sha256 `repro verify` recomputes over the file before reading anything out."""
    name = FILES[identifier][0]
    return {"algorithm": "sha256", "value": hashlib.sha256((HERE / name).read_bytes()).hexdigest()}


def pin(identifier: str) -> dict:
    name, media_type = FILES[identifier]
    return {"id": identifier, "path": name, "media_type": media_type, "digest": digest(identifier)}


def manifest() -> dict:
    return {
        "schema_version": "repro/1",
        "project": HERE.name,
        "artifacts": [pin(identifier) for identifier in FILES],
        "claims": [
            {
                "id": "effect-size",
                "text": "The intervention moved the mean score by 0.045 points.",
                "where": "Results",
                "evidence": [
                    {
                        "kind": "quote",
                        "artifact": "paper",
                        "section": "Methods",
                        "text": (
                            "We compared the paired differences with a bootstrap "
                            "over 2000 resamples"
                        ),
                    },
                    {
                        "kind": "correspondence",
                        "name": "effect-delta",
                        "sides": [
                            {
                                "name": "manuscript",
                                "artifact": "paper",
                                # Two literal anchors, not a pattern: the author says where the
                                # value sits rather than describing a number to go looking for.
                                # The value is what sits between them.
                                "locator": {
                                    "kind": "prose",
                                    "before": "moved the mean score by",
                                    "after": "points",
                                },
                            },
                            {
                                "name": "run",
                                "artifact": "results",
                                "locator": {"kind": "tree", "pointer": "/effect/delta"},
                            },
                        ],
                    },
                ],
            },
            {
                "id": "resamples",
                "text": "The interval comes from 2000 bootstrap resamples.",
                "where": "Methods",
                "evidence": [
                    {
                        "kind": "metric",
                        "artifact": "results",
                        "name": "resamples",
                        # A string, always. YAML reads 3.20 as the float 3.2 and throws away the
                        # precision the manuscript chose.
                        "reported": "2000",
                        "pointer": "/bootstrap/resamples",
                    }
                ],
            },
        ],
        "regenerations": [
            {
                "id": "results-from-data",
                # argv, never a shell string, and it runs only under `repro verify
                # --regenerate`. The declared inputs are copied into an empty directory and the
                # command runs there, so a script reaching for a file the manifest never
                # declared fails instead of quietly passing.
                "command": ["python3", "analysis.py"],
                "inputs": [
                    {"artifact": "data", "digest": digest("data")},
                    {"artifact": "analysis", "digest": digest("analysis")},
                ],
                "output": {"artifact": "results", "digest": digest("results")},
            }
        ],
    }


def main() -> int:
    document = manifest()
    OUT.write_text(yaml.safe_dump(document, sort_keys=False, width=100))
    print(
        f"wrote {OUT.name}: {len(document['artifacts'])} artifacts pinned, "
        f"{len(document['claims'])} claims"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

PAPER_MD = """\
# A paired comparison, worked end to end

## Methods

Twelve subjects were measured before and after the intervention. We compared the paired
differences with a bootstrap over 2000 resamples, drawn from a generator seeded at 8675309,
and report the 2.5th and 97.5th percentiles of the resampled means.

## Results

The intervention moved the mean score by 0.045 points, with a 95 percent bootstrap interval
of [0.0365, 0.0552].

## Discussion

The interval excludes zero, and the effect is moderate against the spread of the twelve
paired differences. The data are invented and the numbers describe nothing. Every number
above has an address in `repro.yaml`.
"""

README_MD = """\
# repro-demo

A paired comparison, small enough to read in a minute and complete enough to check. Every
number in `paper.md` has an address in `repro.yaml`, and `repro verify` reads each one out of
the file it names.

## The files

| file | what it is |
|---|---|
| `data.csv` | twelve paired measurements, before and after |
| `analysis.py` | computes the effect from `data.csv` and a fixed seed; writes `results.json` |
| `results.json` | what the run produced: the effect, its interval, and the seed |
| `paper.md` | the manuscript, stating the effect in prose |
| `pin.py` | writes `repro.yaml`: pins every file by sha256 and declares the claims |
| `repro.yaml` | the manifest — four artifacts, two claims, three evidence assertions |
| `.results/` | the ledger: sealed inputs, the recorded run, and the claim bound to it |

## The commands

```console
$ python analysis.py                 # deterministic: same seed, same numbers
$ python pin.py                      # pin the files, declare the claims
$ repro verify                       # check every assertion against its artifact
$ repro verify --regenerate          # also: does the pinned code still produce results.json?
$ results verify                     # is the ledger chain intact?
```

## What each assertion asserts

**`quote`** — a passage occurs in `paper.md`. Matched against the extracted text after
normalization, never against the bytes, so a line break in the middle of the sentence does not
break it.

**`correspondence`** — `paper.md` and `results.json` hold the same number. The manuscript side
is addressed by two literal anchors (`moved the mean score by` … `points`) and the run side by
a JSON Pointer (`/effect/delta`). Neither side is the reference: when they disagree the report
prints both values and does not say which is wrong.

**`metric`** — `results.json` holds `2000` at `/bootstrap/resamples`. The number is transcribed
into `repro.yaml`, which is the weaker form: rewriting that one field makes the assertion pass
whatever the manuscript says. The correspondence above cannot be silenced that way, because no
number is written into the manifest for it to be rewritten.

Comparison is at printed precision. A manuscript printing `0.045` is not contradicted by a file
holding `0.0453`; one printing `0.0450` would be.

## Breaking it

Two failures, and they are not the same failure:

```console
# 1. a file that is not the file that was declared.
#    In paper.md, change "the effect is moderate" to "the effect is substantial".
$ repro verify
  BROKEN PIN  paper: pinned 4c11751b2019, found 6b5eaf3a3525
  ok    effect-size  quote      <broken_pin>
  ...
  policy publication: FAILED  (1 errors, 0 warnings)
```

No assertion reads that sentence, so all three still hold — and the run fails anyway. A pin is
a claim about bytes, and a different claim from any of the assertions; the two assertions that
read `paper.md` come back marked `<broken_pin>` rather than authoritative. `python pin.py`
re-pins and accepts the edit.

```console
# 2. a number the artifact does not hold.
#    In paper.md, change "by 0.045 points" to "by 0.055 points".
$ python pin.py
$ repro verify
  MISS  effect-size  correspondence effect-delta: manuscript 0.055, run 0.0453
  policy publication: FAILED  (1 errors, 0 warnings)
```

Re-pinning first is what isolates it: the pin is clean, this *is* the declared file, and what
it says contradicts the run.

Three further outcomes are worth producing by hand:

- delete `"delta"` from `results.json` and re-pin — `GONE`, `pointer_absent`. Silence is not
  contradiction: the file no longer says anything about the value, which is not the same as
  saying something that disagrees.
- change `after: points` to `after: percent` in `repro.yaml` — `GONE`, `passage_absent`. The
  anchor addresses nothing, which is a broken address rather than a wrong number.
- change `SEED` in `analysis.py`, re-run it, re-pin, and verify — the correspondence now fails
  on the number the manuscript still prints.

## Somewhere to experiment

The project is self-contained: no network, no data outside this directory, and nothing that
takes more than a second to run. It is a reasonable thing to hand to an agent — *change
something and tell me which check catches it* — because every check here is cheap, offline,
and answers with a reason rather than a verdict.

Two more things to add, once the shape is familiar:

- `prereg new "<title>"` writes a plan, and a claim marked `confirmatory` then needs a run
  record naming that plan and starting after it was registered.
- `results coverage paper.md` lists the numbers in the manuscript that no run is bound to.
"""

#: Everything the demo writes, and everything `--force` removes. Named explicitly rather than
#: clearing the directory, because a demo directory is somewhere people put their own notes and
#: `rm -rf` on a path a user typed is not a thing to do on their behalf.
OWNED = (
    "README.md",
    "analysis.py",
    "data.csv",
    "paper.md",
    "pin.py",
    "repro.yaml",
    "results.json",
    ".results",
)

FILES = {
    "data.csv": DATA_CSV,
    "analysis.py": ANALYSIS_PY,
    "pin.py": PIN_PY,
    "paper.md": PAPER_MD,
    "README.md": README_MD,
}

DESCRIPTIONS = {
    "data.csv": "twelve paired measurements",
    "analysis.py": "computes the effect from data.csv and a fixed seed",
    "paper.md": "the manuscript, stating that number in prose",
    "pin.py": "writes repro.yaml: pins every file, declares the claims",
    "README.md": "what each file is, and what to break next",
}

#: The manuscript edits the walkthrough makes, in order: a word no assertion reads, then the
#: number every assertion is about.
UNREAD_WORD = ("the effect is moderate", "the effect is substantial")
REPORTED_NUMBER = ("by 0.045 points", "by 0.055 points")

CLAIM_TEXT = "The intervention moved the mean score by 0.045 points."
RUN_ID = "demo-001"


# ------------------------------------------------------------------------------- scaffolding


def _console_script(name: str) -> str:
    """An installed entry point, resolved beside the interpreter that is running this.

    `results` ships no `__main__`, so it can only be reached as a console script. Taking the
    bare name off `PATH` finds a different environment's copy whenever `repro` was invoked by
    absolute path -- an unactivated virtualenv, a `pipx` shim -- and the demo would then write
    its ledger with one installation and verify it with another.
    """
    beside = pathlib.Path(sys.executable).parent / name
    return str(beside) if beside.exists() else name


def scaffold(target: pathlib.Path, force: bool = False) -> None:
    """Write the demo project into `target`, or raise rather than overwrite it."""
    if target.exists() and not target.is_dir():
        # `--force` removes named entries inside a directory; it does not delete whatever else
        # a user has at this path. Saying so beats a `NotADirectoryError` out of `iterdir`.
        raise ReproError(f"{target} exists and is not a directory")
    if target.exists() and any(target.iterdir()):
        if not force:
            raise ReproError(
                f"{target} is not empty. Pass --force to replace the demo's own files "
                f"({', '.join(OWNED)}), or name another directory."
            )
        for name in OWNED:
            existing = target / name
            if existing.is_dir():
                shutil.rmtree(existing)
            else:
                existing.unlink(missing_ok=True)

    target.mkdir(parents=True, exist_ok=True)
    for name, content in FILES.items():
        (target / name).write_text(content, encoding="utf-8")


def _edit(path: pathlib.Path, old: str, new: str) -> None:
    """Replace one literal in a file, or raise if it is not there.

    The walkthrough's two failures are edits to a template this module also writes, so a
    template reworded without its edit being updated would make both steps silently rewrite
    nothing -- and the demo would then narrate a failure while printing a passing report.
    """
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise ReproError(f"{path.name} does not contain {old!r}, so the demo cannot edit it")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# ------------------------------------------------------------------------------- walkthrough


def _say(*lines: str) -> None:
    print()
    for line in lines:
        print(line)


def _section(title: str, *lines: str) -> None:
    print()
    print(f"== {title} ".ljust(88, "="))
    for line in lines:
        print(line)


def _run(argv: list[str], cwd: pathlib.Path, shown: str) -> int:
    """Run one step and print it the way a terminal would have.

    `shown` is what the user would type; `argv` is what runs. The two differ only in how the
    interpreter and the console scripts are addressed -- see `_console_script` -- and printing
    an absolute path to a virtualenv in place of `repro` would make the transcript unreadable
    and uncopyable.
    """
    print(f"\n$ {shown}")
    try:
        completed = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=300)
    except FileNotFoundError:
        # Every tool the walkthrough drives is a declared dependency, so this is an installation
        # that lost one. Saying which is more use than a traceback, and the rest of the
        # walkthrough still demonstrates what it can.
        print(f"skipped: {argv[0]} is not installed")
        return 127
    except subprocess.TimeoutExpired:
        print("skipped: the command did not finish within 300s")
        return 124
    output = (completed.stdout + completed.stderr).rstrip("\n")
    if output:
        print(output)
    print(f"[exit {completed.returncode}]")
    return completed.returncode


def walkthrough(target: pathlib.Path) -> int:
    """Drive the real workflow over the scaffolded project, twice into a failure and back.

    Returns the exit code of the last verification, which is the one the closing message
    speaks for.
    """
    python = [sys.executable]
    results = _console_script("results")
    verify = [*python, "-m", "repro", "verify"]

    def run(argv: list[str], shown: str) -> int:
        return _run(argv, target, shown)

    _section(
        "1. record the run",
        "The ledger is what a claim is bound to later: what went in, what came out, in which",
        "order. It is append-only and hash-chained, so an edited line is reported rather than",
        "overwritten.",
    )
    run([results, "init"], "results init")
    run(
        [results, "seal", "data.csv", "analysis.py", "--role", "input"],
        "results seal data.csv analysis.py --role input",
    )
    run([*python, "analysis.py"], "python analysis.py")
    run(
        [results, "run", "results.json", "--run-id", RUN_ID, "--note", "paired bootstrap"],
        f'results run results.json --run-id {RUN_ID} --note "paired bootstrap"',
    )
    run(
        [results, "claim", CLAIM_TEXT, "--run-id", RUN_ID, "--location", "Results"],
        f'results claim "{CLAIM_TEXT}" --run-id {RUN_ID} --location Results',
    )
    run([results, "verify"], "results verify")

    _section(
        "2. declare the evidence, and check it",
        "`pin.py` writes repro.yaml: four artifacts pinned by sha256, two claims, three",
        "assertions over them. `repro verify` reads each assertion out of the artifact it",
        "names -- a passage from the manuscript, a number from the run, and the manuscript's",
        "own number against the run's, which is the one assertion no field in the manifest",
        "can be rewritten to satisfy.",
    )
    run([*python, "pin.py"], "python pin.py")
    run(verify, "repro verify")

    _section(
        "3. a file that is not the file that was declared",
        "One word of the discussion changes. No assertion reads that sentence, so every",
        "assertion still holds.",
    )
    _edit(target / "paper.md", *UNREAD_WORD)
    print(f'\n  (edited paper.md: "{UNREAD_WORD[0]}" -> "{UNREAD_WORD[1]}")')
    run(verify, "repro verify")
    _say(
        "Three assertions verified and the run failed. The digest says the bytes that were read",
        "are not the bytes that were declared, which is a fact about the file rather than about",
        "any number in it -- and the two assertions that read paper.md are marked",
        "<broken_pin>, because what they verified against is not the declared document.",
        "Re-pinning is how an edit is accepted:",
    )
    run([*python, "pin.py"], "python pin.py")
    run(verify, "repro verify")

    _section(
        "4. a number the artifact does not hold",
        "Now the number the manuscript reports changes, and the manifest is re-pinned first, so",
        "the pin is clean and the comparison is the only thing left to fail.",
    )
    _edit(target / "paper.md", *REPORTED_NUMBER)
    print(f'\n  (edited paper.md: "{REPORTED_NUMBER[0]}" -> "{REPORTED_NUMBER[1]}")')
    run([*python, "pin.py"], "python pin.py")
    run(verify, "repro verify")
    _say(
        "No broken pin this time: this is the declared file, and what it says contradicts the",
        "run. The report prints both values and names neither as wrong, because a byte",
        "comparison does not establish whether the manuscript or the analysis is in error.",
    )

    _section(
        "5. back to a project that verifies",
        "Both edits are undone, so paper.md is the file that was scaffolded and the README's",
        "instructions for breaking it by hand still describe the text they name.",
    )
    _edit(target / "paper.md", REPORTED_NUMBER[1], REPORTED_NUMBER[0])
    _edit(target / "paper.md", UNREAD_WORD[1], UNREAD_WORD[0])
    print("\n  (restored both edits to paper.md)")
    run([*python, "pin.py"], "python pin.py")
    return run(verify, "repro verify")


def demo(directory: str | None = None, force: bool = False) -> int:
    """Scaffold the demo project, then run the workflow over it."""
    # Relative by default, and never resolved: every path in the transcript is one the reader
    # can retype, and an absolute path to a temporary directory is neither short nor theirs.
    target = pathlib.Path(directory or "repro-demo")
    scaffold(target, force=force)

    print(f"wrote {target}")
    for name in sorted(FILES):
        print(f"  {name:<14} {DESCRIPTIONS[name]}")

    if walkthrough(target) != 0:
        # The closing message asserts something about the directory, so it is not printed on
        # the word of the script that wrote it. A demo that says a project verifies while
        # leaving one that does not is worse than no demo.
        _say(
            f"{target} does not verify after the edits were undone, which it should. The",
            "verification above says what is wrong with it.",
        )
        return 1

    _say(
        f"The project in {target} verifies. Its README lists three more failures worth",
        "producing by hand -- a pointer that no longer resolves, an anchor that addresses",
        "nothing, and a seed that changes the number the manuscript still prints.",
        "",
        f"    cd {target} && repro verify --regenerate",
    )
    return 0
