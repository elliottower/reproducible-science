"""OSF API v2 integration — push a frozen plan as a draft registration."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

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


def _request(method: str, path: str, token: str, body: dict | None = None) -> dict:
    url = f"{API}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/vnd.api+json")
    req.add_header("Accept", "application/vnd.api+json")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def _fetch_schema(token: str) -> dict[str, str]:
    """Fetch the OSF Preregistration schema and return {question_title: response_key}."""
    resp = _request("GET", f"/schemas/registrations/{SCHEMA_ID}/", token)
    blocks = resp["data"]["attributes"]["schema"]["blocks"]
    mapping = {}
    for i, block in enumerate(blocks):
        if block.get("block_type") in ("question-label", "section-heading"):
            continue
        display = block.get("display_text", "")
        if not display:
            continue
        clean = re.sub(r"<[^>]+>", "", display).strip()
        key = block.get("registration_response_key")
        if key and clean:
            mapping[clean] = key
    return mapping


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


def push_draft(plan_text: str) -> tuple[str, str]:
    """Create a draft registration on OSF from a PREREG.md.

    Returns (draft_id, url). Raises if token missing or API fails.
    """
    token = _token()
    if not token:
        raise RuntimeError(
            "no OSF token found. Set OSF_TOKEN in .env or as an environment variable.\n"
            "Create one at https://osf.io/settings/tokens (scope: osf.full_write)."
        )

    title, sections = _parse_plan(plan_text)
    schema_map = _fetch_schema(token)

    responses = {}
    for heading, content in sections.items():
        question = HEADING_TO_QUESTION.get(heading)
        if not question:
            continue
        key = schema_map.get(question)
        if key and content:
            stripped = content.lstrip("_").rstrip("_").strip()
            if stripped and stripped != "N/A —":
                responses[key] = stripped

    body = {
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

    try:
        resp = _request("POST", "/draft_registrations/", token, body)
    except urllib.error.HTTPError as e:
        detail = e.read().decode() if e.fp else str(e)
        raise RuntimeError(f"OSF API error ({e.code}): {detail}") from e

    draft_id = resp["data"]["id"]
    url = f"https://osf.io/{draft_id}"
    return draft_id, url


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

    if env_path.exists():
        text = env_path.read_text()
        lines = [ln for ln in text.splitlines() if not ln.startswith("OSF_TOKEN=")]
        lines.append(f"OSF_TOKEN={token}")
        env_path.write_text("\n".join(lines) + "\n")
    else:
        env_path.write_text(f"OSF_TOKEN={token}\n")

    if gitignore.exists():
        gi = gitignore.read_text()
        if ".env" not in gi.splitlines():
            gitignore.write_text(gi.rstrip("\n") + "\n.env\n")
    else:
        gitignore.write_text(".env\n")

    return env_path
