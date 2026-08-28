"""A quotation and a characterization of it are different objects, and only one is measured.

`verify` resolves the strings in `quotes` against the pinned bytes and never reads the
statement built on them. A file whose quotation is exact and whose characterization
overreaches therefore passes every check, which is the failure this block exists to make
visible rather than to prevent.
"""

from __future__ import annotations

import pytest
from citations import cli
from citations.models import Claim, Interpretation
from pydantic import ValidationError

PASSAGE = "in conjunction with a long-range autonomy capability"


def claims_dir(tmp_path, body):
    source = tmp_path / "framework.txt"
    source.write_text(
        "Associated risk of severe harm: " + PASSAGE + ", models could bypass safeguards.\n"
        "Risk-specific safeguard guidelines: require security controls meeting High standard.\n"
    )
    d = tmp_path / "claims"
    d.mkdir()
    (d / "framework.yaml").write_text(
        "source:\n"
        "  citation: framework\n"
        "  local: framework.txt\n"
        "  extract_cmd: cat\n"
        "claims:\n" + body
    )
    return d


def test_a_characterization_needs_an_owner():
    with pytest.raises(ValidationError):
        Interpretation(says="the obligation is conditioned on autonomy")


def test_a_file_written_before_interpretations_still_parses():
    claim = Claim(statement="the obligation is conditioned on autonomy", verified=True)
    assert claim.interpretation is None
    assert claim.statement


def test_the_reading_is_reported_apart_from_the_quotation(tmp_path, capsys):
    body = (
        "  autonomy:\n"
        "    interpretation:\n"
        "      says: The safeguard obligation is conditioned on long-range autonomy.\n"
        "      whose: systemcard\n"
        "      status: contested\n"
        "      contest: The phrase sits in the column describing risks.\n"
        "    quotes:\n"
        f"    - exact: {PASSAGE}\n"
    )
    cli.main(["verify", "--claims", str(claims_dir(tmp_path, body)), "--allow-extractor", "cat"])
    out = capsys.readouterr().out
    assert "found" in out
    assert "readings" in out
    assert "does not measure" in out
    assert "attributed to a party other than the source" in out
    assert "contested" in out


def test_a_reading_owned_by_the_source_is_not_flagged_as_foreign(tmp_path, capsys):
    body = (
        "  autonomy:\n"
        "    interpretation:\n"
        "      says: The framework describes a loss-of-oversight risk.\n"
        "      whose: framework\n"
        "    quotes:\n"
        f"    - exact: {PASSAGE}\n"
    )
    cli.main(["verify", "--claims", str(claims_dir(tmp_path, body)), "--allow-extractor", "cat"])
    out = capsys.readouterr().out
    assert "readings" in out
    assert "attributed to a party other than the source" not in out


def test_an_exact_quotation_does_not_make_the_reading_checked(tmp_path, capsys):
    """The whole point: the run is clean and the characterization is still unmeasured."""
    body = (
        "  autonomy:\n"
        "    interpretation:\n"
        "      says: Something the source does not say at all.\n"
        "      whose: ours\n"
        "    quotes:\n"
        f"    - exact: {PASSAGE}\n"
    )
    cli.main(["verify", "--claims", str(claims_dir(tmp_path, body)), "--allow-extractor", "cat"])
    out = capsys.readouterr().out
    assert "all found" in out
    assert "unchecked; this package does not measure them" in out
