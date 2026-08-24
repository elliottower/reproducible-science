"""Two spellings of one name have to compare equal, and two names must not.

There were two folding implementations. `audit.fold` resolved Kästner to `kastner`;
`services.norm` deleted the accented letter and produced `kstner`. The second gated identifier
lookup, so a correct paper was rejected for any author with an accent in their surname.
"""

from __future__ import annotations

from citations.text import expand, fold, surname, surname_variants, tokens, variants


def test_an_accent_resolves_to_its_letter_rather_than_vanishing():
    for accented, plain in [
        ("Kästner", "kastner"),
        ("Munafò", "munafo"),
        ("Alchourrón", "alchourron"),
        ("Räuker", "rauker"),
    ]:
        assert fold(accented) == plain


def test_the_german_expansion_is_also_produced():
    assert expand("Kästner") == "kaestner"
    assert expand("Hölscher-Obermaier") == "hoelscher obermaier"
    assert expand("Weiß") == "weiss"


def test_both_spellings_of_one_name_share_a_variant():
    # A record writes Hölscher-Obermaier; Crossref deposits Hoelscher-Obermaier.
    assert surname_variants("Hölscher-Obermaier, Jason") & surname_variants(
        "Hoelscher-Obermaier, J"
    )


def test_two_different_names_share_no_variant():
    assert not (surname_variants("Kästner, Lena") & surname_variants("Crook, Barnaby"))


def test_a_latex_accent_matches_the_unicode_it_encodes():
    assert tokens("Munaf{\\'o}") == tokens("Munafò") == ("munafo",)
    assert tokens("Gon{\\c{c}}alves") == tokens("Gonçalves") == ("goncalves",)


def test_markup_a_registry_deposited_is_not_part_of_the_title():
    # Crossref stores italics as tags and sometimes escapes them twice.
    assert fold("Effect of statins on &amp;lt;i&amp;gt;LDLR&amp;lt;/i&amp;gt; expression") == fold(
        "Effect of statins on LDLR expression"
    )


def test_a_surname_is_read_out_of_either_name_order():
    assert surname("Vaswani, Ashish") == surname("Ashish Vaswani") == "vaswani"


def test_empty_input_produces_no_variants():
    assert variants("") == frozenset()
    assert surname_variants("") == frozenset()


def test_a_hyphenated_name_is_two_tokens_and_an_accent_is_none():
    assert tokens("Glade-Bender") == tokens("Glade Bender") == ("glade", "bender")
