"""OSF API v2 integration — push a frozen plan as a draft registration."""

from __future__ import annotations

import datetime
import json
import os
import re
import stat
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from provenance_core import atomic_write, exclusive_lock

from prereg import template

API = "https://api.osf.io/v2"
SCHEMA_ID = "697b72f611a8e98484c6139b"

HEADING_TO_QUESTION = {
    "Research questions or hypotheses": "Research questions or hypotheses",
    "Foreknowledge of data or evidence": "Foreknowledge of data or evidence",
    "Explanation of foreknowledge and managing unintended influences": "Explanation of foreknowledge and managing unintended influences",
    "Study type": "Study type",
    "Intention for causal interpretation": "Intention for causal interpretation",
    "Blinding of experimental treatments": "Blinding of experimental treatments",
    "Additional blinding during research or analysis": "Additional blinding during research or analysis",
    "Study design": "Study design",
    "Randomization": "Randomization",
    "Data collection procedures": "Data collection procedures",
    "Data collection procedures - File upload": None,
    "Sample size": "Sample size",
    "Sample size rationale": "Sample size rationale",
    "Starting and stopping rules": "Starting and stopping rules",
    "Manipulated variables": "Manipulated variables",
    "Measured variables - File upload": None,
    "Measured variables": "Measured variables",
    "Indices": "Indices",
    "Indices - File upload": None,
    "Statistical models": "Statistical models",
    "Statistical models - File upload": None,
    "Transformations": "Transformations",
    "Inference criteria": "Inference criteria",
    "Data inclusion and exclusion": "Data inclusion and exclusion",
    "Missing data": "Missing data",
    "Other planned analysis": "Other planned analysis",
    "Context and additional information": "Context and additional information",
}


_BY_CASEFOLD = {k.casefold(): v for k, v in HEADING_TO_QUESTION.items()}


# How long to wait for a `.env` that is a named pipe. A secret manager that exposes one (a
# 1Password-managed environment does) writes to it only after the person approves the read, so
# the wait is for a human; the bound is what stops a dismissed prompt from hanging forever.
FIFO_TIMEOUT = 60.0


def _read_env(env: Path) -> str:
    """The text of a `.env`, which may be a regular file or a named pipe.

    A pipe blocks on open until its writer attaches, and a non-blocking open returns nothing
    because nothing has been written yet. So the read runs in a daemon thread and is abandoned
    after `FIFO_TIMEOUT`: the thread may stay blocked, but the command does not.
    """
    if not stat.S_ISFIFO(env.stat().st_mode):
        return env.read_text()
    box: dict[str, object] = {}

    def read() -> None:
        try:
            box["text"] = env.read_text()
        except OSError as e:
            box["error"] = e

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    reader.join(FIFO_TIMEOUT)
    if "text" in box:
        return str(box["text"])
    if "error" in box:
        raise RuntimeError(f"could not read {env}: {box['error']}")
    raise RuntimeError(
        f"{env} is a named pipe and nothing was written to it in {FIFO_TIMEOUT:.0f}s. The secret "
        "manager behind it did not deliver; its approval prompt was probably dismissed."
    )


#: The names a token is read under, in order. `OSF_PAT` is what a secret manager's environment
#: is likely to call a personal access token; asking the person to rename it in their vault to
#: suit one tool was the whole obstacle.
TOKEN_NAMES = ("OSF_TOKEN", "OSF_PAT")


def _token() -> str | None:
    """OSF_TOKEN (or OSF_PAT) from the environment, or from the nearest `.env` here or above
    that sets it.

    Called only when a request is about to be made: reading a pipe-backed `.env` asks the
    person to approve, and a command that makes no request should not ask.
    """
    for name in TOKEN_NAMES:
        token = os.environ.get(name)
        if token:
            return token
    for p in [Path.cwd(), *Path.cwd().parents]:
        env = p / ".env"
        # `is_file()` is False for a named pipe, so a secret manager's pipe was passed over as
        # if there were no `.env` at all.
        if not (env.is_file() or env.is_fifo()):
            continue
        found: dict[str, str] = {}
        for line in _read_env(env).splitlines():
            line = line.strip().removeprefix("export ").strip()
            name, sep, value = line.partition("=")
            if sep and name in TOKEN_NAMES and not line.startswith("#"):
                found.setdefault(name, value.strip().strip("'\""))
        for name in TOKEN_NAMES:
            if found.get(name):
                return found[name]
    return None


class OSFError(RuntimeError):
    """An OSF request failed. The message carries the status and OSF's own error body."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status  # None when OSF could not be reached at all


def _request(
    method: str,
    path: str,
    token: str | None,
    body: dict | None = None,
    *,
    version: str | None = None,
) -> dict:
    url = path if path.startswith("https://") else f"{API}{path}"
    if version:
        # OSF reads the version from a query parameter as well as the Accept header
        # (api/base/versioning.py, `get_query_param_version`). Without one it serves 2.0.
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode({"version": version})
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/vnd.api+json")
    req.add_header("Accept", "application/vnd.api+json")
    return _send(req)


def _send(req: urllib.request.Request) -> dict:
    # Only the POST was wrapped, so a failed schema fetch escaped as a bare HTTPError and
    # `freeze --osf` ended in a traceback. OSF explains a 400 in the body, and a caller that
    # prints the status alone has thrown away the one line that says what to fix.
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace") if e.fp else str(e)
        raise OSFError(
            f"OSF API error ({e.code}) on {req.get_method()} {req.full_url}: {detail}", e.code
        ) from e
    except urllib.error.URLError as e:
        raise OSFError(f"could not reach OSF ({req.full_url}): {e.reason}") from e


@dataclass(frozen=True)
class Question:
    key: str
    kind: str
    options: tuple[str, ...]


def _fetch_schema(token: str | None = None) -> dict[str, Question]:
    """Fetch the OSF Preregistration schema and return {question_title: Question}.

    The response keys live on the schema's `schema_blocks`, not on `attributes.schema.blocks`,
    which carries the text and no keys. Reading the latter returned an empty map, so every
    section with content was refused as unmapped. A question's label, its input and the input's
    options share a `schema_block_group_key`; OSF's own validator joins them the same way
    (osf/models/validators.py, `_build_question_schema`).

    The schema is public, so this needs no token: a plan can be checked against it before
    anyone is asked to release one.
    """
    blocks: list[dict] = []
    page: str | None = f"/schemas/registrations/{SCHEMA_ID}/schema_blocks/"
    while page:
        resp = _request("GET", page, token)
        blocks += [b["attributes"] for b in resp["data"]]
        page = (resp.get("links") or {}).get("next")

    labels: dict[str, str] = {}
    options: dict[str, list[str]] = {}
    inputs: dict[str, dict] = {}
    for b in blocks:
        group = b.get("schema_block_group_key") or ""
        text = re.sub(r"<[^>]+>", "", b.get("display_text") or "").strip()
        if b["block_type"] == "question-label" and text:
            labels[group] = text
        elif b["block_type"] == "select-input-option":
            options.setdefault(group, []).append(b.get("display_text") or "")
        elif b.get("registration_response_key"):
            inputs[group] = b
    return {
        labels[g]: Question(
            b["registration_response_key"], b["block_type"], tuple(options.get(g, []))
        )
        for g, b in inputs.items()
        if g in labels
    }


def _parse_plan(text: str) -> tuple[str, dict[str, str]]:
    """Parse PREREG.md into title and {heading: content} pairs."""
    title = ""
    sections: dict[str, str] = {}
    current_heading = ""
    current_lines: list[str] = []
    log_mark = "\n---\n\n## Log\n"
    plan = text.split(log_mark)[0] if log_mark in text else text

    for line in plan.splitlines():
        if line.startswith("# ") and not title:
            title = line[2:].strip()
        elif line.startswith("## "):
            if current_heading:
                sections[current_heading] = "\n".join(current_lines).strip()
            current_heading = line[3:].strip()
            current_lines = []
        elif current_heading:
            if not line.startswith(("**Status:**", "**Plan sha256:**", "**Frozen:**")):
                current_lines.append(line)

    if current_heading:
        sections[current_heading] = "\n".join(current_lines).strip()

    return title, sections


_HINTS = {f"_{hint}_" for _, hint in template.QUESTIONS if hint}


def _answer(content: str) -> str | None:
    """The section's answer, or None where the section gives none.

    A section still holding the template's italic prompt is unanswered: sending the prompt
    would register the question as its own answer.
    """
    text = content.strip()
    if not text or text in _HINTS or text.rstrip() == "N/A —":
        return None
    return text.lstrip("_").rstrip("_").strip() or None


def _choose(heading: str, answer: str, q: Question) -> str | list[str]:
    """Map a select question's answer onto OSF's options, or refuse.

    A select question accepts only its listed options, so prose under one is rejected by OSF
    after the plan is already frozen locally. Each line has to name one option, by its full
    text or by a prefix no other option shares. A select question answered `N/A` is left
    unanswered, which OSF permits: it does not apply.
    """
    if answer.startswith("N/A"):
        return [] if q.kind == "multi-select-input" else ""
    lines = [ln.strip().lstrip("-*").strip() for ln in answer.splitlines() if ln.strip()]
    chosen = []
    for line in lines:
        hits = [o for o in q.options if o.startswith(line)]
        if len(hits) != 1:
            raise RuntimeError(
                f"{heading!r} is a multiple-choice question on OSF, and {line!r} "
                f"{'matches more than one' if hits else 'is not one'} of its options. "
                "Write one option per line, as its full text or a prefix only it has:\n  - "
                + "\n  - ".join(o for o in q.options if o)
            )
        chosen.append(hits[0])
    if q.kind == "single-select-input":
        if len(chosen) != 1:
            raise RuntimeError(f"{heading!r} takes exactly one option on OSF; found {len(chosen)}.")
        return chosen[0]
    return chosen


def build_draft(plan_text: str, token: str | None = None) -> dict:
    """The draft-registration request body for a plan, or RuntimeError naming what cannot map.

    Separate from sending it so `freeze --osf` can refuse before it writes anything.
    """
    title, sections = _parse_plan(plan_text)
    schema = _fetch_schema(token)

    responses: dict[str, str | list[str]] = {}
    dropped: list[str] = []
    for heading, content in sections.items():
        question = HEADING_TO_QUESTION.get(heading) or _BY_CASEFOLD.get(heading.casefold())
        if not question:
            # The four "- File upload" headings map to None on purpose: OSF answers them with
            # files, not text, so their `N/A` has nowhere to go. Treating them as unmapped
            # rejected every plan the template produces. Only a heading the table does not
            # know at all is one that would silently vanish from the registration.
            if heading.casefold() not in _BY_CASEFOLD:
                dropped.append(heading)
            continue
        answer = _answer(content)
        q = schema.get(question)
        if answer is None:
            continue
        if q is None:
            dropped.append(heading)
        elif q.kind in ("single-select-input", "multi-select-input"):
            choice = _choose(heading, answer, q)
            if choice:
                responses[q.key] = choice
        else:
            responses[q.key] = answer

    if dropped:
        # A heading that maps to nothing was skipped without a word, so a section could be
        # absent from the external registration while the local file looked complete. The
        # decision rule is one of the sections most likely to be titled differently.
        raise RuntimeError(
            "these sections do not map onto the OSF schema and would be missing from the "
            "registration: " + ", ".join(repr(h) for h in dropped) + ". Rename them to the "
            "template's headings, or push without --osf."
        )

    return {
        "data": {
            "type": "draft_registrations",
            "attributes": {
                "title": title or "Untitled preregistration",
                "registration_responses": responses,
            },
            "relationships": {
                "registration_schema": {
                    "data": {
                        "id": SCHEMA_ID,
                        "type": "registration_schemas",
                    }
                }
            },
        }
    }


def require_token() -> str:
    token = _token()
    if not token:
        raise RuntimeError(
            "no OSF token found. Set OSF_TOKEN (or OSF_PAT) in .env or as an environment "
            "variable.\n"
            "Create one at https://osf.io/settings/tokens (scope: osf.full_write)."
        )
    return token


@dataclass(frozen=True)
class Draft:
    id: str
    url: str
    node_id: str | None  # the hidden node holding the draft's files


def create_draft(body: dict, token: str) -> Draft:
    """POST the draft.

    A draft created without `branched_from` gets a DraftNode of its own as a holding tank for
    files, converted into the registration's node when it is registered
    (osf/models/registrations.py, `DraftRegistration.create_from_node`; osf/models/draft_node.py).
    The response names it under `relationships.branched_from.data`.
    """
    resp = _request("POST", "/draft_registrations/", token, body)
    data = resp["data"]
    branched = ((data.get("relationships") or {}).get("branched_from") or {}).get("data") or {}
    return Draft(data["id"], f"https://osf.io/{data['id']}", branched.get("id"))


#: OSF's project categories, which a draft registration takes as well
#: (osf/models/node.py, `CATEGORY_MAP`). The empty string is "uncategorized".
CATEGORIES = (
    "analysis",
    "communication",
    "data",
    "hypothesis",
    "instrumentation",
    "methods and measures",
    "procedure",
    "project",
    "software",
    "other",
)

DEFAULT_LICENSE = "CC-By Attribution 4.0 International"


@dataclass(frozen=True)
class Metadata:
    """What OSF's draft Metadata page asks for, besides the plan itself.

    `subject_ids` and `license_id` are resolved against OSF before anything is written, so a
    subject that does not exist refuses the push instead of leaving a draft half-described.
    """

    title: str | None = None
    description: str = ""
    tags: tuple[str, ...] = ()
    category: str = ""
    license_id: str | None = None
    license_name: str | None = None
    year: str = ""
    copyright_holders: tuple[str, ...] = ()
    subject_ids: tuple[str, ...] = ()
    subject_names: tuple[str, ...] = ()


def find_subjects(names: list[str], token: str | None = None) -> list[str]:
    """The ids of OSF's registration subjects named exactly `names`, or RuntimeError.

    Subjects are OSF's taxonomy (bepress), looked up by their text. A name matching nothing, or
    matching only by prefix, is refused rather than guessed.
    """
    ids = []
    for name in names:
        q = urllib.parse.urlencode({"filter[text]": name, "page[size]": 100})
        data = _request("GET", f"/providers/registrations/osf/subjects/?{q}", token)["data"]
        exact = [s["id"] for s in data if s["attributes"]["text"].casefold() == name.casefold()]
        if len(exact) != 1:
            near = sorted({s["attributes"]["text"] for s in data})[:8]
            raise RuntimeError(
                f"{name!r} is not one of OSF's subjects"
                + (f"; close: {', '.join(near)}" if near else "")
                + ". Subjects are OSF's taxonomy, matched by their full text."
            )
        ids.append(exact[0])
    return ids


def find_license(name: str, token: str | None = None) -> str:
    """The id of the OSF license named `name`, or RuntimeError."""
    q = urllib.parse.urlencode({"filter[name]": name})
    data = _request("GET", f"/licenses/?{q}", token)["data"]
    exact = [x["id"] for x in data if x["attributes"]["name"].casefold() == name.casefold()]
    if len(exact) != 1:
        raise RuntimeError(f"{name!r} is not one of OSF's licenses.")
    return exact[0]


def set_metadata(draft_id: str, meta: Metadata, token: str) -> None:
    """Fill the draft's Metadata page: title, description, tags, category, license, subjects.

    Two requests, because subjects are a relationship with its own endpoint
    (api/draft_registrations/views.py, `DraftRegistrationSubjectsRelationship`). OSF adds each
    subject's parents itself, so the leaves are enough.
    """
    attributes: dict[str, object] = {}
    if meta.title:
        attributes["title"] = meta.title
    if meta.description:
        attributes["description"] = meta.description
    if meta.tags:
        attributes["tags"] = list(meta.tags)
    if meta.category:
        attributes["category"] = meta.category
    body: dict = {"data": {"type": "draft_registrations", "id": draft_id}}
    if meta.license_id:
        attributes["node_license"] = {
            "year": meta.year,
            "copyright_holders": list(meta.copyright_holders),
        }
        body["data"]["relationships"] = {
            "license": {"data": {"type": "licenses", "id": meta.license_id}}
        }
    body["data"]["attributes"] = attributes
    if attributes:
        _request("PATCH", f"/draft_registrations/{draft_id}/", token, body)
    if meta.subject_ids:
        _request(
            "PATCH",
            f"/draft_registrations/{draft_id}/relationships/subjects/",
            token,
            {"data": [{"type": "subjects", "id": s} for s in meta.subject_ids]},
        )


def push_draft(plan_text: str) -> tuple[str, str]:
    """Create a draft registration on OSF from a PREREG.md.

    Returns (draft_id, url). Raises if token missing or API fails.
    """
    token = require_token()
    draft = create_draft(build_draft(plan_text, token), token)
    return draft.id, draft.url


def upload(node_id: str, name: str, content: bytes, token: str) -> str:
    """Put a file in the draft's node, and return the sha256 OSF computed for what it received.

    Files in the draft's node are archived into the registration when it is registered
    (website/archiver/listeners.py, `after_register`). The upload link comes from the storage
    provider rather than being built here, because it names the node's storage region
    (api/nodes/serializers.py, `NodeStorageProviderSerializer.links.upload`). The upload itself
    is WaterButler's: PUT the raw bytes with `kind=file&name=...`, answered with a file entity
    whose `extra.hashes.sha256` is the digest of what arrived (developer.osf.io, "Upload New
    File"; waterbutler/providers/osfstorage/metadata.py).
    """
    provider = _request("GET", f"/draft_nodes/{node_id}/files/providers/osfstorage/", token)
    link = provider["data"]["links"]["upload"]
    url = (
        link
        + ("&" if "?" in link else "?")
        + urllib.parse.urlencode({"kind": "file", "name": name})
    )
    req = urllib.request.Request(url, data=content, method="PUT")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/octet-stream")
    resp = _send(req)
    return resp["data"]["attributes"]["extra"]["hashes"]["sha256"]


# Registration and view-only links are pinned to the current API version. At 2.0 OSF reads
# `draft_registration` / `registration_choice` / `lift_embargo`; from 2.19 it reads
# `draft_registration_id` / `embargo_end_date` and refuses the old names
# (api/registrations/serializers.py, `RegistrationCreateSerializer`; api/base/versioning.py).
# Leaving the version unset would mean whichever of the two OSF defaults to that day.
API_VERSION = "2.20"


@dataclass(frozen=True)
class Registration:
    id: str
    url: str
    #: The error OSF answered with, when the registration was found to exist anyway.
    recovered_from: str | None = None


#: How often, and how far apart, a failed registration request is checked and retried.
ATTEMPTS = 4
RETRY_WAIT = 20.0


def _registration_of(title: str, since: datetime.datetime, token: str) -> dict | None:
    """The registration of this draft made at or after `since`, if OSF lists one.

    A registration names neither the draft it came from nor, for a draft with no project, a
    node the draft shares, so the draft's title and the time are what identify it. Two
    registrations with the same title made in the same minutes would be ambiguous; that is
    refused rather than guessed.
    """
    q = urllib.parse.urlencode({"sort": "-date_created", "page[size]": 50})
    data = _request("GET", f"/users/me/registrations/?{q}", token)["data"]
    hits = [
        r
        for r in data
        if r["attributes"].get("title") == title
        and datetime.datetime.fromisoformat(r["attributes"]["date_created"]) >= since
    ]
    if len(hits) > 1:
        raise RuntimeError(
            f"OSF lists {len(hits)} registrations titled {title!r} since {since:%H:%M}; "
            "check them on OSF before doing anything else."
        )
    return hits[0] if hits else None


def register(draft_id: str, embargo: datetime.date | None, token: str) -> Registration:
    """Submit the draft as a registration: under embargo until `embargo`, or public at once.

    POST /v2/registrations/ creates the registration pending approval; OSF emails every admin
    and approves it after 48 hours unless one of them cancels (osf/models/registrations.py,
    `require_approval` / `embargo_registration`; website/settings REGISTRATION_APPROVAL_TIME,
    EMBARGO_PENDING_TIME). An embargo must end between about two days and four years ahead.
    The draft must have at least one subject, or OSF refuses it (`DraftRegistration.register`).

    A failed request is not a failed registration. OSF has answered 502 to the POST while
    creating the registration, and a retry then got 403 because the draft was already
    registered. So after a server error, a timeout or a refusal, OSF's list of registrations is
    read before anything is reported or retried. Retrying is safe on its own terms -- a draft
    registers once, and OSF refuses the second -- but reporting a failure that did not happen
    leaves a registration the log does not record. A 400 is OSF declining the draft (no subject,
    say) and is reported at once.
    """
    end = f"{embargo.isoformat()}T00:00:00" if embargo else None
    body = {
        "data": {
            "type": "registrations",
            "attributes": {"draft_registration_id": draft_id, "embargo_end_date": end},
        }
    }
    title = _request("GET", f"/draft_registrations/{draft_id}/", token)["data"]["attributes"][
        "title"
    ]
    # OSF's timestamps are naive UTC. A minute's slack covers a clock that runs ahead of OSF's.
    since = datetime.datetime.now(datetime.UTC).replace(tzinfo=None) - datetime.timedelta(minutes=1)
    error: OSFError | None = None
    for attempt in range(ATTEMPTS):
        if attempt:
            time.sleep(RETRY_WAIT)
        if error is not None:
            found = _registration_of(title, since, token)
            if found:
                return Registration(found["id"], f"https://osf.io/{found['id']}/", str(error)[:80])
        try:
            data = _request("POST", "/registrations/", token, body, version=API_VERSION)["data"]
        except OSFError as e:
            if e.status == 400:
                raise
            error = e
            continue
        url = (data.get("links") or {}).get("html") or f"https://osf.io/{data['id']}/"
        return Registration(data["id"], url)
    found = _registration_of(title, since, token)
    if found:
        return Registration(found["id"], f"https://osf.io/{found['id']}/", str(error)[:80])
    raise RuntimeError(f"OSF did not register draft {draft_id} after {ATTEMPTS} attempts: {error}")


@dataclass(frozen=True)
class ViewOnlyLink:
    id: str
    key: str
    url: str


def view_only_link(
    registration_id: str, anonymous: bool, name: str | None, token: str
) -> ViewOnlyLink:
    """Create a view-only link on a registration; `anonymous` hides the contributors.

    POST /v2/registrations/<id>/view_only_links/ (api/registrations/views.py,
    `RegistrationViewOnlyLinksList`, which takes `anonymous` and `name`:
    api/nodes/serializers.py, `NodeViewOnlyLinkSerializer`). The link is the registration's page
    with `?view_only=<key>` (website/project/views/node.py).
    """
    attributes: dict[str, object] = {"anonymous": anonymous}
    if name:
        attributes["name"] = name
    body = {"data": {"type": "view_only_links", "attributes": attributes}}
    path = f"/registrations/{registration_id}/view_only_links/"
    data = _request("POST", path, token, body, version=API_VERSION)["data"]
    key = data["attributes"]["key"]
    return ViewOnlyLink(data["id"], key, f"https://osf.io/{registration_id}/?view_only={key}")


# What the log records about OSF, and how it is read back. The log is the only local record of
# which draft was made from which freeze, so `register` reads it rather than asking for an id:
# an id typed by hand can name a draft made from a plan that has since been re-frozen.
DRAFT_EVENT = re.compile(r"\bosf draft (\S+) of plan ([0-9a-f]{16})\b")
REGISTRATION_EVENT = re.compile(r"\bosf registration (\S+) from draft ([^\s,]+)")
ATTACHED_EVENT = re.compile(r"\bosf attached (.+) sha256 ([0-9a-f]{64})\b")


def draft_event(draft_id: str, digest: str) -> str:
    return f"osf draft {draft_id} of plan {digest[:16]}"


def attached_event(name: str, sha256: str) -> str:
    return f"osf attached {name} sha256 {sha256}"


def registration_event(reg: Registration, draft_id: str, embargo: datetime.date | None) -> str:
    choice = f"embargo until {embargo.isoformat()}" if embargo else "immediate"
    event = f"osf registration {reg.id} from draft {draft_id}, {choice}, {reg.url}"
    if reg.recovered_from:
        # The request reported an error and the registration existed anyway; the log says so,
        # because the id was read from OSF's listing rather than from the answer to the request.
        status = re.search(r"\((\d{3})\)", reg.recovered_from)
        event += f", found after OSF error {status.group(1) if status else 'unreachable'}"
    return event


def link_event(link: ViewOnlyLink, registration_id: str, anonymous: bool) -> str:
    # The key is not logged. It opens an embargoed registration to whoever holds it, and the
    # log sits in a repository that may be public; the link id finds it again on OSF.
    kind = "anonymous" if anonymous else "named"
    return f"osf view-only link {link.id} on {registration_id}, {kind}"


def last(pattern: re.Pattern[str], entries: list[str]) -> re.Match[str] | None:
    """The last log entry matching `pattern`."""
    for line in reversed(entries):
        m = pattern.search(line)
        if m:
            return m
    return None


def setup_token(directory: Path | None = None) -> Path:
    """Write OSF_TOKEN to .env and add .env to .gitignore. Returns .env path."""
    target = directory or Path.cwd()
    env_path = target / ".env"
    gitignore = target / ".gitignore"

    import getpass

    token = getpass.getpass("OSF personal token (from https://osf.io/settings/tokens): ")
    token = token.strip()
    if not token:
        raise RuntimeError("no token provided")

    # `.env` is ignored before the token is in it. The two writes were the other way round, so a
    # crash between them left a credential in a file git was not yet told to skip. Ordering costs
    # nothing and the window is the whole exposure.
    with exclusive_lock(gitignore):
        if gitignore.exists():
            gi = gitignore.read_text()
            if ".env" not in gi.splitlines():
                atomic_write(gitignore, gi.rstrip("\n") + "\n.env\n")
        else:
            atomic_write(gitignore, ".env\n")

    # Read and write under one hold: a concurrent `prereg setup` reading the same snapshot would
    # drop whichever token was written second, and every other variable in the file with it.
    with exclusive_lock(env_path):
        if env_path.exists():
            text = env_path.read_text()
            lines = [ln for ln in text.splitlines() if not ln.startswith("OSF_TOKEN=")]
            lines.append(f"OSF_TOKEN={token}")
            atomic_write(env_path, "\n".join(lines) + "\n")
        else:
            atomic_write(env_path, f"OSF_TOKEN={token}\n")
        # A token is not a record. `atomic_write` keeps an existing file's mode, and a new one
        # gets the umask default, which on a shared machine is world-readable.
        env_path.chmod(0o600)

    return env_path
