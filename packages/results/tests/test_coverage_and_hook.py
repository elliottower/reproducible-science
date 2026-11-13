"""The coverage command, and the hook that notices a number entering a manuscript."""

import hashlib
import json
import pathlib
import re
import subprocess
import sys

from results import cli

HOOK = pathlib.Path(__file__).resolve().parents[1] / "plugin" / "hooks" / "unbound_numbers.py"


def tracked_repo(tmp_path, claims=(), wrote=""):
    """A directory with a ledger holding the given claim texts, all bound to run `r1`. With
    `wrote`, the run recorded one output holding that text."""
    results = tmp_path / ".results"
    results.mkdir()
    run = {"event": "run", "run_id": "r1"}
    if wrote:
        (tmp_path / "out.json").write_text(wrote)
        digest = hashlib.sha256(wrote.encode()).hexdigest()
        run["outputs"] = [{"path": "out.json", "sha256": digest}]
    lines = [{"event": "init"}, run]
    lines += [{"event": "claim", "run_id": "r1", "claim": text} for text in claims]
    (results / "ledger.jsonl").write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    return tmp_path


def summary(out):
    """The counts from the report, so a test does not depend on column widths."""

    def count(label):
        match = re.search(rf"^\s*{re.escape(label)}\s+(\d+)", out, re.M)
        return int(match.group(1)) if match else None

    return {
        "bound": count("yours, bound to a run"),
        "unbound": count("yours, bound to nothing"),
        "cited": count("beside a citation"),
        "exempt": count("owing no claim"),
    }


def fire(payload):
    """Run the hook exactly as Claude Code does, and return what it told the model."""
    done = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, "the hook must never fail the tool call"
    if not done.stdout.strip():
        return None
    return json.loads(done.stdout)["hookSpecificOutput"]["additionalContext"]


def test_coverage_counts_bound_against_owed(tmp_path, monkeypatch, capsys):
    root = tracked_repo(
        tmp_path, ["accuracy reached 87.65 on the held-out split"], wrote='{"acc": 87.6512}'
    )
    paper = root / "paper.tex"
    paper.write_text(r"\begin{document}we report 87.65 and also 43.21\end{document}")
    monkeypatch.chdir(root)

    monkeypatch.setattr(sys, "argv", ["results", "coverage", str(paper)])
    code = cli.main()

    out = capsys.readouterr().out
    assert summary(out)["bound"] == 1
    assert summary(out)["unbound"] == 1
    assert "43.21" in out
    assert code == 0


def test_coverage_attributes_a_number_beside_a_citation(tmp_path, monkeypatch, capsys):
    root = tracked_repo(tmp_path)
    paper = root / "paper.tex"
    paper.write_text(
        "\\begin{document}\n"
        "we measured 43.21 ourselves\n"
        "an earlier trial reported 55.44 \\cite{smith2019}\n"
        "\\end{document}\n"
    )
    monkeypatch.chdir(root)
    monkeypatch.setattr(sys, "argv", ["results", "coverage", str(paper)])
    cli.main()

    out = capsys.readouterr().out
    counts = summary(out)
    assert counts["cited"] == 1, "the value beside the citation is attributed, not unbound"
    assert counts["unbound"] == 1
    assert "43.21" in out
    assert "55.44" not in out, "a cited number is not reported as your omission"


def test_coverage_strict_exits_nonzero_while_anything_is_unbound(tmp_path, monkeypatch, capsys):
    root = tracked_repo(tmp_path, ["accuracy reached 87.65"])
    paper = root / "paper.tex"
    paper.write_text(r"\begin{document}87.65 and 43.21\end{document}")
    monkeypatch.chdir(root)
    monkeypatch.setattr(sys, "argv", ["results", "coverage", str(paper), "--strict"])

    assert cli.main() == 1


def test_hook_names_a_number_no_claim_covers(tmp_path):
    root = tracked_repo(tmp_path, ["accuracy reached 87.65"])
    paper = root / "paper.tex"
    paper.write_text("")

    message = fire(
        {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": str(paper),
                "old_string": "",
                "new_string": "we also see 43.21",
            },
        }
    )

    assert message is not None
    assert "43.21" in message


def test_hook_is_silent_when_a_claim_already_names_the_number(tmp_path):
    root = tracked_repo(tmp_path, ["accuracy reached 87.65"])
    paper = root / "paper.tex"

    assert (
        fire(
            {
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": str(paper),
                    "old_string": "",
                    "new_string": "again, 87.65",
                },
            }
        )
        is None
    )


def test_hook_is_silent_on_a_file_that_is_not_a_manuscript(tmp_path):
    root = tracked_repo(tmp_path)

    assert (
        fire(
            {
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": str(root / "train.py"),
                    "old_string": "",
                    "new_string": "lr = 43.21",
                },
            }
        )
        is None
    )


def test_hook_is_silent_where_no_ledger_governs_the_file(tmp_path):
    paper = tmp_path / "elsewhere" / "paper.tex"
    paper.parent.mkdir()
    paper.write_text("")

    assert (
        fire(
            {
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": str(paper),
                    "old_string": "",
                    "new_string": "we see 43.21",
                },
            }
        )
        is None
    )


def test_hook_does_not_reach_the_working_directory_for_a_ledger(tmp_path, monkeypatch):
    """A ledger belongs to the file's own tree, never to wherever the session started."""
    tracked_repo(tmp_path, ["accuracy reached 87.65"])
    outside = tmp_path.parent / "unrelated"
    outside.mkdir(exist_ok=True)
    paper = outside / "paper.tex"
    paper.write_text("")
    monkeypatch.chdir(tmp_path)

    assert (
        fire(
            {
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": str(paper),
                    "old_string": "",
                    "new_string": "we see 43.21",
                },
            }
        )
        is None
    )


def test_hook_ignores_layout_constants_and_identifiers(tmp_path):
    root = tracked_repo(tmp_path)
    paper = root / "paper.tex"

    assert (
        fire(
            {
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": str(paper),
                    "old_string": "",
                    "new_string": r"\vspace{0.5em}\cite{a2019} at 1.96 with p < 0.05 on CIFAR-10",
                },
            }
        )
        is None
    )


def test_hook_reports_only_what_the_edit_added(tmp_path):
    root = tracked_repo(tmp_path)
    paper = root / "paper.tex"

    message = fire(
        {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": str(paper),
                "old_string": "the figure was 11.11",
                "new_string": "the figure was 11.11 and the other was 43.21",
            },
        }
    )

    assert message is not None and "43.21" in message and "11.11" not in message


def test_hook_survives_input_that_is_not_a_tool_call():
    done = subprocess.run(
        [sys.executable, str(HOOK)], input="not json", capture_output=True, text=True
    )

    assert done.returncode == 0
    assert done.stdout.strip() == ""


def coverage(root, paper, monkeypatch, capsys, *extra):
    monkeypatch.chdir(root)
    monkeypatch.setattr(sys, "argv", ["results", "coverage", str(paper), *extra])
    code = cli.main()
    return code, capsys.readouterr().out


def test_a_claim_that_lists_numbers_binds_none_of_them(tmp_path, monkeypatch, capsys):
    values = [f"{n}.{n + 11}" for n in range(11, 26)]
    root = tracked_repo(tmp_path, [", ".join(values)], wrote='{"other": 0.4213}')
    paper = root / "paper.tex"
    sentences = "\n".join(f"Model {chr(65 + i)} reached {v}." for i, v in enumerate(values))
    paper.write_text(f"\\begin{{document}}\n{sentences}\n\\end{{document}}\n")

    code, out = coverage(root, paper, monkeypatch, capsys, "--strict")

    assert summary(out)["bound"] == 0
    assert summary(out)["unbound"] == 15
    assert code == 1


def test_a_claim_printing_the_sentence_binds_its_number(tmp_path, monkeypatch, capsys):
    root = tracked_repo(tmp_path, ["The ICC was 0.4213 (Table 2)."])
    paper = root / "paper.tex"
    paper.write_text(
        "\\begin{document}\nThe ICC was 0.4213 (Table 2), and 43.21.\n\\end{document}\n"
    )

    _, out = coverage(root, paper, monkeypatch, capsys)

    assert summary(out)["bound"] == 1
    assert summary(out)["unbound"] == 1


def test_a_number_the_run_wrote_is_bound_whatever_the_wording(tmp_path, monkeypatch, capsys):
    root = tracked_repo(tmp_path, ["agreement 0.42"], wrote='{"icc": 0.4213}')
    paper = root / "paper.tex"
    paper.write_text("\\begin{document}\nWe found an ICC of 0.42 overall.\n\\end{document}\n")

    code, out = coverage(root, paper, monkeypatch, capsys, "--strict")

    assert summary(out)["bound"] == 1
    assert code == 0
