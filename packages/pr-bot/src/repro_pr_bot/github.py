"""The GitHub REST calls the pull-request bot makes, and nothing else.

Each method is one documented endpoint, named in its docstring. `Client.request` is the one
place a request is sent, so a test replaces the client, never the network. Reads the token the
workflow gives it and sends it to the API's host only.
"""

from __future__ import annotations

import base64
import datetime
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from claims.exceptions import ReproError
from pydantic import BaseModel, ConfigDict

API = "https://api.github.com"
GRAPHQL = "https://api.github.com/graphql"
#: The login the workflow token acts as, and the only author whose markers are believed.
BOT = "github-actions[bot]"
#: The permissions `GET /repos/{owner}/{repo}/collaborators/{username}/permission` names that
#: allow a reply to be recorded. `maintain` is reported there as `write`.
WRITERS = ("admin", "maintain", "write")
TIMEOUT = 30
_NEXT = re.compile(r'<([^>]+)>;\s*rel="next"')


class GitHubError(ReproError):
    """GitHub refused a request, or answered it with something that does not read."""

    def __init__(self, method: str, path: str, status: int, said: str) -> None:
        self.status = status
        super().__init__(f"{method} {path}: GitHub answered {status}: {said[:300]}")


class Comment(BaseModel):
    """A comment on a pull request: on a line of its diff (`review`) or in its conversation
    (`issue`)."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    id: int
    kind: str
    body: str = ""
    login: str = ""
    bot: bool = False
    """Whether GitHub says the author is a bot account."""
    created_at: datetime.datetime
    in_reply_to: int | None = None

    @classmethod
    def read(cls, kind: str, data: dict[str, Any]) -> Comment:
        user = data.get("user") or {}
        return cls(
            id=data["id"],
            kind=kind,
            body=data.get("body") or "",
            login=user.get("login", ""),
            bot=user.get("type") == "Bot",
            created_at=data["created_at"],
            in_reply_to=data.get("in_reply_to_id"),
        )

    @property
    def by_bot(self) -> bool:
        """Whether the pull-request bot could have written it."""
        return self.bot and self.login == BOT


class Pull(BaseModel):
    """What the bot reads of a pull request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    number: int
    head_sha: str
    head_ref: str
    head_repository: str
    """`owner/repo` of the branch the pull request is from; empty where that repository was
    deleted."""


class Client:
    """The REST API of one repository, with the workflow's token."""

    def __init__(
        self, repository: str, token: str, api: str = API, graphql: str = GRAPHQL
    ) -> None:
        self.repository = repository
        self._token = token
        self._api = api.rstrip("/")
        self._graphql = graphql

    # -- transport --------------------------------------------------------------------------

    def request(
        self, method: str, path: str, body: dict | None = None
    ) -> tuple[Any, dict[str, str]]:
        """One request, as JSON, and the response's headers."""
        # A full address is the next page GitHub's `Link` header names, or the GraphQL endpoint.
        url = path if path.startswith("https://") else f"{self._api}{path}"
        sent = urllib.request.Request(
            url,
            method=method,
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(sent, timeout=TIMEOUT) as answered:
                text = answered.read().decode("utf-8")
                headers = dict(answered.headers.items())
        except urllib.error.HTTPError as refused:
            said = refused.read().decode("utf-8", "replace")
            raise GitHubError(method, path, refused.code, said) from None
        return (json.loads(text) if text else None), headers

    def _all(self, path: str) -> list[dict]:
        """Every page of a list."""
        found: list[dict] = []
        joiner = "&" if "?" in path else "?"
        url: str | None = f"{path}{joiner}per_page=100"
        while url:
            page, headers = self.request("GET", url)
            found += page
            following = _NEXT.search(headers.get("Link", headers.get("link", "")))
            url = following[1] if following else None
        return found

    def _repo(self, rest: str) -> str:
        return f"/repos/{self.repository}{rest}"

    # -- pull requests ----------------------------------------------------------------------

    def pull(self, number: int) -> Pull:
        """`GET /repos/{owner}/{repo}/pulls/{pull_number}`."""
        data, _ = self.request("GET", self._repo(f"/pulls/{number}"))
        head = data["head"]
        return Pull(
            number=data["number"],
            head_sha=head["sha"],
            head_ref=head["ref"],
            head_repository=(head.get("repo") or {}).get("full_name", ""),
        )

    def patches(self, number: int) -> dict[str, str]:
        """`GET /repos/{owner}/{repo}/pulls/{pull_number}/files`: each file's patch, by path.
        A file GitHub gives no patch for, a binary or a large one, is left out."""
        return {
            item["filename"]: item["patch"]
            for item in self._all(self._repo(f"/pulls/{number}/files"))
            if item.get("patch")
        }

    def review_comments(self, number: int) -> list[Comment]:
        """`GET /repos/{owner}/{repo}/pulls/{pull_number}/comments`."""
        return [
            Comment.read("review", item)
            for item in self._all(self._repo(f"/pulls/{number}/comments"))
        ]

    def review_comment(self, comment_id: int) -> Comment:
        """`GET /repos/{owner}/{repo}/pulls/comments/{comment_id}`."""
        data, _ = self.request("GET", self._repo(f"/pulls/comments/{comment_id}"))
        return Comment.read("review", data)

    def issue_comment(self, comment_id: int) -> Comment:
        """`GET /repos/{owner}/{repo}/issues/comments/{comment_id}`."""
        data, _ = self.request("GET", self._repo(f"/issues/comments/{comment_id}"))
        return Comment.read("issue", data)

    def fresh(self, comment: Comment) -> Comment | None:
        """The comment as it is now, or None where it was deleted."""
        try:
            if comment.kind == "review":
                return self.review_comment(comment.id)
            return self.issue_comment(comment.id)
        except GitHubError as refused:
            if refused.status == 404:
                return None
            raise

    def issue_comments(self, number: int) -> list[Comment]:
        """`GET /repos/{owner}/{repo}/issues/{issue_number}/comments`."""
        return [
            Comment.read("issue", item)
            for item in self._all(self._repo(f"/issues/{number}/comments"))
        ]

    def comment_on_line(
        self, number: int, body: str, sha: str, path: str, line: int
    ) -> int:
        """`POST /repos/{owner}/{repo}/pulls/{pull_number}/comments`, on the new side."""
        data, _ = self.request(
            "POST",
            self._repo(f"/pulls/{number}/comments"),
            {
                "body": body,
                "commit_id": sha,
                "path": path,
                "line": line,
                "side": "RIGHT",
            },
        )
        return data["id"]

    def reply_on_line(self, number: int, comment_id: int, body: str) -> int:
        """`POST /repos/{owner}/{repo}/pulls/{pull_number}/comments/{comment_id}/replies`."""
        data, _ = self.request(
            "POST",
            self._repo(f"/pulls/{number}/comments/{comment_id}/replies"),
            {"body": body},
        )
        return data["id"]

    def comment(self, number: int, body: str) -> int:
        """`POST /repos/{owner}/{repo}/issues/{issue_number}/comments`."""
        data, _ = self.request(
            "POST", self._repo(f"/issues/{number}/comments"), {"body": body}
        )
        return data["id"]

    def edit(self, comment: Comment, body: str) -> None:
        """`PATCH /repos/{owner}/{repo}/pulls/comments/{comment_id}`, or
        `PATCH /repos/{owner}/{repo}/issues/comments/{comment_id}`."""
        where = "pulls" if comment.kind == "review" else "issues"
        self.request(
            "PATCH", self._repo(f"/{where}/comments/{comment.id}"), {"body": body}
        )

    def resolve_thread(self, number: int, comment_id: int, resolved: bool) -> bool:
        """Resolve, or unresolve, the review thread a comment opens, through GraphQL's
        `resolveReviewThread` and `unresolveReviewThread`. False where no thread holds it."""
        owner, name = self.repository.split("/", 1)
        after = None
        while True:
            data = self._graph(
                "query($owner:String!,$name:String!,$number:Int!,$after:String){"
                "repository(owner:$owner,name:$name){pullRequest(number:$number){"
                "reviewThreads(first:100,after:$after){pageInfo{hasNextPage endCursor}"
                "nodes{id isResolved comments(first:1){nodes{databaseId}}}}}}}",
                {"owner": owner, "name": name, "number": number, "after": after},
            )
            threads = data["repository"]["pullRequest"]["reviewThreads"]
            for thread in threads["nodes"]:
                first = thread["comments"]["nodes"]
                if first and first[0]["databaseId"] == comment_id:
                    if thread["isResolved"] != resolved:
                        verb = (
                            "resolveReviewThread"
                            if resolved
                            else "unresolveReviewThread"
                        )
                        self._graph(
                            f"mutation($id:ID!){{{verb}(input:{{threadId:$id}}){{thread{{id}}}}}}",
                            {"id": thread["id"]},
                        )
                    return True
            if not threads["pageInfo"]["hasNextPage"]:
                return False
            after = threads["pageInfo"]["endCursor"]

    def _graph(self, query: str, variables: dict) -> dict:
        data, _ = self.request(
            "POST", self._graphql, {"query": query, "variables": variables}
        )
        if not isinstance(data, dict) or data.get("errors") or "data" not in data:
            said = json.dumps((data or {}).get("errors", data))[:300]
            raise GitHubError("POST", "graphql", 200, said)
        return data["data"]

    def dispatch(self, workflow: str, ref: str, inputs: dict[str, str]) -> None:
        """`POST /repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches`: run a
        workflow that has a `workflow_dispatch` trigger on the branch `ref`."""
        self.request(
            "POST",
            self._repo(f"/actions/workflows/{urllib.parse.quote(workflow)}/dispatches"),
            {"ref": ref, "inputs": inputs},
        )

    # -- access and contents ----------------------------------------------------------------

    def permission(self, login: str) -> str:
        """`GET /repos/{owner}/{repo}/collaborators/{username}/permission`: `admin`, `write`,
        `read` or `none`. A login GitHub does not know has none."""
        try:
            data, _ = self.request(
                "GET",
                self._repo(f"/collaborators/{urllib.parse.quote(login)}/permission"),
            )
        except GitHubError as refused:
            if refused.status == 404:
                return "none"
            raise
        return str(data.get("permission", "none"))

    def file(self, path: str, ref: str) -> tuple[bytes, str]:
        """`GET /repos/{owner}/{repo}/contents/{path}?ref=`: the bytes and the blob's sha."""
        quoted = urllib.parse.quote(path)
        data, _ = self.request(
            "GET",
            self._repo(f"/contents/{quoted}?ref={urllib.parse.quote(ref, safe='')}"),
        )
        return base64.b64decode(data["content"]), data["sha"]

    def put_file(
        self, path: str, content: bytes, sha: str, branch: str, message: str
    ) -> str:
        """`PUT /repos/{owner}/{repo}/contents/{path}`: one commit on `branch`, refused where
        the file is no longer the blob `sha`. Returns the commit's sha."""
        data, _ = self.request(
            "PUT",
            self._repo(f"/contents/{urllib.parse.quote(path)}"),
            {
                "message": message,
                "content": base64.b64encode(content).decode("ascii"),
                "sha": sha,
                "branch": branch,
            },
        )
        return data["commit"]["sha"]


__all__ = ["BOT", "WRITERS", "Client", "Comment", "GitHubError", "Pull"]
