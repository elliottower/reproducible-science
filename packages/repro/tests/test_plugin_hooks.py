"""The plugin's hooks, which run inside someone's editing session and ship untested.

A hook is the one part of this project that executes without being invoked. It reads a JSON
payload on stdin, runs on every matching tool call, and its failure mode is a broken session
rather than a red test. The three that shipped before this file had no test of any kind, so
the properties they promise in their own docstrings -- never break, never block, stay quiet --
were promises and nothing else.

`unfrozen_plan_before_run.py` is the first `PreToolUse` hook here, and the first that could
deny a command. That it does not is the property most worth pinning.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
HOOKS = ROOT / "packages" / "repro" / "plugin" / "hooks"

#: Every plugin in the workspace that registers hooks. `test_hooks_json_has_the_shape_the
#: _runtime_requires` reads all of them, because the defect it guards against was in all four.
PLUGIN_HOOKS = sorted(
    (ROOT / "packages" / package / "plugin" / "hooks" / "hooks.json")
    for package in ("citations", "prereg", "repro", "results")
)

#: The matchers, which sit under a top-level `hooks` key. Reading through that key rather than
#: from the root is not cosmetic: a file whose events are at the root loads nowhere.
REGISTRY = json.loads((HOOKS / "hooks.json").read_text())["hooks"]

FROZEN = "**Status:** FROZEN at `abc123def456`\n**Plan sha256:** `" + "0" * 64 + "`\n"


def run(hook: str, payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HOOKS / hook)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
    )


def declared_hooks() -> list[str]:
    return [
        entry["command"].rsplit("/", 1)[-1]
        for hooks in REGISTRY.values()
        for group in hooks
        for entry in group["hooks"]
    ]


def plan(tmp_path: pathlib.Path, body: str) -> pathlib.Path:
    directory = tmp_path / "experiment"
    directory.mkdir(exist_ok=True)
    (directory / "PREREG.md").write_text(body)
    return directory


#: Event names a matcher may be filed under. A key outside this set at the top level is the
#: shape that shipped for four releases: the runtime reads `hooks` and `modules` there and
#: nothing else, so a file listing `PostToolUse` at the root registers no hook at all.
EVENTS = frozenset(
    {
        "PreToolUse",
        "PostToolUse",
        "UserPromptSubmit",
        "Notification",
        "Stop",
        "SubagentStop",
        "PreCompact",
        "SessionStart",
        "SessionEnd",
    }
)


@pytest.mark.parametrize("path", PLUGIN_HOOKS, ids=lambda p: p.parents[1].parents[0].name)
def test_hooks_json_has_the_shape_the_runtime_requires(path):
    # Every hook this project ships was unreachable from its first commit until 2026-08-30,
    # because the events sat at the root and the loader looks for them one level down. The
    # suite passed throughout: it parsed this file itself and asked the runtime nothing.
    document = json.loads(path.read_text())
    assert set(document) <= {"hooks", "modules"}, (
        f"{path} has {sorted(set(document) - {'hooks', 'modules'})} at the top level; the "
        f"loader reads only `hooks` and `modules` there and registers nothing else"
    )
    assert "hooks" in document or "modules" in document, f"{path} declares neither"
    assert set(document.get("hooks", {})) <= EVENTS, (
        f"{path} files a matcher under {sorted(set(document.get('hooks', {})) - EVENTS)}, "
        f"which is not an event the runtime dispatches"
    )


@pytest.mark.parametrize("hook", declared_hooks())
def test_every_declared_hook_exists_and_is_executable(hook):
    path = HOOKS / hook
    assert path.is_file(), f"{hook} is registered in hooks.json and not present"
    assert path.stat().st_mode & 0o111, f"{hook} is not executable"


@pytest.mark.parametrize("hook", declared_hooks())
def test_no_hook_breaks_the_session_on_rubbish(hook):
    """Constraint 1 of every hook's docstring. A hook that raises interrupts someone's work."""
    out = subprocess.run(
        [sys.executable, str(HOOKS / hook)],
        input="this is not json",
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert out.returncode == 0, out.stderr


@pytest.mark.parametrize("hook", declared_hooks())
def test_no_hook_speaks_when_given_an_empty_payload(hook):
    assert run(hook, {}).stdout.strip() == ""


HOOK = "unfrozen_plan_before_run.py"


def test_an_unfrozen_plan_is_reported_before_an_analysis_runs(tmp_path):
    directory = plan(tmp_path, "# Plan\n\n**Status:** DRAFT\n\nWe will measure X against Y.\n")
    out = run(HOOK, {"tool_input": {"command": "python analysis.py"}, "cwd": str(directory)})
    assert "carries no freeze" in out.stdout
    assert "prereg freeze" in out.stdout


def test_a_frozen_plan_says_nothing(tmp_path):
    directory = plan(tmp_path, f"# Plan\n\n{FROZEN}\nWe will measure X.\n")
    out = run(HOOK, {"tool_input": {"command": "python analysis.py"}, "cwd": str(directory)})
    assert out.stdout.strip() == ""


def test_a_command_that_runs_no_analysis_says_nothing(tmp_path):
    """It fires on every Bash call. A hook that speaks on `git status` gets uninstalled."""
    directory = plan(tmp_path, "# Plan\n\n**Status:** DRAFT\n\nWe will measure X.\n")
    for command in ("git status", "ls -la", "cat README.md", "echo hi"):
        out = run(HOOK, {"tool_input": {"command": command}, "cwd": str(directory)})
        assert out.stdout.strip() == "", f"spoke on {command!r}"


def test_a_runner_behind_another_word_is_still_a_run(tmp_path):
    directory = plan(tmp_path, "# Plan\n\n**Status:** DRAFT\n\nWe will measure X.\n")
    for command in ("uv run python fit.py", "poetry run pytest", "make analysis"):
        out = run(HOOK, {"tool_input": {"command": command}, "cwd": str(directory)})
        assert "carries no freeze" in out.stdout, f"missed {command!r}"


def test_a_directory_with_no_plan_says_nothing(tmp_path):
    out = run(HOOK, {"tool_input": {"command": "python x.py"}, "cwd": str(tmp_path)})
    assert out.stdout.strip() == ""


def test_the_plan_above_the_working_directory_governs_it(tmp_path):
    directory = plan(tmp_path, "# Plan\n\n**Status:** DRAFT\n\nWe will measure X.\n")
    nested = directory / "src" / "deep"
    nested.mkdir(parents=True)
    out = run(HOOK, {"tool_input": {"command": "python x.py"}, "cwd": str(nested)})
    assert "carries no freeze" in out.stdout


def test_a_template_nobody_has_filled_in_is_left_alone(tmp_path):
    """Telling an author to freeze a blank form is worse than saying nothing."""
    stub = "# Plan\n\n**Status:** DRAFT\n\n" + "N/A — not applicable.\n" * 14
    directory = plan(tmp_path, stub)
    out = run(HOOK, {"tool_input": {"command": "python x.py"}, "cwd": str(directory)})
    assert out.stdout.strip() == ""


def test_the_hook_never_denies_the_command(tmp_path):
    """`PreToolUse` can block. This one must not: a check that can halt the work it observes
    is a check that gets switched off."""
    directory = plan(tmp_path, "# Plan\n\n**Status:** DRAFT\n\nWe will measure X.\n")
    out = run(HOOK, {"tool_input": {"command": "python analysis.py"}, "cwd": str(directory)})
    assert out.returncode == 0
    emitted = json.loads(out.stdout)
    assert "permissionDecision" not in json.dumps(emitted), "the hook must never deny"
    assert emitted["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
