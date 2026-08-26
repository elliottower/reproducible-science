"""The commit-msg hook and the workflow that rejects trailers, exercised against each other.

Both encode one fact: which trailers may not reach a commit. Neither had ever run against the
other, so they disagreed for a day -- the hook rewrote a co-authorship trailer to `Assisted-by:`
and the workflow rejected `Assisted-by:`, and the repository produced commits its own continuous
integration refused.

The pattern is read out of the workflow rather than restated here. A copy would be a third
artifact holding the same fact, free to drift from both, which is the shape of the defect this
file exists to close.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[3]
HOOK = ROOT / "scripts" / "commit_msg_attribution.py"
WORKFLOW = ROOT / ".github" / "workflows" / "attribution.yml"

#: Messages the hook is supposed to clean. Each is a form seen in this repository's own history.
DIRTY = [
    "a fix\n\nCo-Authored-By: Claude Opus 5 <noreply@anthropic.com>\n",
    "a fix\n\nCo-authored-by: Claude Opus 5 (1M context) <noreply@anthropic.com>\n",
    "a fix\n\nAssisted-by: Claude Opus 5\n",
    "a fix\n\nClaude-Session: https://claude.ai/code/session_01E5iZ74\n",
    "a fix\n\nCo-Authored-By: Jane Roe <jane@example.org>\nAssisted-by: Claude Opus 5\n",
]


def gate_pattern() -> str:
    """The regex the workflow greps commit messages with, read from the workflow itself."""
    steps = yaml.safe_load(WORKFLOW.read_text())["jobs"]["trailers"]["steps"]
    script = next(s["run"] for s in steps if "run" in s and "grep -qiE" in s["run"])
    # The pattern is the single-quoted argument on the line after `grep -qiE \`.
    found = re.search(r"grep -qiE\s*\\\s*\n\s*'([^']+)'", script)
    assert found, "the workflow's grep pattern moved; this test reads it and cannot guess"
    return found.group(1)


def cleaned(message: str, tmp_path: pathlib.Path) -> str:
    path = tmp_path / "COMMIT_EDITMSG"
    path.write_text(message)
    subprocess.run([sys.executable, str(HOOK), str(path)], check=True, capture_output=True)
    return path.read_text()


def rejects(pattern: str, message: str) -> bool:
    """Whether the workflow's grep would flag this message, using grep so the dialect matches."""
    done = subprocess.run(
        ["grep", "-qiE", pattern], input=message, text=True, capture_output=True, check=False
    )
    return done.returncode == 0


def test_the_workflow_pattern_is_readable_from_the_workflow():
    assert "co-authored-by" in gate_pattern().lower()


@pytest.mark.parametrize("message", DIRTY, ids=range(len(DIRTY)))
def test_what_the_hook_produces_is_what_the_workflow_accepts(message, tmp_path):
    assert rejects(gate_pattern(), message), (
        "this message should have been rejected before the hook ran; if it is not, the case no "
        "longer exercises the disagreement"
    )
    assert not rejects(gate_pattern(), cleaned(message, tmp_path))


def test_a_human_co_author_survives_the_hook_and_the_workflow(tmp_path):
    message = "a fix\n\nCo-Authored-By: Jane Roe <jane@example.org>\n"
    out = cleaned(message, tmp_path)
    assert "Jane Roe" in out
    assert not rejects(gate_pattern(), out)
