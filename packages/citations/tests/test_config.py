"""Which papers cite into a library is configuration, not code.

It was a dict of absolute paths inside build.py, so the package worked on one machine.
"""

from __future__ import annotations

import pytest
from citations import config
from citations.config import LibraryConfig, PaperConfig
from citations.exceptions import ClaimFileError


def test_a_library_with_no_config_reads_as_no_papers(tmp_path):
    assert config.load(tmp_path).papers == {}


def test_a_config_round_trips(tmp_path):
    cfg = LibraryConfig(
        papers={"my-paper": PaperConfig(bib=tmp_path / "refs.bib", claims=tmp_path / "claims")}
    )
    config.save(cfg, tmp_path)
    back = config.load(tmp_path)
    assert set(back.papers) == {"my-paper"}
    assert back.papers["my-paper"].resolved("bib", tmp_path) == tmp_path / "refs.bib"


def test_a_relative_path_resolves_against_the_library(tmp_path):
    paper = PaperConfig(bib="papers/refs.bib")
    assert paper.resolved("bib", tmp_path) == (tmp_path / "papers/refs.bib").resolve()


def test_an_unconfigured_field_resolves_to_nothing(tmp_path):
    assert PaperConfig(bib="x.bib").resolved("claims", tmp_path) is None


def test_malformed_yaml_names_the_file_rather_than_raising_from_the_parser(tmp_path):
    (tmp_path / config.CONFIG_NAME).write_text("papers:\n  - this is a list not a mapping\n")
    with pytest.raises(ClaimFileError) as e:
        config.load(tmp_path)
    assert config.CONFIG_NAME in str(e.value)
