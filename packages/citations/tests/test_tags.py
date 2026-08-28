"""A tag has no source to be rebuilt from, so the vocabulary is the only thing checking it.

`cited_by` cannot drift: `citations build` rewrites it from the bibliographies. Not one of the
1,202 bib entries across this registry carries a `keywords` field, so nothing can do the same
for a tag. These pin the two properties that follow: an undeclared tag is a finding rather than
a new tag, and a bulk write needs a query before it will touch anything.
"""

from __future__ import annotations

import pytest
import yaml
from citations.exceptions import CitationsError
from citations.tags import (
    Kind,
    apply,
    namespaces,
    survey,
    undeclared,
    untagged,
    vocabulary,
)


def library(tmp_path, tags=None, records=None):
    (tmp_path / "records").mkdir(parents=True, exist_ok=True)
    if tags is not None:
        (tmp_path / "tags.yaml").write_text(yaml.safe_dump({"tags": tags}))
    for name, body in (records or {}).items():
        (tmp_path / "records" / f"{name}.yaml").write_text(yaml.safe_dump(body))
    return tmp_path


def counts(found):
    return {u.tag: u.count for u in found}


def test_a_library_with_no_vocabulary_declares_no_tags(tmp_path):
    assert vocabulary(library(tmp_path / "lib")) == {}


def test_a_tag_may_be_declared_with_no_description(tmp_path):
    lib = library(tmp_path / "lib", tags={"ai-safety": None})
    assert vocabulary(lib)["ai-safety"].description == ""


def test_the_tree_is_read_off_the_name_and_cannot_disagree_with_it():
    assert namespaces({"a/b/c", "a/d"}) == {"a", "a/b"}


def test_a_declared_name_is_not_also_reported_as_a_namespace():
    """`a` is declared, so it is applicable; it must not appear twice."""
    assert namespaces({"a", "a/b"}) == set()


def test_counts_roll_up_by_record_not_by_tag(tmp_path):
    """A work under two children of one parent is one work, and the count answers "how many
    works does this cover"."""
    lib = library(
        tmp_path / "lib",
        tags={"ai/governance": "", "ai/evaluation": ""},
        records={"r": {"slug": "r", "tags": ["ai/governance", "ai/evaluation"]}},
    )
    assert counts(survey(lib))["ai"] == 1


def test_a_parent_counts_every_record_beneath_it(tmp_path):
    lib = library(
        tmp_path / "lib",
        tags={"ai/governance": "", "ai/evaluation": ""},
        records={
            "a": {"slug": "a", "tags": ["ai/governance"]},
            "b": {"slug": "b", "tags": ["ai/evaluation"]},
        },
    )
    assert counts(survey(lib))["ai"] == 2


def test_a_declared_tag_nothing_uses_is_still_reported(tmp_path):
    """Otherwise an unused vocabulary entry looks identical to one that was never written."""
    lib = library(tmp_path / "lib", tags={"unused": ""})
    assert counts(survey(lib)) == {"unused": 0}


def test_a_tag_the_vocabulary_does_not_name_is_a_finding(tmp_path):
    """The typo case. `ai-saftey` is plausible, and free text would accept it silently."""
    lib = library(
        tmp_path / "lib",
        tags={"ai-safety": ""},
        records={"r": {"slug": "r", "tags": ["ai-saftey"]}},
    )
    assert set(undeclared(lib)) == {"ai-saftey"}
    assert any(u.tag == "ai-saftey" and u.kind is Kind.UNDECLARED for u in survey(lib))


def test_untagged_counts_records_carrying_nothing(tmp_path):
    lib = library(
        tmp_path / "lib",
        tags={"t": ""},
        records={"a": {"slug": "a", "tags": ["t"]}, "b": {"slug": "b"}},
    )
    assert untagged(lib) == 1


def test_applying_a_tag_the_vocabulary_does_not_declare_is_refused(tmp_path):
    lib = library(
        tmp_path / "lib", tags={"known": ""}, records={"a": {"slug": "a", "cited_by": {"p": {}}}}
    )
    with pytest.raises(CitationsError, match=r"not in tags\.yaml"):
        apply(lib, "unknown", cited_by="p")


def test_a_bulk_write_only_touches_what_the_query_selects(tmp_path):
    lib = library(
        tmp_path / "lib",
        tags={"t": ""},
        records={
            "a": {"slug": "a", "cited_by": {"wanted": {}}},
            "b": {"slug": "b", "cited_by": {"other": {}}},
        },
    )
    changed = apply(lib, "t", cited_by="wanted")
    assert [p.stem for p in changed] == ["a"]
    b = yaml.safe_load((lib / "records" / "b.yaml").read_text())
    assert "tags" not in b


def test_applying_a_tag_twice_changes_nothing_the_second_time(tmp_path):
    lib = library(
        tmp_path / "lib", tags={"t": ""}, records={"a": {"slug": "a", "cited_by": {"p": {}}}}
    )
    assert apply(lib, "t", cited_by="p")
    assert apply(lib, "t", cited_by="p") == [], "a re-run must not rewrite every file"


def test_applying_a_tag_keeps_the_tags_already_there(tmp_path):
    lib = library(
        tmp_path / "lib",
        tags={"t": "", "keep": ""},
        records={"a": {"slug": "a", "cited_by": {"p": {}}, "tags": ["keep"]}},
    )
    apply(lib, "t", cited_by="p")
    a = yaml.safe_load((lib / "records" / "a.yaml").read_text())
    assert a["tags"] == ["keep", "t"]


def test_removing_the_last_tag_drops_the_field_rather_than_leaving_it_empty(tmp_path):
    lib = library(
        tmp_path / "lib",
        tags={"t": ""},
        records={"a": {"slug": "a", "cited_by": {"p": {}}, "tags": ["t"]}},
    )
    apply(lib, "t", cited_by="p", remove=True)
    assert "tags" not in yaml.safe_load((lib / "records" / "a.yaml").read_text())


def test_an_undeclared_tag_can_still_be_removed(tmp_path):
    """Removal is the repair for a bulk write. Refusing it for the tags that need repairing
    most would leave 384 files to fix by hand."""
    lib = library(
        tmp_path / "lib",
        tags={},
        records={"a": {"slug": "a", "cited_by": {"p": {}}, "tags": ["typo"]}},
    )
    assert apply(lib, "typo", cited_by="p", remove=True)
    assert undeclared(lib) == {}


def test_a_bulk_write_leaves_every_other_value_as_it_parsed(tmp_path):
    body = {"slug": "a", "year": "2016", "arxiv": "1606.03137", "cited_by": {"p": {}}}
    lib = library(tmp_path / "lib", tags={"t": ""}, records={"a": body})
    apply(lib, "t", cited_by="p")
    after = yaml.safe_load((lib / "records" / "a.yaml").read_text())
    assert after["year"] == "2016" and after["arxiv"] == "1606.03137"


def test_the_subcommand_is_reachable_from_the_top_level_command(tmp_path, capsys):
    """The seam. Every function above can be right while `citations tags` is not a command."""
    from citations import cli

    lib = library(
        tmp_path / "lib",
        tags={"ai/governance": "policy instruments"},
        records={"a": {"slug": "a", "tags": ["ai/governance"]}},
    )
    assert cli.main(["tags", "--library", str(lib)]) == 0
    assert "ai/governance" in capsys.readouterr().out


def test_the_command_fails_where_a_record_uses_a_tag_nothing_declares(tmp_path, capsys):
    from citations import cli

    lib = library(tmp_path / "lib", tags={"ai": ""}, records={"a": {"slug": "a", "tags": ["ia"]}})
    assert cli.main(["tags", "--library", str(lib)]) == 1
    assert "no vocabulary declares" in capsys.readouterr().out


def test_a_bulk_write_with_no_query_refuses_rather_than_tagging_everything(tmp_path, capsys):
    from citations import cli

    lib = library(
        tmp_path / "lib", tags={"t": ""}, records={"a": {"slug": "a", "cited_by": {"p": {}}}}
    )
    assert cli.main(["tags", "--library", str(lib), "--add", "t"]) == 2
    assert "tags" not in yaml.safe_load((lib / "records" / "a.yaml").read_text())
    assert "need a query" in capsys.readouterr().out


def test_a_record_model_carries_its_tags(tmp_path):
    """`Record` validates every record before anything else reads one, so a field it does not
    know is a field the rest of the package cannot see."""
    from citations.models import load_record

    lib = library(tmp_path / "lib", records={"a": {"slug": "a", "tags": ["x"]}})
    assert load_record(lib / "records" / "a.yaml").tags == ["x"]


def test_a_namespace_is_not_reported_as_a_tag_nothing_declares(tmp_path):
    """`ai-safety` is a level implied by `ai-safety/governance`, not a missing declaration.
    Read as undeclared it puts a finding on every parent, and the report cries wolf on its
    own tree."""
    lib = library(
        tmp_path / "lib",
        tags={"ai-safety/governance": ""},
        records={"a": {"slug": "a", "tags": ["ai-safety/governance"]}},
    )
    found = {u.tag: u.kind for u in survey(lib)}
    assert found["ai-safety"] is Kind.NAMESPACE
    assert found["ai-safety/governance"] is Kind.DECLARED
    assert undeclared(lib) == {}


def test_a_record_carrying_a_bare_namespace_is_still_a_finding(tmp_path):
    """A namespace is not applicable: only a declared name may go on a record."""
    lib = library(
        tmp_path / "lib",
        tags={"ai-safety/governance": ""},
        records={"a": {"slug": "a", "tags": ["ai-safety"]}},
    )
    assert set(undeclared(lib)) == {"ai-safety"}
