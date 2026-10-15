"""`reproducible-science-pr-bot`: the reply parser, the comment marker, posting without
duplicates, the `set_aside` edit, and the command. GitHub is an in-memory fake; nothing reaches
a network."""

from __future__ import annotations

import datetime
import hashlib
import itertools
import json
import urllib.request

import pytest
import yaml
from claims.manifest import load
from claims.models import Manifest, Review, SetAside

from repro_pr_bot import actions, cli, comments, setaside
from repro_pr_bot.comments import Answer, Decision, Marker
from repro_pr_bot.findings import Finding, Findings, check
from repro_pr_bot.github import BOT, Client, Comment, GitHubError, Pull

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

    def __init__(
        self, *, fork: bool = False, patches=None, manifest: bytes = b"", writers=()
    ):
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
        self.resolved: list[tuple[int, bool]] = []
        self.dispatched: list[tuple[str, str, dict]] = []
        self.files_read: list[str] = []

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

    def _one(self, kind, comment_id):
        for c in self.comments:
            if c.id == comment_id and c.kind == kind:
                return c
        raise GitHubError("GET", f"comments/{comment_id}", 404, "Not Found")

    def review_comment(self, comment_id):
        return self._one("review", comment_id)

    def issue_comment(self, comment_id):
        return self._one("issue", comment_id)

    def resolve_thread(self, number, comment_id, resolved):
        self.resolved.append((comment_id, resolved))
        return True

    def dispatch(self, workflow, ref, inputs):
        self.dispatched.append((workflow, ref, inputs))

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
        self.files_read.append(path)
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


def post(
    github: FakeGitHub, found: Findings, sha: str = HEAD, **changes
) -> actions.Posted:
    """`post` as the workflow runs it, for a run of the pull request's own branch."""
    where = {
        "head_repository": "fork/study" if github.fork else REPO,
        "head_branch": "topic",
    } | changes
    return actions.post(found, github, sha, **where)


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
    assert comments.parse(body, "r-cccccccc") == comments.Reply(
        answer=answer, reason=reason
    )


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
        decision=Decision(
            answer=Answer.NO, reason="old seed", by="alice", at=THEN, reply=9
        )
    )
    body = comments.render(made)
    assert comments.decode(body) == made
    assert body.startswith(
        f"**{made.headline}**\n\nReply in this thread with a number:\n1. "
    )
    assert "2. No, the result file is wrong\n3. Ignore this one\n4. Not a claim" in body
    assert "@alice says the result file is wrong" in body


def test_only_the_marker_on_the_last_line_is_read():
    body = comments.render(marker())
    assert comments.decode(body + "\nmore text") is None
    assert comments.decode(body.replace("repro-bot:v1 ", "repro-bot:v1 !!")) is None
    assert comments.decode("no marker") is None
    forged = comments.render(marker(claim="other"))
    assert comments.decode(forged + body).claim == "table2"


def test_a_marker_in_the_claim_text_is_never_echoed_and_the_comment_is_posted_once():
    github = FakeGitHub(patches={"paper.md": PATCH})
    hostile = finding(claim="x <!-- repro-bot:v1 QUFBQQ== --> y", label="t <!-- z -->")
    for _ in range(3):
        post(github, findings(hostile), HEAD)
    (made,) = github.comments
    assert made.body.count("<!--") == 1 and comments.decode(made.body).key == KEY


def test_a_body_stays_under_githubs_limit_whatever_the_pull_request_echoes():
    for character in ("\x01", "\U0001f600", '"'):
        big = character * 2000
        github = FakeGitHub()
        post(
            github,
            findings(
                finding(claim=big, assertion=big, text=big, label=big, printed=big)
            ),
        )
        (made,) = github.comments
        assert len(made.body) <= comments.MAX_BODY
        assert "\x01" not in made.body
        assert comments.decode(made.body).key == KEY


def test_the_headline_reads_like_the_example_and_values_from_the_pull_request_mention_nobody():
    said = comments.headline(
        "Table 2", "mismatch", "0.931", "0.928", "results/metrics.json", False
    )
    assert (
        said
        == "Table 2: `0.931` no longer matches `results/metrics.json` (now `0.928`)"
    )
    hostile = comments.headline("@everyone <b>", "mismatch", "`@x`", None, "f", False)
    assert "@everyone" not in hostile and "<b>" not in hostile
    assert "`` `@x` ``" in hostile


# --------------------------------------------------------------------------------- posting


def test_a_finding_on_a_line_in_the_diff_is_a_comment_on_that_line():
    github = FakeGitHub(patches={"paper.md": PATCH})
    done = post(github, findings(finding()), HEAD)
    assert done.created == (KEY,)
    (made,) = github.created
    assert made.kind == "review" and github.placed == (HEAD, "paper.md", 3)
    assert comments.decode(made.body).key == KEY


def test_a_finding_whose_line_is_not_in_the_diff_is_a_comment_in_the_conversation():
    github = FakeGitHub(patches={"paper.md": PATCH})
    post(github, findings(finding(line=40)), HEAD)
    (made,) = github.created
    assert made.kind == "issue"
    assert "quoting this comment or starting with `r-cccccccc`" in made.body


def test_lines_a_review_comment_can_take_are_the_added_and_unchanged_lines_of_each_hunk():
    assert actions.lines(PATCH) == {1, 2, 3, 4}
    assert actions.lines(
        "@@ -10 +20,2 @@\n-a\n+b\n c\n\\ No newline at end of file\n"
    ) == {20, 21}


def test_posting_twice_never_duplicates_and_a_changed_finding_edits_the_comment():
    github = FakeGitHub(patches={"paper.md": PATCH})
    post(github, findings(finding()), HEAD)
    again = post(github, findings(finding()), HEAD)
    assert again.created == () and again.edited == () and again.unchanged == (KEY,)
    moved = post(github, findings(finding(digest="e" * 16, stored="0.925")), HEAD)
    assert moved.edited == (KEY,) and len(github.comments) == 1
    assert "(now `0.925`)" in github.comments[0].body


def test_an_assertion_that_passes_again_is_marked_fixed_and_reopened_if_it_fails_again():
    github = FakeGitHub(patches={"paper.md": PATCH})
    post(github, findings(finding()), HEAD)
    github.head = OTHER
    fixed = post(github, findings(head=OTHER), OTHER)
    assert fixed.edited == (KEY,)
    body = github.comments[0].body
    assert (
        body.startswith("~~Table 2")
        and f"Fixed: the claim passes at {OTHER[:7]}." in body
    )
    assert comments.decode(body).state == "fixed"
    reopened = post(github, findings(finding(), head=OTHER), OTHER)
    assert reopened.edited == (KEY,) and len(github.comments) == 1
    assert comments.decode(github.comments[0].body).state == "open"


def test_a_set_aside_or_removed_assertion_closes_its_comment_saying_which():
    github = FakeGitHub()
    post(github, findings(finding()), HEAD)
    post(github, findings(set_aside=(KEY,)), HEAD)
    assert comments.SET_ASIDE in github.comments[0].body
    assert "`repro verify` still reports this claim" in comments.SET_ASIDE
    post(github, findings(checked=()), HEAD)
    assert "no longer in `repro.yaml`" in github.comments[0].body


def test_a_marker_in_a_comment_the_bot_did_not_write_is_not_believed():
    github = FakeGitHub()
    github.human("issue", comments.render(marker(placed="issue")), "mallory")
    post(github, findings(finding()), HEAD)
    assert len(github.created) == 1


def test_findings_from_another_commit_are_refused_and_nothing_is_posted():
    github = FakeGitHub()
    with pytest.raises(actions.NotThisRunError):
        post(github, findings(finding()), OTHER)
    github.head = OTHER
    with pytest.raises(actions.NotThisRunError):
        post(FakeGitHub(), findings(finding(), head=OTHER), OTHER)
    assert github.comments == []


def test_on_a_fork_every_comment_is_in_the_conversation_and_says_nothing_is_committed():
    github = FakeGitHub(fork=True, patches={"paper.md": PATCH})
    done = post(github, findings(finding()), HEAD)
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
    post(github, findings(finding(**changes)), HEAD)
    return github.created[-1]


def test_ignore_commits_a_set_aside_entry_with_who_and_when_and_says_so_in_the_thread():
    github = FakeGitHub(
        patches={"paper.md": PATCH}, manifest=MANIFEST, writers={"alice"}
    )
    root = posted(github)
    answer = github.human(
        "review", "3 a figure from the pilot", "alice", in_reply_to=root.id
    )
    done = actions.reply(
        "pull_request_review_comment",
        review_event(answer),
        github,
        dispatch=("repro-pr-bot.yml", "claims.yml"),
    )
    assert done.done == "recorded"
    assert done.said == (
        f"recorded: ignored by @alice; set_aside entry committed in {done.committed[:7]}. "
        + comments.SET_ASIDE
    )
    assert github.dispatched == [
        ("repro-pr-bot.yml", "topic", {"pull_request": "7"}),
        ("claims.yml", "topic", {}),
    ]
    assert (
        github.comments[-1].in_reply_to == root.id
        and github.comments[-1].body == done.said
    )
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
    assert github.commits == [
        "repro.yaml: set aside claim table2 (ignored by @alice on #7)"
    ]


def load_entries(text: str) -> list[SetAside]:
    return [SetAside.model_validate(item) for item in yaml.safe_load(text)["set_aside"]]


def test_yes_and_no_are_recorded_in_the_comment_and_change_no_file():
    for number, said in (
        ("1", "accepts the file's value"),
        ("2", "says the result file is wrong"),
    ):
        github = FakeGitHub(
            patches={"paper.md": PATCH}, manifest=MANIFEST, writers={"alice"}
        )
        root = posted(github)
        answer = github.human("review", number, "alice", in_reply_to=root.id)
        done = actions.reply(
            "pull_request_review_comment", review_event(answer), github
        )
        assert (
            done.done == "recorded"
            and github.commits == []
            and github.manifest == MANIFEST
        )
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


@pytest.mark.parametrize("body", ["5", "#3", "12 please", "@repro which one?"])
def test_a_writer_reply_meant_as_an_answer_that_gives_none_gets_a_one_line_answer(body):
    github = FakeGitHub(patches={"paper.md": PATCH}, writers={"alice"})
    root = posted(github)
    answer = github.human("review", body, "alice", in_reply_to=root.id)
    done = actions.reply("pull_request_review_comment", review_event(answer), github)
    assert done.done == "not an answer"
    assert github.comments[-1].body == comments.NOT_AN_ANSWER
    assert "\n" not in comments.NOT_AN_ANSWER


@pytest.mark.parametrize(
    ("body", "login"),
    [
        ("why is this failing?", "alice"),
        ("lgtm", "alice"),
        ("5", "visitor"),
        ("", "alice"),
    ],
)
def test_discussion_in_a_thread_and_replies_from_others_are_left_alone(body, login):
    github = FakeGitHub(patches={"paper.md": PATCH}, writers={"alice"})
    root = posted(github)
    answer = github.human("review", body, login, in_reply_to=root.id)
    before = len(github.comments)
    assert actions.reply(
        "pull_request_review_comment", review_event(answer), github
    ).done == ("skipped")
    assert len(github.comments) == before


def test_a_reply_addressed_to_the_bot_gives_its_answer():
    assert comments.parse("@repro 3 a pilot value") == comments.Reply(
        answer=Answer.IGNORE, reason="a pilot value"
    )


def test_a_reply_in_another_thread_is_ignored_and_nothing_is_said():
    github = FakeGitHub(patches={"paper.md": PATCH}, writers={"alice"})
    posted(github)
    theirs = github.human("review", "a review comment", "bob")
    forged = github.human("review", comments.render(marker()), "mallory")
    before = len(github.comments)
    for root in (theirs, forged):
        answer = github.human("review", "3", "alice", in_reply_to=root.id)
        done = actions.reply(
            "pull_request_review_comment", review_event(answer), github
        )
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
    assert done.done == "recorded" and done.said.startswith(
        "recorded: not a claim by @alice"
    )
    assert github.comments[-1].body.startswith(
        "`r-cccccccc` recorded: not a claim by @alice"
    )


def test_the_latest_reply_wins_and_a_change_of_mind_removes_the_entry_the_bot_wrote():
    github = FakeGitHub(
        patches={"paper.md": PATCH}, manifest=MANIFEST, writers={"alice", "bob"}
    )
    root = posted(github)
    first = github.human("review", "3", "alice", in_reply_to=root.id)
    actions.reply("pull_request_review_comment", review_event(first), github)
    assert len(load_entries(github.manifest.decode())) == 2
    second = github.human(
        "review", "1 the paper is out of date", "bob", in_reply_to=root.id
    )
    done = actions.reply("pull_request_review_comment", review_event(second), github)
    assert done.said.startswith(
        "recorded: accepted by @bob; the set_aside entry was removed"
    )
    assert github.manifest == MANIFEST
    state = comments.decode(github.body(root.id))
    assert state.decision.answer is Answer.YES and state.state == "open"
    # An older reply arriving late changes nothing.
    assert actions.reply(
        "pull_request_review_comment", review_event(first), github
    ).done == ("skipped")


def test_on_a_fork_an_answer_is_recorded_and_nothing_is_committed():
    github = FakeGitHub(fork=True, manifest=MANIFEST, writers={"alice"})
    root = posted(github)
    answer = github.human("issue", "r-cccccccc 3", "alice")
    done = actions.reply("issue_comment", issue_event(answer), github)
    assert done.said == (
        "recorded: ignored by @alice; this pull request comes from a fork, so nothing was committed"
    )
    assert comments.SET_ASIDE not in github.body(root.id)
    assert github.commits == [] and github.manifest == MANIFEST
    assert "No `set_aside` entry was committed." in github.body(root.id)


def test_a_comment_by_a_bot_is_never_read_as_a_reply():
    github = FakeGitHub(writers={BOT})
    event = issue_event(github.human("issue", "3", BOT))
    event["comment"]["user"]["type"] = "Bot"
    assert actions.reply("issue_comment", event, github).done == "skipped"


def test_a_branch_that_moved_between_read_and_write_is_read_again():
    github = FakeGitHub(
        patches={"paper.md": PATCH}, manifest=MANIFEST, writers={"alice"}
    )
    root = posted(github)
    write = github.put_file
    refusals = iter([GitHubError("PUT", "contents", 409, "sha does not match")])

    def moved(*args):
        for refused in refusals:
            raise refused
        return write(*args)

    github.put_file = moved
    answer = github.human("review", "3", "alice", in_reply_to=root.id)
    assert actions.reply(
        "pull_request_review_comment", review_event(answer), github
    ).committed


def test_findings_naming_another_pull_request_or_another_file_are_refused():
    github = FakeGitHub(patches={"paper.md": PATCH})
    # A fork at the same commit, naming the repository's own pull request.
    with pytest.raises(actions.NotThisRunError, match="mallory/study:topic"):
        post(github, findings(finding()), head_repository="mallory/study")
    with pytest.raises(actions.NotThisRunError, match="other-branch"):
        post(github, findings(finding()), head_branch="other-branch")
    dependabot = Findings(
        pull_request=7,
        head_sha=HEAD,
        findings=(finding(),),
        manifest=".github/dependabot.yml",
    )
    with pytest.raises(actions.NotThisRunError, match="dependabot"):
        post(github, dependabot)
    assert github.comments == []


def test_a_comment_naming_another_file_is_not_answered_and_nothing_is_committed_there():
    github = FakeGitHub(
        patches={"paper.md": PATCH}, manifest=MANIFEST, writers={"alice"}
    )
    forged = github._add(
        "review", comments.render(marker(manifest=".github/dependabot.yml"))
    )
    answer = github.human("review", "3", "alice", in_reply_to=forged.id)
    assert actions.reply(
        "pull_request_review_comment", review_event(answer), github
    ).done == ("not ours")
    assert github.commits == [] and github.files_read == []
    with pytest.raises(ValueError):
        actions.reply(
            "pull_request_review_comment",
            review_event(answer),
            github,
            manifest="../x.yaml",
        )


def test_two_replies_racing_end_on_the_later_one_whichever_run_finishes_last():
    github = FakeGitHub(
        patches={"paper.md": PATCH}, manifest=MANIFEST, writers={"alice", "bob"}
    )
    root = posted(github)
    first = github.human("review", "3 seed", "alice", in_reply_to=root.id)
    stale = list(github.comments)
    second = github.human("review", "1", "bob", in_reply_to=root.id)
    assert actions.reply(
        "pull_request_review_comment", review_event(second), github
    ).done == ("recorded")
    # The first reply's run read the thread before the second landed.
    listed = github.review_comments
    github.review_comments = lambda number: [c for c in stale if c.kind == "review"]
    late = actions.reply("pull_request_review_comment", review_event(first), github)
    github.review_comments = listed
    assert (
        late.done == "skipped" and github.commits == [] and github.manifest == MANIFEST
    )
    assert comments.decode(github.body(root.id)).decision.answer is Answer.YES


def test_a_run_records_an_answer_whose_own_run_was_cancelled():
    github = FakeGitHub(
        patches={"paper.md": PATCH, "other.md": PATCH}, writers={"alice"}
    )
    one = posted(github)
    two = posted(github, key="e" * 64, digest="e" * 16)
    lost = github.human("review", "2 wrong file", "alice", in_reply_to=one.id)
    trigger = github.human("review", "1", "alice", in_reply_to=two.id)
    done = actions.reply("pull_request_review_comment", review_event(trigger), github)
    assert done.done == "recorded" and len(done.others) == 1
    assert comments.decode(github.body(one.id)).decision.reply == lost.id


def test_post_keeps_an_answer_recorded_after_it_listed_the_comments():
    github = FakeGitHub(patches={"paper.md": PATCH}, writers={"alice"})
    root = posted(github)
    stale = list(github.comments)
    answer = github.human("review", "2 wrong file", "alice", in_reply_to=root.id)
    listed = github.review_comments
    github.review_comments = lambda number: [c for c in stale if c.kind == "review"]
    actions.reply("pull_request_review_comment", review_event(answer), github)
    post(github, findings(finding(digest="1" * 16, stored="0.927")))
    github.review_comments = listed
    held = comments.decode(github.body(root.id))
    assert held.decision is not None and held.decision.answer is Answer.NO
    assert "(now `0.927`)" in github.body(root.id)


def test_a_reply_to_a_deleted_comment_is_not_ours_and_does_not_fail():
    github = FakeGitHub(patches={"paper.md": PATCH}, writers={"alice"})
    root = posted(github)
    github.comments.remove(root)
    answer = github.human("review", "2", "alice", in_reply_to=root.id)
    assert actions.reply(
        "pull_request_review_comment", review_event(answer), github
    ).done == ("not ours")
    assert post(github, findings(finding())).created == (KEY,)


def test_a_passage_already_set_aside_by_hand_is_said_and_the_comment_closed():
    github = FakeGitHub(
        patches={"paper.md": PATCH}, manifest=MANIFEST, writers={"alice"}
    )
    root = posted(github, text="took 12 minutes")
    answer = github.human("review", "3", "alice", in_reply_to=root.id)
    done = actions.reply("pull_request_review_comment", review_event(answer), github)
    assert "the passage is already set aside in repro.yaml" in done.said
    assert (
        github.commits == []
        and comments.decode(github.body(root.id)).state == "set-aside"
    )


def test_a_comment_on_the_diff_has_its_thread_resolved_when_fixed_and_reopened_on_failure():
    github = FakeGitHub(patches={"paper.md": PATCH})
    root = posted(github)
    post(github, findings())
    post(github, findings(finding()))
    assert github.resolved == [(root.id, True), (root.id, False)]


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
        yaml.safe_load(source).get("set_aside") in (None, [])
        and "set_aside" not in removed
    )
    if "\r\n" in source:
        assert "\n" not in result.replace("\r\n", "")


@pytest.mark.parametrize(
    "source",
    [
        "project: s\nset_aside:\n- artifact: p\n  text: t\n  reason: |\n    long\n    reason\nclaims: []\n",
        "set_aside:\n- artifact: p\n  text: t\n  reason: >\n    r\n# keep me\nclaims: []\n",
        "claims: []\nset_aside:\n- artifact: p\n  text: t\n  reason: r",
        "\ufeffproject: s\nclaims: []\n",
        "---\nproject: s\n",
    ],
)
def test_an_entry_is_added_and_removed_again_to_the_same_bytes(source):
    result = setaside.added(source, ENTRY)
    assert load_entries(result.removeprefix("\ufeff"))[-1] == ENTRY
    assert result.endswith("\n") == source.endswith("\n")
    assert setaside.removed(result, "paper", "an accuracy of 0.931") == source


def test_the_comment_after_an_empty_list_and_a_missing_final_line_break_are_kept():
    result = setaside.added("set_aside: []  # none yet\nclaims: []", ENTRY)
    assert result.startswith("set_aside:  # none yet\n- artifact: paper\n")
    assert result.endswith("\nclaims: []")


@pytest.mark.parametrize(
    "source",
    [
        "project: s\nclaims: []\n...\n",
        "a: 1\n---\nb: 2\n",
        "a: [\n",
        "set_aside: |\n  x\n",
    ],
)
def test_a_manifest_the_entry_cannot_be_put_in_cleanly_is_refused_with_a_reason(source):
    with pytest.raises(setaside.ManifestShapeError, match="nothing was changed"):
        setaside.added(source, ENTRY)


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
    (tmp_path / "paper.md").write_text(
        "# Results\n\nWe report\nan accuracy of 0.931 here.\n"
    )
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
        handle.write(
            "set_aside:\n- {artifact: paper, text: an accuracy of 0.931, reason: r}\n"
        )
    again = check(load(tmp_path / "repro.yaml"), tmp_path, 7, HEAD)
    assert again.findings == () and len(again.set_aside) == 2


def test_resolving_a_thread_finds_it_by_its_first_comment_and_sends_one_mutation():
    sent = []

    class Recorded(Client):
        def request(self, method, path, body=None):
            sent.append((method, path, body))
            if "mutation" in body["query"]:
                return {"data": {}}, {}
            thread = {
                "id": "T1",
                "isResolved": False,
                "comments": {"nodes": [{"databaseId": 5}]},
            }
            page = {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "nodes": [thread],
            }
            return {
                "data": {"repository": {"pullRequest": {"reviewThreads": page}}}
            }, {}

    assert Recorded(REPO, "token").resolve_thread(7, 5, True)
    assert [path for _, path, _ in sent] == ["https://api.github.com/graphql"] * 2
    assert "resolveReviewThread" in sent[1][2]["query"] and sent[1][2]["variables"] == {
        "id": "T1"
    }
    assert not Recorded(REPO, "token").resolve_thread(7, 6, True)


# ------------------------------------------------------------------------------ the command


def test_check_reads_the_pull_request_and_commit_from_the_event(tmp_path, monkeypatch):
    (tmp_path / "repro.yaml").write_text("project: study\n")
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"number": 7, "head": {"sha": HEAD}}}))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path / "temp"))
    monkeypatch.chdir(tmp_path)
    assert cli.main(["check"]) == 0
    found = Findings.model_validate_json((tmp_path / "temp" / cli.FINDINGS).read_text())
    assert (found.pull_request, found.head_sha, found.problem) == (7, HEAD, "")


def test_check_after_a_dispatch_reads_the_number_it_was_given(tmp_path, monkeypatch):
    (tmp_path / "repro.yaml").write_text("project: study\n")
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"inputs": {"pull_request": "9"}}))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("GITHUB_SHA", OTHER)
    monkeypatch.chdir(tmp_path)
    assert cli.main(["check", "--out", str(tmp_path / "f.json")]) == 0
    found = Findings.model_validate_json((tmp_path / "f.json").read_text())
    assert (found.pull_request, found.head_sha) == (9, OTHER)


def test_post_without_the_run_it_belongs_to_refuses_and_posts_nothing(
    tmp_path, monkeypatch, capsys
):
    findings_file = tmp_path / "f.json"
    findings_file.write_text(findings(finding()).model_dump_json())
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"workflow_run": {"head_sha": HEAD}}))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    assert cli.main(["post", str(findings_file)]) == 2
    assert "--head-repository" in capsys.readouterr().out


def test_workflows_to_start_again_are_read_from_spaces_and_commas_once_each():
    assert cli._workflows(
        ["repro-pr-bot.yml claims.yml", "claims.yml,results.yml"]
    ) == (
        "repro-pr-bot.yml",
        "claims.yml",
        "results.yml",
    )
