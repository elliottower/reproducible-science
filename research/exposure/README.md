# exposure

A deterministic record of what an agent read, for use with preregistered analysis.

`SPEC_v2.md` is the current argument; `SPEC_v1.md` is the prior version, kept as provenance. This is how to run it.

## Install

Add to `~/.claude/settings.json` for every session, or `.claude/settings.json` in a
study repo to scope it to that project:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Read|Edit|Write|NotebookEdit|Grep|Glob|Bash",
        "hooks": [
          {
            "type": "command",
            "command": "/Users/elliottower/Documents/GitHub/reproducible-science/exposure/hooks/exposure_log.py"
          }
        ]
      }
    ]
  }
}
```

The log lands at `~/.claude/exposure.jsonl` by default. Point `EXPOSURE_LOG` at the
study directory to keep a study's record beside its data:

```bash
export EXPOSURE_LOG="$PWD/exposure.jsonl"
```

## What it records

One JSONL line per file-touching tool call:

```json
{"ts":"2026-08-24T19:06:24-0400","session":"s1","cwd":"/study","tool":"Read","paths":["/data/outcomes.csv"]}
```

The model neither produces this record nor can edit it. That is the entire point: an
agent's account of what it read is a claim, and this is an observation.

## What it does not do

- **It does not block.** Blocking belongs in a `PreToolUse` hook and is not written yet.
- **It does not prove absence.** Bash path extraction is heuristic — a runtime-constructed
  path, a heredoc, or a shell-expanded glob can be missed. The log supports "this was
  read," never "nothing was read."
- **It does not resist tampering.** The file is append-only by convention, not by
  construction. A study that needs the record to be evidence should hash-chain it, which
  is what `results` already does for run ledgers.
- **It never interrupts the session.** Every failure path exits 0 silently. A logger that
  can halt the work it observes gets switched off, and a logger that is off records
  nothing.

## Testing it

```bash
export EXPOSURE_LOG=/tmp/exposure_test.jsonl
echo '{"session_id":"t","tool_name":"Read","tool_input":{"file_path":"/data/outcomes.csv"}}' \
  | ./hooks/exposure_log.py
cat "$EXPOSURE_LOG"
```
