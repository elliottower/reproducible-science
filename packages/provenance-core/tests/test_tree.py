"""A dataset is a directory, and its digest has to mean the same thing on two machines.

The failure this exists to prevent is a seal that looks complete: files enumerated by hand, one
added afterwards, and nothing to notice. The failures these tests guard are the ones a tree
digest invents on its own -- an order the filesystem chose, a rename that changes nothing, a
stray editor file that makes two checkouts of one dataset disagree.
"""

from __future__ import annotations

import pytest

from provenance_core.digests import NOISE, sha256_of_file, sha256_of_tree


def build(root, files: dict[str, str]):
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return root


DATA = {
    "raw/one.csv": "a,b\n1,2\n",
    "raw/two.csv": "a,b\n3,4\n",
    "notes.md": "about the data\n",
}


def test_the_same_tree_hashes_the_same_twice(tmp_path):
    a = build(tmp_path / "a", dict(DATA))
    assert sha256_of_tree(a)[0] == sha256_of_tree(a)[0]


def test_two_trees_with_identical_contents_agree(tmp_path):
    a = build(tmp_path / "a", dict(DATA))
    b = build(tmp_path / "b", dict(DATA))
    assert sha256_of_tree(a)[0] == sha256_of_tree(b)[0]


def test_a_changed_byte_changes_the_digest(tmp_path):
    a = build(tmp_path / "a", dict(DATA))
    before = sha256_of_tree(a)[0]
    (a / "raw/one.csv").write_text("a,b\n1,3\n")
    assert sha256_of_tree(a)[0] != before


def test_a_file_added_afterwards_changes_the_digest(tmp_path):
    """The whole point: hand-enumeration cannot see this, and a tree digest must."""
    a = build(tmp_path / "a", dict(DATA))
    before = sha256_of_tree(a)[0]
    (a / "raw/three.csv").write_text("a,b\n5,6\n")
    assert sha256_of_tree(a)[0] != before


def test_a_removed_file_changes_the_digest(tmp_path):
    a = build(tmp_path / "a", dict(DATA))
    before = sha256_of_tree(a)[0]
    (a / "notes.md").unlink()
    assert sha256_of_tree(a)[0] != before


def test_a_rename_changes_the_digest_though_the_bytes_did_not(tmp_path):
    """A set of bytes is not the same dataset once its labels are reshuffled."""
    a = build(tmp_path / "a", dict(DATA))
    before = sha256_of_tree(a)[0]
    (a / "raw/one.csv").rename(a / "raw/uno.csv")
    assert sha256_of_tree(a)[0] != before


def test_swapping_two_files_contents_changes_the_digest(tmp_path):
    """Contents-only hashing would call this identical, because the multiset is unchanged."""
    a = build(tmp_path / "a", dict(DATA))
    before = sha256_of_tree(a)[0]
    one, two = (a / "raw/one.csv").read_text(), (a / "raw/two.csv").read_text()
    (a / "raw/one.csv").write_text(two)
    (a / "raw/two.csv").write_text(one)
    assert sha256_of_tree(a)[0] != before


def test_a_path_boundary_cannot_be_forged(tmp_path):
    """Without a length prefix, `ab`+`c` and `a`+`bc` would hash alike."""
    a = build(tmp_path / "a", {"ab": "x", "c": "y"})
    b = build(tmp_path / "b", {"a": "x", "bc": "y"})
    assert sha256_of_tree(a)[0] != sha256_of_tree(b)[0]


def test_noise_is_skipped_and_reported_rather_than_hashed(tmp_path):
    a = build(tmp_path / "a", dict(DATA))
    clean = sha256_of_tree(a)[0]
    (a / ".DS_Store").write_bytes(b"\x00\x01")
    digest, covered, skipped = sha256_of_tree(a)
    assert digest == clean, "a stray editor file must not make two checkouts disagree"
    assert ".DS_Store" in skipped, "and it must not be skipped in silence"
    assert all(".DS_Store" not in rel for rel, _ in covered)


def test_what_it_covered_is_returned_so_a_seal_can_record_it(tmp_path):
    a = build(tmp_path / "a", dict(DATA))
    _, covered, _ = sha256_of_tree(a)
    assert sorted(rel for rel, _ in covered) == sorted(DATA)
    for rel, digest in covered:
        assert digest == sha256_of_file(a / rel)


def test_an_empty_directory_contributes_nothing(tmp_path):
    a = build(tmp_path / "a", dict(DATA))
    before = sha256_of_tree(a)[0]
    (a / "raw" / "empty").mkdir()
    assert sha256_of_tree(a)[0] == before


def test_a_symlink_is_skipped_and_named(tmp_path):
    """Following it would put bytes from outside under a digest that claims the tree."""
    outside = tmp_path / "outside.csv"
    outside.write_text("x\n")
    a = build(tmp_path / "a", dict(DATA))
    (a / "link.csv").symlink_to(outside)
    _, covered, skipped = sha256_of_tree(a)
    assert "link.csv" in skipped
    assert all(rel != "link.csv" for rel, _ in covered)


def test_the_skip_set_is_a_parameter_not_a_rule(tmp_path):
    a = build(tmp_path / "a", dict(DATA))
    _, covered, _ = sha256_of_tree(a, skip=frozenset())
    assert len(covered) == len(DATA)
    assert NOISE, "the default is a set, and the caller may replace it"


def test_an_empty_tree_has_a_digest_rather_than_an_error(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    digest, covered, skipped = sha256_of_tree(empty)
    assert len(digest) == 64
    assert covered == [] and skipped == []


@pytest.mark.parametrize("depth", [1, 3, 6])
def test_nesting_depth_does_not_matter(tmp_path, depth):
    rel = "/".join(f"d{i}" for i in range(depth)) + "/f.csv"
    a = build(tmp_path / f"a{depth}", {rel: "x\n"})
    digest, covered, _ = sha256_of_tree(a)
    assert [r for r, _ in covered] == [rel]
    assert len(digest) == 64
