"""The Codex plugin, which is the Claude Code bundle read by a second runtime.

`packages/repro/plugin` is one directory with two manifests. Codex looks for a plugin's manifest
at `plugin.json`, then `.codex-plugin/plugin.json`, then `.claude-plugin/plugin.json`, and takes
the first it finds (`DISCOVERABLE_PLUGIN_MANIFEST_PATHS` and `find_plugin_manifest_path` in
openai/codex, `codex-rs/utils/plugins/src/plugin_namespace.rs`). Claude Code reads only
`.claude-plugin/plugin.json`. So the Codex manifest sits in `.codex-plugin/` and points at the
same `skills/` directory: there is one copy of each skill and nothing to keep in step.

What differs is the hooks. Codex edits files through `apply_patch`, whose input is the patch text
in `tool_input.command` with no `file_path`, so the four edit hooks run behind
`hooks/codex_apply_patch.py`, which hands each one the payload Claude Code would have sent for
each file the patch touches. The format these tests feed it is the one documented at
https://developers.openai.com/codex/hooks.md and built in `codex-rs/core/src/tools/handlers/
apply_patch.rs` (`pre_tool_use_payload`: `{"command": <patch>}`).

The schemas under `schemas/agent-plugins-1.0.0/` are copied byte for byte from
https://agent-plugins.org/schemas/1.0.0/, fetched 2026-10-14.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

import jsonschema
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "packages" / "repro" / "plugin"
CLAUDE_MANIFEST = PLUGIN / ".claude-plugin" / "plugin.json"
CODEX_MANIFEST = PLUGIN / ".codex-plugin" / "plugin.json"
MARKETPLACE = ROOT / ".agents" / "plugins" / "marketplace.json"
CLAUDE_MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
SCHEMAS = pathlib.Path(__file__).resolve().parent / "schemas" / "agent-plugins-1.0.0"
ADAPTER = PLUGIN / "hooks" / "codex_apply_patch.py"


def load(path: pathlib.Path) -> dict:
    return json.loads(path.read_text())


def manifest() -> dict:
    return load(CODEX_MANIFEST)


def under_plugin(relative: str) -> pathlib.Path:
    """A manifest path resolved the way Codex resolves it, or a failure saying why it would not."""
    assert relative.startswith("./"), f"{relative!r}: Codex ignores a path without a leading ./"
    assert ".." not in relative.split("/"), f"{relative!r}: Codex ignores a path containing .."
    resolved = (PLUGIN / relative[2:]).resolve()
    assert resolved.is_relative_to(PLUGIN.resolve()), f"{relative!r} leaves the plugin root"
    return resolved


# The manifest.

#: The fields of a `.codex-plugin/plugin.json`, from "Manifest fields" at
#: https://developers.openai.com/plugins/deploy/submission and the parser (`RawPluginManifest` in
#: `codex-rs/core-plugins/src/manifest.rs`, which also reads `apps` and `hooks`). The parser
#: ignores the rest, and a misspelt field is ignored the same way, so an unknown one fails here.
MANIFEST_FIELDS = {
    "name",
    "version",
    "description",
    "author",
    "homepage",
    "repository",
    "license",
    "keywords",
    "skills",
    "mcpServers",
    "apps",
    "hooks",
    "interface",
    "extensions",
    "id",
}

INTERFACE_FIELDS = {
    "displayName",
    "shortDescription",
    "longDescription",
    "developerName",
    "category",
    "capabilities",
    "websiteURL",
    "supportURL",
    "privacyPolicyURL",
    "termsOfServiceURL",
    "defaultPrompt",
    "brandColor",
    "brandColorDark",
    "composerIcon",
    "composerIconDark",
    "logo",
    "logoDark",
    "screenshots",
}

#: The identity fields a portable Agent Plugins manifest shares with this one.
IDENTITY = {"name", "version", "description", "author", "homepage", "repository", "license"}


def test_the_manifest_declares_only_fields_codex_reads():
    unknown = set(manifest()) - MANIFEST_FIELDS
    assert not unknown, f"Codex ignores {sorted(unknown)} in .codex-plugin/plugin.json"
    unknown = set(manifest().get("interface", {})) - INTERFACE_FIELDS
    assert not unknown, f"Codex ignores interface fields {sorted(unknown)}"


def test_the_manifest_has_every_field_the_codex_format_requires():
    """The "Required for Codex" rows of the field tables on the submission page."""
    found = manifest()
    assert "$schema" not in found, "the docs say to omit $schema from a Codex manifest"
    assert found["version"].strip() and found["description"].strip()
    assert found["author"]["name"].strip()
    interface = found["interface"]
    for field in ("displayName", "shortDescription", "longDescription", "developerName"):
        assert interface[field].strip(), f"interface.{field} is required"
    assert interface["category"].strip()
    assert isinstance(interface["capabilities"], list)
    assert len(interface["displayName"]) <= 30 and len(interface["shortDescription"]) <= 30


def test_the_identity_fields_are_a_valid_agent_plugins_manifest():
    """The name rule is the portable one, so a later move to a root `plugin.json` keeps it."""
    identity = {key: value for key, value in manifest().items() if key in IDENTITY | {"keywords"}}
    identity["$schema"] = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
    jsonschema.validate(identity, load(SCHEMAS / "plugin.schema.json"))


def test_the_codex_and_claude_manifests_name_one_plugin_at_one_version():
    claude = load(CLAUDE_MANIFEST)
    assert {"name", "version", "description"} <= claude.keys()
    for field in (IDENTITY | {"keywords"}) & claude.keys():
        assert manifest()[field] == claude[field], f"{field} differs between the two manifests"


def test_the_codex_manifest_carries_the_release_version():
    assert manifest()["version"] == load(CLAUDE_MARKETPLACE)["metadata"]["version"]


def versions_module():
    spec = importlib.util.spec_from_file_location("versions", ROOT / "scripts" / "versions.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_release_bump_writes_the_codex_manifest_version(tmp_path, monkeypatch):
    versions = versions_module()
    assert CODEX_MANIFEST in versions.PLUGIN_MANIFESTS

    copy = tmp_path / "plugin.json"
    copy.write_text(CODEX_MANIFEST.read_text())
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "x"\nversion = "0.6.1"\n')
    monkeypatch.setattr(versions, "PACKAGES", {"x": pyproject})
    monkeypatch.setattr(versions, "PLUGIN_MANIFESTS", (copy,))
    monkeypatch.setattr(versions, "HOOKS", tmp_path / "absent.yaml")
    monkeypatch.setattr(versions, "HOOK_README", tmp_path / "absent.md")
    monkeypatch.setattr(versions, "CITATION", tmp_path / "absent.cff")
    monkeypatch.setattr(versions, "PROJECT_ROOT", tmp_path)

    versions.bump("9.9.9")

    bumped = load(copy)
    assert bumped["version"] == "9.9.9"
    assert {k: v for k, v in bumped.items() if k != "version"} == {
        k: v for k, v in manifest().items() if k != "version"
    }


def test_codex_reads_this_manifest_and_not_the_claude_one():
    """A root `plugin.json` with an Agent Plugins `$schema` would win over both. It would also
    switch Copilot CLI, which reads `.claude-plugin/plugin.json` today, to Agent Plugins rules,
    under which it loads no hooks from `hooks/hooks.json`."""
    assert not (PLUGIN / "plugin.json").exists()
    assert CODEX_MANIFEST.is_file() and not CODEX_MANIFEST.is_symlink()


@pytest.mark.parametrize("field", ["skills", "mcpServers", "hooks"])
def test_every_component_path_resolves_inside_the_plugin(field):
    assert under_plugin(manifest()[field]).exists(), f"{field}: {manifest()[field]} is missing"


def test_the_skills_codex_loads_are_the_claude_plugins_skills():
    """One directory, so the skills cannot drift. Codex's install copy keeps regular files and
    drops symlinks (`copy_dir_recursive` in `codex-rs/core-plugins/src/store.rs`), so a skill
    linked in from elsewhere would install as nothing."""
    loaded = under_plugin(manifest()["skills"])
    assert loaded == (PLUGIN / "skills").resolve()
    skills = sorted(loaded.glob("*/SKILL.md"))
    assert {path.parent.name for path in skills} == {
        "citations",
        "open-items",
        "osf-registration",
        "prereg",
        "prereg-style",
        "repro",
        "results",
    }
    for path in [loaded, *loaded.rglob("*")]:
        assert not path.is_symlink(), f"{path} is a symlink, which Codex does not install"


def test_the_mcp_config_is_a_valid_agent_plugins_config_running_repro_mcp():
    config = load(under_plugin(manifest()["mcpServers"]))
    jsonschema.validate(config, load(SCHEMAS / "mcp.schema.json"))
    assert config["mcpServers"] == {"repro": {"type": "stdio", "command": "repro", "args": ["mcp"]}}


def test_the_mcp_config_is_not_where_claude_code_would_load_it():
    """Claude Code reads `.mcp.json` at a plugin's root, and so does Codex by default. A server
    meant for Codex alone is named in the Codex manifest under another file name."""
    assert manifest()["mcpServers"] != "./.mcp.json"
    assert not (PLUGIN / ".mcp.json").exists()


# The marketplace.


def marketplace() -> dict:
    return load(MARKETPLACE)


def test_the_marketplace_lists_the_bundle_as_codex_requires():
    """Codex reads `.agents/plugins/marketplace.json` before `.claude-plugin/marketplace.json`
    (`MARKETPLACE_MANIFEST_RELATIVE_PATHS`), so this file is the one Codex sees."""
    document = marketplace()
    assert document["name"] == load(CLAUDE_MARKETPLACE)["name"]
    for entry in document["plugins"]:
        assert entry["source"]["source"] == "local"
        assert entry["policy"]["installation"] in {
            "AVAILABLE",
            "INSTALLED_BY_DEFAULT",
            "NOT_AVAILABLE",
        }
        assert entry["policy"]["authentication"] in {"ON_INSTALL", "ON_USE"}
        assert entry["category"]


@pytest.mark.parametrize("entry", marketplace()["plugins"], ids=lambda e: e["name"])
def test_every_marketplace_entry_points_at_a_codex_manifest_of_that_name(entry):
    path = entry["source"]["path"]
    assert path.startswith("./") and ".." not in path.split("/")
    root = ROOT / path[2:]
    assert load(root / ".codex-plugin" / "plugin.json")["name"] == entry["name"]


def test_every_plugin_with_a_codex_manifest_is_listed():
    on_disk = {p.parents[1] for p in ROOT.glob("packages/*/*/.codex-plugin/plugin.json")}
    listed = {ROOT / e["source"]["path"][2:] for e in marketplace()["plugins"]}
    assert on_disk == listed


# The hooks file.

#: Events Codex dispatches, from https://developers.openai.com/codex/hooks.md.
CODEX_EVENTS = {
    "PreToolUse",
    "PermissionRequest",
    "PostToolUse",
    "PreCompact",
    "PostCompact",
    "UserPromptSubmit",
    "SubagentStop",
    "Stop",
    "Interrupt",
    "SessionStart",
    "SubagentStart",
    "SessionEnd",
}


def handlers() -> list[tuple[str, str, str]]:
    """(event, matcher, command) for every handler the Codex hooks file declares."""
    document = load(under_plugin(manifest()["hooks"]))
    assert set(document) <= {"description", "hooks"}, "Codex reads only `hooks` at the top"
    assert set(document["hooks"]) <= CODEX_EVENTS
    return [
        (event, group.get("matcher", ""), handler["command"])
        for event, groups in document["hooks"].items()
        for group in groups
        for handler in group["hooks"]
        if handler["type"] == "command"
    ]


def scripts(command: str) -> list[str]:
    return re.findall(r"[\w-]+\.py", command)


def test_every_claude_hook_is_ported_or_runs_unchanged():
    claude = load(PLUGIN / "hooks" / "hooks.json")["hooks"]
    wanted = {
        (event, script)
        for event, groups in claude.items()
        for group in groups
        for handler in group["hooks"]
        for script in scripts(handler["command"])
    }
    ported = {(event, scripts(command)[-1]) for event, _, command in handlers()}
    assert wanted <= ported


@pytest.mark.parametrize("event,matcher,command", handlers())
def test_every_hook_command_names_scripts_that_exist(event, matcher, command):
    for script in scripts(command):
        path = PLUGIN / "hooks" / script
        assert path.is_file(), f"{command} names {script}, which is not in hooks/"
        assert path.stat().st_mode & 0o111, f"{script} is not executable"


@pytest.mark.parametrize("event,matcher,command", handlers())
def test_every_hook_command_reads_the_plugin_root_in_a_form_every_shell_expands(
    event, matcher, command
):
    """Codex runs a hook as `$SHELL -lc <command>`. fish rejects `${PLUGIN_ROOT}`; it, bash, zsh
    and sh all expand `$PLUGIN_ROOT` inside double quotes."""
    assert "${" not in command
    assert '"$PLUGIN_ROOT/hooks/' in command


def test_every_edit_hook_runs_on_apply_patch_and_on_a_patch_sent_through_the_shell():
    edit_hooks = {"frozen_file_before_edit.py", "frozen_plan_changed.py"}
    edit_hooks |= {"unverified_quotations.py", "unbound_numbers.py"}
    for tool in ("apply_patch", "Bash"):
        covered = {
            scripts(command)[-1]
            for _, matcher, command in handlers()
            if "codex_apply_patch.py" in command and re.fullmatch(matcher, tool)
        }
        assert covered == edit_hooks, f"{tool}: {sorted(edit_hooks - covered)} never run"


# The hooks, given what Codex sends.


def patch(*hunks: str) -> str:
    return "*** Begin Patch\n" + "".join(hunks) + "*** End Patch\n"


def codex_payload(event: str, tool_name: str, command: str, cwd: pathlib.Path) -> dict:
    """A hook input as Codex writes it, with the fields every turn-scoped event carries."""
    payload = {
        "session_id": "thr_1",
        "transcript_path": None,
        "cwd": str(cwd),
        "hook_event_name": event,
        "model": "gpt-5",
        "turn_id": "turn_1",
        "permission_mode": "default",
        "tool_name": tool_name,
        "tool_use_id": "call_1",
        "tool_input": {"command": command},
    }
    if event == "PostToolUse":
        payload["tool_response"] = "Success."
    return payload


def adapt(hook: str, payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ADAPTER), hook],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=60,
    )


def spoken(out: subprocess.CompletedProcess) -> dict:
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout) if out.stdout.strip() else {}


def denial(out: subprocess.CompletedProcess) -> str:
    decision = spoken(out)["hookSpecificOutput"]
    assert decision["hookEventName"] == "PreToolUse"
    assert decision["permissionDecision"] == "deny"
    return decision["permissionDecisionReason"]


def frozen_whole(directory: pathlib.Path, name: str, body: str) -> pathlib.Path:
    (directory / ".prereg").mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(body)
    digest = hashlib.sha256(body.encode()).hexdigest()
    (directory / ".prereg" / f"{name}.json").write_text(json.dumps({"sha256": digest}))
    return path


PLAN = "# Plan\n\nH1. The effect exceeds 0.10.\n"
FROZEN_IN_PLACE = "# Plan\n\n**Plan sha256:** `" + "0" * 64 + "`\n\nWe will measure X.\n"
REFUSE = "frozen_file_before_edit.py"


def claude_reason(path: pathlib.Path) -> str:
    """What the hook says to Claude Code about an edit to `path`."""
    out = subprocess.run(
        [sys.executable, str(PLUGIN / "hooks" / REFUSE)],
        input=json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(path)}}),
        capture_output=True,
        text=True,
        timeout=30,
    )
    return json.loads(out.stdout)["hookSpecificOutput"]["permissionDecisionReason"]


def test_an_apply_patch_to_a_plan_frozen_whole_is_denied_as_claude_code_denies_it(tmp_path):
    path = frozen_whole(tmp_path, "PREREG.md", PLAN)
    command = patch("*** Update File: PREREG.md\n@@\n-H1. The effect exceeds 0.10.\n+H1. Any.\n")
    reason = denial(adapt(REFUSE, codex_payload("PreToolUse", "apply_patch", command, tmp_path)))
    assert reason == claude_reason(path)
    assert path.read_text() == PLAN


def test_an_apply_patch_to_a_plan_frozen_in_place_is_denied(tmp_path):
    (tmp_path / "PREREG.md").write_text(FROZEN_IN_PLACE)
    command = patch("*** Update File: PREREG.md\n@@\n-We will measure X.\n+We measured Y.\n")
    reason = denial(adapt(REFUSE, codex_payload("PreToolUse", "apply_patch", command, tmp_path)))
    assert f"{tmp_path / 'PREREG.md'} is a frozen registration" in reason


@pytest.mark.parametrize(
    "hunk",
    [
        "*** Delete File: PREREG.md\n",
        "*** Add File: PREREG.md\n+# A new plan\n",
        "*** Update File: PREREG.md\n*** Move to: OLD_PREREG.md\n",
        "*** Update File: notes.md\n*** Move to: PREREG.md\n@@\n+moved over the plan\n",
    ],
    ids=["delete", "overwrite", "move-away", "move-onto"],
)
def test_every_patch_operation_that_changes_a_frozen_file_is_denied(tmp_path, hunk):
    frozen_whole(tmp_path, "PREREG.md", PLAN)
    (tmp_path / "notes.md").write_text("notes\n")
    command = patch(hunk)
    reason = denial(adapt(REFUSE, codex_payload("PreToolUse", "apply_patch", command, tmp_path)))
    assert "has a freeze record" in reason


def test_a_patch_touching_one_frozen_file_among_others_is_denied_for_that_file(tmp_path):
    path = frozen_whole(tmp_path, "PREREG.md", PLAN)
    (tmp_path / "analysis.py").write_text("x = 1\n")
    command = patch(
        "*** Update File: analysis.py\n@@\n-x = 1\n+x = 2\n",
        "*** Update File: PREREG.md\n@@\n-H1. The effect exceeds 0.10.\n+H1. Any.\n",
    )
    reason = denial(adapt(REFUSE, codex_payload("PreToolUse", "apply_patch", command, tmp_path)))
    assert reason == claude_reason(path)


def test_a_patch_to_an_unfrozen_plan_is_allowed_in_silence(tmp_path):
    (tmp_path / "PREREG.md").write_text("# Plan\n\nStill a draft.\n")
    command = patch("*** Update File: PREREG.md\n@@\n-Still a draft.\n+Nearly done.\n")
    out = adapt(REFUSE, codex_payload("PreToolUse", "apply_patch", command, tmp_path))
    assert spoken(out) == {}


def test_a_patch_run_through_the_shell_is_denied_too(tmp_path):
    """Codex intercepts `apply_patch` typed as a shell command, and the hook sees a `Bash` call."""
    frozen_whole(tmp_path, "PREREG.md", PLAN)
    body = patch("*** Update File: PREREG.md\n@@\n-H1. The effect exceeds 0.10.\n+H1. Any.\n")
    command = f"apply_patch <<'EOF'\n{body}EOF\n"
    reason = denial(adapt(REFUSE, codex_payload("PreToolUse", "Bash", command, tmp_path)))
    assert "has a freeze record" in reason


def test_a_shell_command_with_no_patch_is_left_alone(tmp_path):
    frozen_whole(tmp_path, "PREREG.md", PLAN)
    command = "sed -i '' s/0.10/0.05/ PREREG.md"
    assert spoken(adapt(REFUSE, codex_payload("PreToolUse", "Bash", command, tmp_path))) == {}


@pytest.mark.parametrize(
    "hook,event",
    [
        (REFUSE, "PostToolUse"),
        ("frozen_plan_changed.py", "PreToolUse"),
        ("unfrozen_plan_before_run.py", "PreToolUse"),
        ("../../../anything.py", "PreToolUse"),
    ],
)
def test_the_adapter_runs_only_an_edit_hook_on_its_own_event(tmp_path, hook, event):
    frozen_whole(tmp_path, "PREREG.md", PLAN)
    command = patch("*** Update File: PREREG.md\n@@\n-H1. The effect exceeds 0.10.\n+H1. Any.\n")
    assert spoken(adapt(hook, codex_payload(event, "apply_patch", command, tmp_path))) == {}


@pytest.mark.parametrize("stdin", ["", "this is not json", "[]", '{"tool_input": {"command": 3}}'])
def test_input_the_adapter_cannot_read_allows_the_edit(stdin):
    out = subprocess.run(
        [sys.executable, str(ADAPTER), REFUSE],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert out.returncode == 0
    assert out.stdout.strip() == ""


@pytest.mark.parametrize("frozen_in_place", [False, True], ids=["whole", "in-place"])
def test_a_patch_through_a_symlink_to_a_frozen_plan_is_denied(tmp_path, frozen_in_place):
    if frozen_in_place:
        (tmp_path / "PREREG.md").write_text(FROZEN_IN_PLACE)
    else:
        frozen_whole(tmp_path, "PREREG.md", PLAN)
    (tmp_path / "link.md").symlink_to("PREREG.md")
    command = patch("*** Update File: link.md\n@@\n+appended through the link\n")
    reason = denial(adapt(REFUSE, codex_payload("PreToolUse", "apply_patch", command, tmp_path)))
    assert str((tmp_path / "PREREG.md").resolve()) in reason


#: A stand-in for the refusing hook, for the failures the real one does not have on demand. It
#: refuses `A.md`, hangs on `slow.md`, and crashes on anything else.
FAILING_HOOK = """import json, sys, time
path = json.load(sys.stdin)["tool_input"]["file_path"]
if path.endswith("/A.md"):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
        "permissionDecision": "deny", "permissionDecisionReason": "A is frozen"}}))
elif path.endswith("/slow.md"):
    time.sleep(30)
else:
    sys.exit(1)
"""


def adapt_with_failing_hook(tmp_path: pathlib.Path, command: str, cwd: pathlib.Path):
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    adapter = ADAPTER.read_text().replace("TIMEOUT_SECONDS = 30", "TIMEOUT_SECONDS = 1")
    assert "TIMEOUT_SECONDS = 1" in adapter
    (hooks / ADAPTER.name).write_text(adapter)
    (hooks / REFUSE).write_text(FAILING_HOOK)
    return subprocess.run(
        [sys.executable, str(hooks / ADAPTER.name), REFUSE],
        input=json.dumps(codex_payload("PreToolUse", "apply_patch", command, cwd)),
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.parametrize("name", ["PREREG.md", "prereg.md", "notes.md"])
def test_a_check_that_fails_on_a_possibly_frozen_file_refuses_the_patch(tmp_path, name):
    project = tmp_path / "project"
    (project / ".prereg").mkdir(parents=True)
    command = patch(f"*** Update File: {name}\n@@\n+x\n")
    reason = denial(adapt_with_failing_hook(tmp_path, command, project))
    assert f"{project / name} may be a frozen preregistration and could not be checked" in reason


def test_a_check_that_fails_on_a_file_that_cannot_be_frozen_allows_the_patch(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    command = patch("*** Update File: analysis.py\n@@\n+x = 2\n")
    assert spoken(adapt_with_failing_hook(tmp_path, command, project)) == {}


def test_a_refusal_already_found_survives_a_later_file_timing_out(tmp_path):
    project = tmp_path / "project"
    (project / ".prereg").mkdir(parents=True)
    command = patch(
        "*** Update File: A.md\n@@\n+x\n",
        "*** Update File: slow.md\n@@\n+y\n",
        "*** Update File: other/elsewhere.py\n@@\n+z\n",
    )
    reason = denial(adapt_with_failing_hook(tmp_path, command, project))
    assert "A is frozen" in reason
    assert f"{project / 'slow.md'} may be a frozen preregistration" in reason
    assert "elsewhere.py" not in reason


@pytest.mark.parametrize(
    "command",
    ["*** Update File: PREREG.md\n@@\n+x\n", "not a patch at all", "*** Begin Patch\n"],
    ids=["no-begin", "prose", "empty"],
)
def test_a_patch_that_cannot_be_read_is_passed(tmp_path, command):
    frozen_whole(tmp_path, "PREREG.md", PLAN)
    out = adapt(REFUSE, codex_payload("PreToolUse", "apply_patch", command, tmp_path))
    assert spoken(out) == {}


def test_the_unfrozen_plan_hook_reads_a_codex_bash_payload_unchanged(tmp_path):
    (tmp_path / "PREREG.md").write_text("# Plan\n\n**Status:** DRAFT\n\nWe will measure X.\n")
    out = subprocess.run(
        [sys.executable, str(PLUGIN / "hooks" / "unfrozen_plan_before_run.py")],
        input=json.dumps(codex_payload("PreToolUse", "Bash", "python fit.py", tmp_path)),
        capture_output=True,
        text=True,
        timeout=30,
    )
    said = spoken(out)
    assert said["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert "carries no freeze" in said["hookSpecificOutput"]["additionalContext"]
    assert "permissionDecision" not in said["hookSpecificOutput"]


def test_a_frozen_file_changed_by_a_patch_is_reported_after_it(tmp_path):
    path = frozen_whole(tmp_path, "PREREG.md", PLAN)
    command = patch("*** Update File: PREREG.md\n@@\n-H1. The effect exceeds 0.10.\n+H1. Any.\n")
    payload = codex_payload("PostToolUse", "apply_patch", command, tmp_path)
    assert spoken(adapt("frozen_plan_changed.py", payload)) == {}, "unchanged, so nothing said"

    path.write_text("# Plan\n\nH1. Any.\n")
    said = spoken(adapt("frozen_plan_changed.py", payload))["hookSpecificOutput"]
    assert said["hookEventName"] == "PostToolUse"
    assert "PREREG.md was frozen whole and no longer matches" in said["additionalContext"]


def test_a_number_a_patch_adds_with_no_claim_is_reported(tmp_path):
    (tmp_path / ".results").mkdir()
    claim = {"event": "claim", "claim": "Accuracy was 0.873 on the held-out split."}
    (tmp_path / ".results" / "ledger.jsonl").write_text(json.dumps(claim) + "\n")
    (tmp_path / "paper.md").write_text("Accuracy was 0.873 and recall was 0.641.\n")
    command = patch("*** Add File: paper.md\n+Accuracy was 0.873 and recall was 0.641.\n")
    payload = codex_payload("PostToolUse", "apply_patch", command, tmp_path)
    said = spoken(adapt("unbound_numbers.py", payload))["hookSpecificOutput"]["additionalContext"]
    assert "1 number(s) entered paper.md" in said
    assert "0.641" in said and "0.873" not in said.split("Ledger:")[0]


def test_a_number_only_the_removed_lines_held_is_not_reported(tmp_path):
    (tmp_path / ".results").mkdir()
    (tmp_path / ".results" / "ledger.jsonl").write_text("")
    (tmp_path / "paper.md").write_text("Recall was 0.641.\n")
    command = patch("*** Update File: paper.md\n@@\n-Recall was 0.641.\n+Recall was 0.641!\n")
    payload = codex_payload("PostToolUse", "apply_patch", command, tmp_path)
    assert spoken(adapt("unbound_numbers.py", payload)) == {}


PASSAGE = "a printed value should name the address it came from, and searching afterwards is not provenance"


def test_a_quotation_a_patch_adds_with_no_pin_is_reported(tmp_path):
    (tmp_path / "claims").mkdir()
    (tmp_path / "claims" / "pinned.yaml").write_text(
        'claims:\n  a:\n    quotes:\n    - exact: "something else entirely, pinned so it exists"\n'
    )
    (tmp_path / "draft.md").write_text(f'The source states that "{PASSAGE}".\n')
    command = patch(f'*** Add File: draft.md\n+The source states that "{PASSAGE}".\n')
    payload = codex_payload("PostToolUse", "apply_patch", command, tmp_path)
    said = spoken(adapt("unverified_quotations.py", payload))
    assert PASSAGE in said["hookSpecificOutput"]["additionalContext"]


def test_a_deleted_file_is_not_read_after_the_patch(tmp_path):
    (tmp_path / ".results").mkdir()
    (tmp_path / ".results" / "ledger.jsonl").write_text("")
    command = patch("*** Delete File: paper.md\n")
    payload = codex_payload("PostToolUse", "apply_patch", command, tmp_path)
    assert spoken(adapt("unbound_numbers.py", payload)) == {}


def test_the_declared_command_denies_when_run_by_a_shell_as_codex_runs_it(tmp_path):
    """The wiring: the command string from the hooks file, run by a shell with `PLUGIN_ROOT` set.
    Codex runs it as `$SHELL -lc` (`build_command` in `codex-rs/hooks/src/engine/command_runner.rs`);
    `-c` here keeps a login profile from changing which `python3` is found."""
    path = frozen_whole(tmp_path, "PREREG.md", PLAN)
    [command] = [c for event, m, c in handlers() if event == "PreToolUse" and m == "^apply_patch$"]
    body = patch("*** Update File: PREREG.md\n@@\n-H1. The effect exceeds 0.10.\n+H1. Any.\n")
    env = {
        **os.environ,
        "PLUGIN_ROOT": str(PLUGIN),
        "PATH": f"{pathlib.Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}",
    }
    out = subprocess.run(
        [shutil.which("sh") or "/bin/sh", "-c", command],
        input=json.dumps(codex_payload("PreToolUse", "apply_patch", body, tmp_path)),
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        cwd=tmp_path,
    )
    assert denial(out) == claude_reason(path)
