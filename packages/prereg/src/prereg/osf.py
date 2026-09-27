"""OSF API v2 integration — push a frozen plan as a draft registration."""

from __future__ import annotations

import json
import os
import re
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


def _token() -> str | None:
    token = os.environ.get("OSF_TOKEN")
    if token:
        return token
    for p in [Path.cwd(), *Path.cwd().parents]:
        env = p / ".env"
        if env.is_file():
            for line in env.read_text().splitlines():
                line = line.strip()
                if line.startswith("OSF_TOKEN=") and not line.startswith("#"):
                    return line.split("=", 1)[1].strip().strip("'\"")
    return None


class OSFError(RuntimeError):
    """An OSF request failed. The message carries the status and OSF's own error body."""


def _request(
    method: str, path: str, token: str, body: dict | None = None, *, version: str | None = None
) -> dict:
    url = path if path.startswith("https://") else f"{API}{path}"
    if version:
        # OSF reads the version from a query parameter as well as the Accept header
        # (api/base/versioning.py, `get_query_param_version`). Without one it serves 2.0.
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode({"version": version})
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
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
            f"OSF API error ({e.code}) on {req.get_method()} {req.full_url}: {detail}"
        ) from e
    except urllib.error.URLError as e:
        raise OSFError(f"could not reach OSF ({req.full_url}): {e.reason}") from e


@dataclass(frozen=True)
class Question:
    key: str
    kind: str
    options: tuple[str, ...]


def _fetch_schema(token: str) -> dict[str, Question]:
    """Fetch the OSF Preregistration schema and return {question_title: Question}.

    The response keys live on the schema's `schema_blocks`, not on `attributes.schema.blocks`,
    which carries the text and no keys. Reading the latter returned an empty map, so every
    section with content was refused as unmapped. A question's label, its input and the input's
    options share a `schema_block_group_key`; OSF's own validator joins them the same way
    (osf/models/validators.py, `_build_question_schema`).
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


def build_draft(plan_text: str, token: str) -> dict:
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
            "no OSF token found. Set OSF_TOKEN in .env or as an environment variable.\n"
            "Create one at https://osf.io/settings/tokens (scope: osf.full_write)."
        )
    return token


def create_draft(body: dict, token: str) -> tuple[str, str]:
    """POST the draft. Returns (draft_id, url)."""
    resp = _request("POST", "/draft_registrations/", token, body)
    draft_id = resp["data"]["id"]
    return draft_id, f"https://osf.io/{draft_id}"


def push_draft(plan_text: str) -> tuple[str, str]:
    """Create a draft registration on OSF from a PREREG.md.

    Returns (draft_id, url). Raises if token missing or API fails.
    """
    token = require_token()
    return create_draft(build_draft(plan_text, token), token)


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
