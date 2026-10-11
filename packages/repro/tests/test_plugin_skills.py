"""The plugins' skills, which are discovered by directory and listed in no manifest.

A skill is a `skills/<name>/SKILL.md` whose frontmatter carries the name it answers to and the
description a model reads when deciding whether to load it. Nothing registers one, so nothing
fails when one is malformed: a skill with no description is never chosen, and a skill added to a
`prereg` plugin and not to the bundle is missing for everyone who installed the bundle.
"""

from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
BUNDLE = ROOT / "packages" / "repro" / "plugin" / "skills"

#: Every skill in every plugin, as (package, skill name).
SKILLS = sorted(
    (path.parents[3].name, path.parent.name)
    for path in ROOT.glob("packages/*/plugin/skills/*/SKILL.md")
)

#: The skills the `prereg` plugin ships, which the bundle carries unchanged. The `citations` and
#: `results` skills are worded differently in the bundle, so they are not compared here.
PREREG = [name for package, name in SKILLS if package == "prereg"]


def skill(package: str, name: str) -> pathlib.Path:
    return ROOT / "packages" / package / "plugin" / "skills" / name / "SKILL.md"


def frontmatter(path: pathlib.Path) -> dict[str, str]:
    opening, block, _ = path.read_text().split("---\n", 2)
    assert opening == "", f"{path} does not open with frontmatter"
    return dict(line.split(": ", 1) for line in block.splitlines())


def test_the_prereg_plugin_ships_the_osf_and_style_skills():
    assert {("prereg", "osf-registration"), ("prereg", "prereg-style")} <= set(SKILLS)


@pytest.mark.parametrize(("package", "name"), SKILLS, ids=lambda value: value)
def test_a_skill_answers_to_its_directory_and_says_when_to_use_it(package, name):
    found = frontmatter(skill(package, name))
    assert found["name"] == name
    assert found["description"].strip()


@pytest.mark.parametrize(("package", "name"), SKILLS, ids=lambda value: value)
def test_a_plugins_readme_names_every_skill_its_directory_holds(package, name):
    readme = (ROOT / "packages" / package / "plugin" / "README.md").read_text()
    assert re.search(rf"(?:`|skills/){re.escape(name)}(?:`|/)", readme), (
        f"packages/{package}/plugin/README.md does not name the skill {name}"
    )


@pytest.mark.parametrize("name", PREREG)
def test_the_bundle_ships_every_prereg_skill_byte_for_byte(name):
    assert (BUNDLE / name / "SKILL.md").read_bytes() == skill("prereg", name).read_bytes()
