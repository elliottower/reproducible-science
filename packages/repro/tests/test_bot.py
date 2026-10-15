"""`repro bot`: the reply parser, the comment marker, posting without duplicates, the
`set_aside` edit, and the workflows. GitHub is an in-memory fake; nothing reaches a network."""

from __future__ import annotations

import datetime
import hashlib
import itertools
import json
import re
import subprocess
import urllib.request

import pytest
import repro
import yaml
from repro.bot import actions, comments, setaside, workflows
from repro.bot.comments import Answer, Decision, Marker
from repro.bot.findings import Finding, Findings, check
from repro.bot.github import BOT, Client, Comment, GitHubError, Pull
from repro.cli import main
from repro.manifest import load
from repro.models import Manifest, Review, SetAside

REPO = "someone/study"
HEAD = "a" * 40
OTHER = "b" * 40
KEY = "c" * 64
THEN = datetime.datetime(2026, 10, 14, 12, 0, tzinfo=datetime.UTC)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refused(*args, **kwargs):
        raise AssertionError("a test reached for the network")

    monkeypatch.setattr(urllib.request, "urlopen", refused)


# ----------------------------------------------------------------------------- the fake API


class FakeGitHub(Client):
    """The calls `repro bot` makes, against comments and a file held in memory."""

    def __init__(self, *, fork: bool = False, patches=None, manifest: bytes = b"", writers=()):
        super().__init__(REPO, "token")
        self.head = HEAD
        self.fork = fork
        self._patches = patches or {}
        self.manifest = manifest
        self.writers = set(writers)
        self.comments: list[Comment] = []
        self.commits: list[str] = []
        self.created: list[Comment] = []
        self._ids = itertools.count(100)
        self._clock = itertools.count(1)

    def request(self, method, path, body=None):
        raise AssertionError(f"unexpected request {method} {path}")

    def _add(self, kind, body, login=BOT, bot=True, in_reply_to=None) -> Comment:
        made = Comment(
            id=next(self._ids),
            kind=kind,
            body=body,
            login=login,
            bot=bot,
            created_at=THEN + datetime.timedelta(minutes=next(self._clock)),
            in_reply_to=in_reply_to,
        )
        self.comments.append(made)
        return made

    def human(self, kind, body, login, in_reply_to=None) -> Comment:
        return self._add(kind, body, login=login, bot=False, in_reply_to=in_reply_to)

    def pull(self, number):
        return Pull(
            number=number,
            head_sha=self.head,
            head_ref="topic",
            head_repository="fork/study" if self.fork else REPO,
        )

    def patches(self, number):
        return self._patches

    def review_comments(self, number):
        return [c for c in self.comments if c.kind == "review"]

    def review_comment(self, comment_id):
        return next(c for c in self.comments if c.id == comment_id)

    def issue_comments(self, number):
        return [c for c in self.comments if c.kind == "issue"]

    def comment_on_line(self, number, body, sha, path, line):
        made = self._add("review", body)
        self.created.append(made)
        self.placed = (sha, path, line)
        return made.id

    def reply_on_line(self, number, comment_id, body):
        return self._add("review", body, in_reply_to=comment_id).id

    def comment(self, number, body):
        made = self._add("issue", body)
        self.created.append(made)
        return made.id

    def edit(self, comment, body):
        at = next(i for i, c in enumerate(self.comments) if c.id == comment.id)
        self.comments[at] = comment.model_copy(update={"body": body})

    def permission(self, login):
        return "write" if login in self.writers else "read"

    def file(self, path, ref):
        assert (path, ref) == ("repro.yaml", "topic")
        return self.manifest, hashlib.sha1(self.manifest).hexdigest()

    def put_file(self, path, content, sha, branch, message):
        assert sha == hashlib.sha1(self.manifest).hexdigest() and branch == "topic"
        self.manifest = content
        self.commits.append(message)
        return f"{len(self.commits):040d}"

    def body(self, comment_id) -> str:
        return next(c for c in self.comments if c.id == comment_id).body


def finding(**changes) -> Finding:
    made = {
        "key": KEY,
        "digest": "d" * 16,
        "claim": "table2",
        "assertion": "metric accuracy",
        "label": "Table 2",
        "kind": "mismatch",
        "printed": "0.931",
        "stored": "0.928",
        "file": "results/metrics.json",
        "path": "paper.md",
        "line": 3,
        "artifact": "paper",
        "text": "an accuracy of 0.931",
    }
    return Finding(**(made | changes))


def findings(*found, checked=(KEY,), set_aside=(), head=HEAD) -> Findings:
    return Findings(
        pull_request=7,
        head_sha=head,
        findings=found,
        checked=checked,
        set_aside=set_aside,
    )


PATCH = "@@ -1,2 +1,4 @@\n # Results\n-old line\n+new line\n+an accuracy of 0.931\n context\n"


# ----------------------------------------------------------------------------- the replies


@pytest.mark.parametrize(
    ("body", "answer", "reason"),
    [
        ("1", Answer.YES, ""),
        ("2", Answer.NO, ""),
        (" 3\n", Answer.IGNORE, ""),
        ("4", Answer.NOT_A_CLAIM, ""),
        (
            "3 the table is from the appendix draft",
            Answer.IGNORE,
            "the table is from the appendix draft",
        ),
        ("2: the run used\nthe old seed", Answer.NO, "the run used the old seed"),
        ("1.", Answer.YES, ""),
        ("4) a section number", Answer.NOT_A_CLAIM, "a section number"),
        (
            "> **Table 2: 0.931 no longer matches**\n> 1. Yes\n\n4 not a claim",
            Answer.NOT_A_CLAIM,
            "not a claim",
        ),
        ("r-cccccccc 3 typo", Answer.IGNORE, "typo"),
    ],
)
def test_a_reply_starting_with_one_to_four_gives_that_answer_and_the_rest_is_the_reason(
    body, answer, reason
):
    assert comments.parse(body, "r-cccccccc") == comments.Reply(answer=answer, reason=reason)


@pytest.mark.parametrize(
    "body", ["", "5", "0", "12", "1.5", "yes", "three", "x 3", "3x", "> 3", "see 2"]
)
def test_anything_else_gives_no_answer(body):
    assert comments.parse(body, "r-cccccccc") is None


def test_a_reply_in_the_conversation_is_in_a_thread_only_by_quoting_it_or_naming_it():
    assert comments.refers_to("> repro bot · r-cccccccc · claim\n\n3", "r-cccccccc")
    assert comments.refers_to("r-cccccccc 3", "r-cccccccc")
    assert not comments.refers_to("3", "r-cccccccc")
    assert not comments.refers_to("> r-dddddddd\n3 r-cccccccc", "r-cccccccc")


# ----------------------------------------------------------------------------- the marker


def marker(**changes) -> Marker:
    made = {
        "claim": "table2",
        "key": KEY,
        "digest": "d" * 16,
        "headline": "Table 2: `0.931` no longer matches `results/metrics.json` (now `0.928`)",
        "option": "Yes, the paper should say `0.928`",
        "placed": "review",
        "artifact": "paper",
        "text": "an accuracy of 0.931",
    }
    return Marker(**(made | changes))


def test_a_comment_carries_its_marker_and_reads_back_as_it_was_written():
    made = marker(
        decision=Decision(answer=Answer.NO, reason="old seed", by="alice", at=THEN, reply=9)
    )
    body = comments.render(made)
    assert comments.decode(body) == made
    assert body.startswith(f"**{made.headline}**\n\nReply in this thread with a number:\n1. ")
    assert "2. No, the result file is wrong\n3. Ignore this one\n4. Not a claim" in body
    assert "@alice says the result file is wrong" in body


def test_a_body_with_two_markers_or_a_damaged_one_has_none():
    body = comments.render(marker())
    assert comments.decode(body + body) is None
    assert comments.decode(body.replace("repro-bot:v1 ", "repro-bot:v1 !!")) is None
    assert comments.decode("no marker") is None


def test_the_headline_reads_like_the_example_and_values_from_the_pull_request_mention_nobody():
    said = comments.headline("Table 2", "mismatch", "0.931", "0.928", "results/metrics.json", False)
    assert said == "Table 2: `0.931` no longer matches `results/metrics.json` (now `0.928`)"
    hostile = comments.headline("@everyone <b>", "mismatch", "`@x`", None, "f", False)
    assert "@everyone" not in hostile and "<b>" not in hostile
    assert "`` `@x` ``" in hostile


# --------------------------------------------------------------------------------- posting


def test_a_finding_on_a_line_in_the_diff_is_a_comment_on_that_line():
    github = FakeGitHub(patches={"paper.md": PATCH})
    done = actions.post(findings(finding()), github, HEAD)
    assert done.created == (KEY,)
    (made,) = github.created
    assert made.kind == "review" and github.placed == (HEAD, "paper.md", 3)
    assert comments.decode(made.body).key == KEY


def test_a_finding_whose_line_is_not_in_the_diff_is_a_comment_in_the_conversation():
    github = FakeGitHub(patches={"paper.md": PATCH})
    actions.post(findings(finding(line=40)), github, HEAD)
    (made,) = github.created
    assert made.kind == "issue"
    assert "quoting this comment or starting with `r-cccccccc`" in made.body


def test_lines_a_review_comment_can_take_are_the_added_and_unchanged_lines_of_each_hunk():
    assert actions.lines(PATCH) == {1, 2, 3, 4}
    assert actions.lines("@@ -10 +20,2 @@\n-a\n+b\n c\n\\ No newline at end of file\n") == {20, 21}


def test_posting_twice_never_duplicates_and_a_changed_finding_edits_the_comment():
    github = FakeGitHub(patches={"paper.md": PATCH})
    actions.post(findings(finding()), github, HEAD)
    again = actions.post(findings(finding()), github, HEAD)
    assert again.created == () and again.edited == () and again.unchanged == (KEY,)
    moved = actions.post(findings(finding(digest="e" * 16, stored="0.925")), github, HEAD)
    assert moved.edited == (KEY,) and len(github.comments) == 1
    assert "(now `0.925`)" in github.comments[0].body


def test_an_assertion_that_passes_again_is_marked_fixed_and_reopened_if_it_fails_again():
    github = FakeGitHub(patches={"paper.md": PATCH})
    actions.post(findings(finding()), github, HEAD)
    github.head = OTHER
    fixed = actions.post(findings(head=OTHER), github, OTHER)
    assert fixed.edited == (KEY,)
    body = github.comments[0].body
    assert body.startswith("~~Table 2") and f"Fixed: the claim passes at {OTHER[:7]}." in body
    assert comments.decode(body).state == "fixed"
    reopened = actions.post(findings(finding(), head=OTHER), github, OTHER)
    assert reopened.edited == (KEY,) and len(github.comments) == 1
    assert comments.decode(github.comments[0].body).state == "open"


def test_a_set_aside_or_removed_assertion_closes_its_comment_saying_which():
    github = FakeGitHub()
    actions.post(findings(finding()), github, HEAD)
    actions.post(findings(set_aside=(KEY,)), github, HEAD)
    assert "Set aside in `repro.yaml`." in github.comments[0].body
    actions.post(findings(checked=()), github, HEAD)
    assert "no longer in `repro.yaml`" in github.comments[0].body


def test_a_marker_in_a_comment_the_bot_did_not_write_is_not_believed():
    github = FakeGitHub()
    github.human("issue", comments.render(marker(placed="issue")), "mallory")
    actions.post(findings(finding()), github, HEAD)
    assert len(github.created) == 1


def test_findings_from_another_commit_are_refused_and_nothing_is_posted():
    github = FakeGitHub()
    with pytest.raises(actions.NotThisRunError):
        actions.post(findings(finding()), github, OTHER)
    github.head = OTHER
    with pytest.raises(actions.NotThisRunError):
        actions.post(findings(finding(), head=OTHER), FakeGitHub(), OTHER)
    assert github.comments == []


def test_on_a_fork_every_comment_is_in_the_conversation_and_says_nothing_is_committed():
    github = FakeGitHub(fork=True, patches={"paper.md": PATCH})
    done = actions.post(findings(finding()), github, HEAD)
    (made,) = github.created
    assert done.fork and made.kind == "issue"
    assert comments.FORK in made.body


def test_findings_that_name_a_path_outside_the_repository_do_not_read():
    for path in ("../repro.yaml", "/etc/repro.yaml", "a/../../repro.yaml", "repro.txt"):
        with pytest.raises(ValueError):
            Findings(pull_request=1, head_sha=HEAD, manifest=path)


# ---------------------------------------------------------------------------------- replying


MANIFEST = b"""\
# the study's manifest
project: study   # kept as written
artifacts:
- {id: paper, path: paper.md}
set_aside:
  - artifact: paper
    text: took 12 minutes
    reason: how long the form takes, not a result

claims: []
"""


def review_event(reply: Comment) -> dict:
    return {
        "comment": {
            "id": reply.id,
            "body": reply.body,
            "user": {"login": reply.login, "type": "User"},
            "created_at": reply.created_at.isoformat(),
            "in_reply_to_id": reply.in_reply_to,
        },
        "pull_request": {"number": 7},
    }


def issue_event(reply: Comment) -> dict:
    event = review_event(reply)
    del event["pull_request"]
    event["comment"].pop("in_reply_to_id")
    event["issue"] = {"number": 7, "pull_request": {"url": "x"}}
    return event


def posted(github: FakeGitHub, **changes) -> Comment:
    actions.post(findings(finding(**changes)), github, HEAD)
    return github.created[-1]


def test_ignore_commits_a_set_aside_entry_with_who_and_when_and_says_so_in_the_thread():
    github = FakeGitHub(patches={"paper.md": PATCH}, manifest=MANIFEST, writers={"alice"})
    root = posted(github)
    answer = github.human("review", "3 a figure from the pilot", "alice", in_reply_to=root.id)
    done = actions.reply("pull_request_review_comment", review_event(answer), github)
    assert done.done == "recorded"
    assert (
        done.said
        == f"recorded: ignored by @alice; set_aside entry committed in {done.committed[:7]}"
    )
    assert github.comments[-1].in_reply_to == root.id and github.comments[-1].body == done.said
    written = github.manifest.decode()
    assert written.startswith(MANIFEST.decode().split("\nclaims:")[0])
    entry = load_entries(written)[-1]
    assert entry == SetAside(
        artifact="paper",
        text="an accuracy of 0.931",
        reason="pull request #7, ignored: a figure from the pilot",
        reviewed=Review(who="alice", when=answer.created_at),
    )
    state = comments.decode(github.body(root.id))
    assert state.state == "set-aside" and state.decision.by == "alice"
    assert github.commits == ["repro.yaml: set aside claim table2 (ignored by @alice on #7)"]


def load_entries(text: str) -> list[SetAside]:
    return [SetAside.model_validate(item) for item in yaml.safe_load(text)["set_aside"]]


def test_yes_and_no_are_recorded_in_the_comment_and_change_no_file():
    for number, said in (("1", "accepts the file's value"), ("2", "says the result file is wrong")):
        github = FakeGitHub(patches={"paper.md": PATCH}, manifest=MANIFEST, writers={"alice"})
        root = posted(github)
        answer = github.human("review", number, "alice", in_reply_to=root.id)
        done = actions.reply("pull_request_review_comment", review_event(answer), github)
        assert done.done == "recorded" and github.commits == [] and github.manifest == MANIFEST
        assert said in github.body(root.id)
        assert comments.decode(github.body(root.id)).state == "open"


def test_a_reply_from_someone_without_write_access_is_answered_and_not_recorded():
    github = FakeGitHub(patches={"paper.md": PATCH}, manifest=MANIFEST)
    root = posted(github)
    answer = github.human("review", "3", "visitor", in_reply_to=root.id)
    done = actions.reply("pull_request_review_comment", review_event(answer), github)
    assert done.done == "not allowed" and github.commits == []
    assert github.comments[-1].body == comments.NOT_ALLOWED
    assert comments.decode(github.body(root.id)).decision is None


def test_a_reply_that_is_not_a_number_gets_a_one_line_answer():
    github = FakeGitHub(patches={"paper.md": PATCH}, writers={"alice"})
    root = posted(github)
    answer = github.human("review", "why is this failing?", "alice", in_reply_to=root.id)
    done = actions.reply("pull_request_review_comment", review_event(answer), github)
    assert done.done == "not an answer"
    assert github.comments[-1].body == comments.NOT_AN_ANSWER
    assert "\n" not in comments.NOT_AN_ANSWER


def test_a_reply_in_another_thread_is_ignored_and_nothing_is_said():
    github = FakeGitHub(patches={"paper.md": PATCH}, writers={"alice"})
    posted(github)
    theirs = github.human("review", "a review comment", "bob")
    forged = github.human("review", comments.render(marker()), "mallory")
    before = len(github.comments)
    for root in (theirs, forged):
        answer = github.human("review", "3", "alice", in_reply_to=root.id)
        done = actions.reply("pull_request_review_comment", review_event(answer), github)
        assert done.done == "not ours"
    top = github.human("issue", "3", "alice")
    assert actions.reply("issue_comment", issue_event(top), github).done == "not ours"
    assert len(github.comments) == before + 3


def test_a_reply_in_the_conversation_quoting_the_comment_is_recorded_there():
    github = FakeGitHub(manifest=MANIFEST, writers={"alice"})
    root = posted(github, line=None, path=None)
    quoted = "\n".join(f"> {line}" for line in root.body.splitlines()[:-1])
    answer = github.human("issue", f"{quoted}\n\n4 a section number", "alice")
    done = actions.reply("issue_comment", issue_event(answer), github)
    assert done.done == "recorded" and done.said.startswith("recorded: not a claim by @alice")
    assert github.comments[-1].body.startswith("`r-cccccccc` recorded: not a claim by @alice")


def test_the_latest_reply_wins_and_a_change_of_mind_removes_the_entry_the_bot_wrote():
    github = FakeGitHub(patches={"paper.md": PATCH}, manifest=MANIFEST, writers={"alice", "bob"})
    root = posted(github)
    first = github.human("review", "3", "alice", in_reply_to=root.id)
    actions.reply("pull_request_review_comment", review_event(first), github)
    assert len(load_entries(github.manifest.decode())) == 2
    second = github.human("review", "1 the paper is out of date", "bob", in_reply_to=root.id)
    done = actions.reply("pull_request_review_comment", review_event(second), github)
    assert done.said.startswith("recorded: accepted by @bob; the set_aside entry was removed")
    assert github.manifest == MANIFEST
    state = comments.decode(github.body(root.id))
    assert state.decision.answer is Answer.YES and state.state == "open"
    # An older reply arriving late changes nothing.
    assert actions.reply("pull_request_review_comment", review_event(first), github).done == (
        "skipped"
    )


def test_on_a_fork_an_answer_is_recorded_and_nothing_is_committed():
    github = FakeGitHub(fork=True, manifest=MANIFEST, writers={"alice"})
    root = posted(github)
    answer = github.human("issue", "r-cccccccc 3", "alice")
    done = actions.reply("issue_comment", issue_event(answer), github)
    assert done.said == (
        "recorded: ignored by @alice; this pull request comes from a fork, so nothing was committed"
    )
    assert github.commits == [] and github.manifest == MANIFEST
    assert "No `set_aside` entry was committed." in github.body(root.id)


def test_a_comment_by_a_bot_is_never_read_as_a_reply():
    github = FakeGitHub(writers={BOT})
    event = issue_event(github.human("issue", "3", BOT))
    event["comment"]["user"]["type"] = "Bot"
    assert actions.reply("issue_comment", event, github).done == "skipped"


def test_a_branch_that_moved_between_read_and_write_is_read_again():
    github = FakeGitHub(patches={"paper.md": PATCH}, manifest=MANIFEST, writers={"alice"})
    root = posted(github)
    write = github.put_file
    refusals = iter([GitHubError("PUT", "contents", 409, "sha does not match")])

    def moved(*args):
        for refused in refusals:
            raise refused
        return write(*args)

    github.put_file = moved
    answer = github.human("review", "3", "alice", in_reply_to=root.id)
    assert actions.reply("pull_request_review_comment", review_event(answer), github).committed


# ----------------------------------------------------------------------- the set_aside edit

ENTRY = setaside.entry("paper", "an accuracy of 0.931", 7, "ignored", "", "alice", THEN)


def test_an_entry_is_added_after_the_last_and_every_other_byte_is_kept():
    source = MANIFEST.decode()
    result = setaside.added(source, ENTRY)
    block = (
        "  - artifact: paper\n"
        "    text: an accuracy of 0.931\n"
        "    reason: 'pull request #7, ignored'\n"
        "    reviewed:\n"
        "      who: alice\n"
        "      when: '2026-10-14T12:00:00Z'\n"
    )
    assert block in result
    assert result.replace(block, "", 1) == source
    assert setaside.removed(result, "paper", "an accuracy of 0.931") == source


@pytest.mark.parametrize(
    "source",
    [
        "project: study\nclaims: []\n",
        "project: study\nclaims: []",
        "project: study\nset_aside: []\nclaims: []\n",
        "project: study\nset_aside:\n\nclaims: []\n",
        "project: study\r\nset_aside:\r\n- artifact: paper\r\n  text: x\r\n  reason: y\r\n",
    ],
)
def test_an_entry_can_be_added_to_a_manifest_of_any_shape_and_removed_again(source):
    result = setaside.added(source, ENTRY)
    assert load_entries(result)[-1] == ENTRY
    assert yaml.safe_load(result)["project"] == "study"
    removed = setaside.removed(result, "paper", "an accuracy of 0.931")
    assert yaml.safe_load(removed) == yaml.safe_load(source) or (
        yaml.safe_load(source).get("set_aside") in (None, []) and "set_aside" not in removed
    )
    if "\r\n" in source:
        assert "\n" not in result.replace("\r\n", "")


def test_an_entry_someone_wrote_by_hand_is_never_removed():
    assert setaside.removed(MANIFEST.decode(), "paper", "took 12 minutes") is None


def test_a_list_written_inline_is_refused_rather_than_rewritten():
    with pytest.raises(setaside.ManifestShapeError):
        setaside.added("set_aside: [{artifact: a, text: b, reason: c}]\n", ENTRY)


def test_an_entry_without_a_review_dumps_as_it_did_before_the_field_existed():
    plain = SetAside(artifact="paper", text="x", reason="y")
    assert plain.model_dump() == {"artifact": "paper", "text": "x", "reason": "y"}
    assert "reviewed" not in Manifest(set_aside=(plain,)).model_dump_json()


# ------------------------------------------------------------------------------ the check


def test_check_finds_a_mismatch_with_the_manuscript_line_and_the_passage_to_set_aside(
    tmp_path, monkeypatch
):
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "metrics.json").write_text(json.dumps({"accuracy": 0.928}))
    (tmp_path / "paper.md").write_text("# Results\n\nWe report\nan accuracy of 0.931 here.\n")
    (tmp_path / "repro.yaml").write_text(
        """\
project: study
artifacts:
- {id: paper, path: paper.md}
- {id: metrics, path: results/metrics.json}
claims:
- id: table2
  text: an accuracy of 0.931
  where: Table 2
  evidence:
  - {kind: quote, artifact: paper, text: an accuracy of 0.931}
  - {kind: metric, artifact: metrics, name: accuracy, reported: "0.931", pointer: /accuracy}
- id: other
  text: the same accuracy
  evidence:
  - {kind: metric, artifact: metrics, name: accuracy, reported: "0.928", pointer: /accuracy}
"""
    )
    monkeypatch.chdir(tmp_path)
    found = check(load(tmp_path / "repro.yaml"), tmp_path, 7, HEAD)
    (made,) = found.findings
    assert len(found.checked) == 3 and found.set_aside == ()
    assert (made.label, made.kind, made.printed, made.stored) == (
        "Table 2",
        "mismatch",
        "0.931",
        "0.928",
    )
    assert (made.file, made.path, made.line) == ("results/metrics.json", "paper.md", 4)
    assert (made.artifact, made.text, found.manifest) == (
        "paper",
        "an accuracy of 0.931",
        "repro.yaml",
    )

    with (tmp_path / "repro.yaml").open("a") as handle:
        handle.write("set_aside:\n- {artifact: paper, text: an accuracy of 0.931, reason: r}\n")
    again = check(load(tmp_path / "repro.yaml"), tmp_path, 7, HEAD)
    assert again.findings == () and len(again.set_aside) == 2


# ------------------------------------------------------------------------------ workflows


def git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def repository(tmp_path, monkeypatch):
    git(tmp_path, "init", "--quiet")
    (tmp_path / "repro.yaml").write_text("project: study\n")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def written(root) -> dict[str, tuple[str, dict]]:
    return {
        path.name: (path.read_text(), yaml.safe_load(path.read_text()))
        for path in sorted((root / ".github" / "workflows").iterdir())
    }


def test_init_writes_three_workflows_with_least_privilege_and_pinned_actions(repository):
    assert main(["bot", "init"]) == 0
    flows = written(repository)
    assert list(flows) == ["repro-bot-check.yml", "repro-bot-post.yml", "repro-bot-reply.yml"]
    for text, flow in flows.values():
        assert text.startswith(workflows.MARKER)
        assert "pull_request_target" not in text
        assert "github.event.comment.body" not in text
        uses = [
            step["uses"] for job in flow["jobs"].values() for step in job["steps"] if "uses" in step
        ]
        assert all(re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", used) for used in uses)
        assert f"reproducible-science=={repro.__version__} repro bot" in text

    _, check_flow = flows["repro-bot-check.yml"]
    # PyYAML reads the key `on` as a boolean.
    assert check_flow[True] == {"pull_request": None}
    assert check_flow["permissions"] == {"contents": "read"}
    (job,) = check_flow["jobs"].values()
    assert job["steps"][0]["with"] == {
        "ref": "${{ github.event.pull_request.head.sha }}",
        "persist-credentials": False,
    }

    _, post_flow = flows["repro-bot-post.yml"]
    assert post_flow[True] == {
        "workflow_run": {"workflows": [check_flow["name"]], "types": ["completed"]}
    }
    assert post_flow["permissions"] == {
        "actions": "read",
        "contents": "read",
        "issues": "write",
        "pull-requests": "write",
    }

    _, reply_flow = flows["repro-bot-reply.yml"]
    assert reply_flow[True] == {
        "issue_comment": {"types": ["created"]},
        "pull_request_review_comment": {"types": ["created"]},
    }
    assert reply_flow["permissions"] == {
        "contents": "write",
        "issues": "write",
        "pull-requests": "write",
    }
    for flow in (post_flow, reply_flow):
        steps = [step for job in flow["jobs"].values() for step in job["steps"]]
        assert not any("checkout" in step.get("uses", "") for step in steps)
        assert all(
            step.get("with", {}).get("enable-cache") is False
            for step in steps
            if "setup-uv" in step.get("uses", "")
        )


def test_init_never_replaces_a_workflow_it_did_not_write_even_when_forced(repository, capsys):
    theirs = repository / ".github" / "workflows" / "repro-bot-post.yml"
    theirs.parent.mkdir(parents=True)
    theirs.write_text("name: something else\n")
    for flags in ([], ["--force"]):
        assert main(["bot", "init", *flags]) == 2
        assert "did not write it, so it is never replaced" in capsys.readouterr().out
        assert theirs.read_text() == "name: something else\n"
    assert not (theirs.parent / "repro-bot-check.yml").exists()


def test_init_replaces_its_own_workflows_only_when_forced(repository, capsys):
    assert main(["bot", "init"]) == 0
    check_file = repository / ".github" / "workflows" / "repro-bot-check.yml"
    check_file.write_text(workflows.MARKER + "\nname: edited\n")
    assert main(["bot", "init"]) == 2
    assert "`--force` replaces" in capsys.readouterr().out
    assert main(["bot", "init", "--force"]) == 0
    assert yaml.safe_load(check_file.read_text())["name"] == workflows.CHECK_NAME


def test_init_with_no_manifest_writes_nothing(tmp_path, monkeypatch, capsys):
    git(tmp_path, "init", "--quiet")
    monkeypatch.chdir(tmp_path)
    assert main(["bot", "init"]) == 2
    assert "repro manifest init" in capsys.readouterr().out
    assert not (tmp_path / ".github").exists()
