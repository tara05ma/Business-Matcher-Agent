import random

import pytest

from business_matcher_agent import distortions as d
from business_matcher_agent.normalize import normalize_name


def rng():
    return random.Random(0)


def test_split_suffix():
    assert d.split_suffix("FARWAY MARINA, INC.") == ("FARWAY MARINA", "INC.")
    assert d.split_suffix("101 GILA REALTY, L.L.C.") == ("101 GILA REALTY", "L.L.C.")
    assert d.split_suffix("ABC CO., INC.") == ("ABC", "CO., INC.")
    assert d.split_suffix("SMITH & CO.") == ("SMITH", "& CO.")
    assert d.split_suffix("NO SUFFIX HERE") == ("NO SUFFIX HERE", "")
    assert d.split_suffix("THE COMPANY") == ("THE COMPANY", "")  # nothing left: keep it whole


def test_drop_suffix_matches_what_search_compares():
    assert d.drop_suffix("FARWAY MARINA, INC.") == "FARWAY MARINA"
    assert normalize_name(d.drop_suffix("SMITH & CO.")) == normalize_name("SMITH & CO.")


def test_change_suffix_switches_the_legal_form():
    assert d.change_suffix("101 GILA REALTY, LLC") == "101 GILA REALTY INC."
    assert d.change_suffix("FARWAY MARINA INC.") == "FARWAY MARINA LLC"


def test_legal_form():
    assert d.legal_form("101 GILA REALTY, L.L.C.") == "llc"
    assert d.legal_form("FARWAY MARINA INC.") == d.legal_form("FARWAY MARINA INCORPORATED") == "corporation"
    assert d.legal_form("ABC CO., INC.") == "corporation"
    assert d.legal_form("SMITH & CO.") is None  # "Co" alone doesn't say which form
    assert d.legal_form("NO SUFFIX HERE") is None


def test_abbreviate_shortens_one_listed_word():
    assert d.abbreviate("SMITH BROTHERS PLUMBING INC.", rng()) == "SMITH BROS PLUMBING INC."
    assert d.abbreviate("Acme Management LLC", rng()) == "Acme Mgmt LLC"
    assert d.abbreviate("FARWAY MARINA INC.", rng()) is None


def test_typos_change_the_base_but_not_the_suffix():
    for seed in range(20):
        typo = d.add_typos("FARWAY MARINA INC.", random.Random(seed), count=2)
        assert typo.endswith(" INC.")
        assert typo != "FARWAY MARINA INC."


def test_two_typos_never_cancel_out():
    # Before the fix, a second typo could undo the first (164 of 20,000 seeds).
    for seed in range(2000):
        for name in ["FARWAY MARINA INC.", "AB BB LLC", "Golden Nature Inc."]:
            assert d.add_typos(name, random.Random(seed), count=2) != name


def test_typos_need_letters():
    with pytest.raises(ValueError):
        d.add_typos("1010 LLC", rng())
    with pytest.raises(ValueError):
        d.add_typos("AB LLC", rng(), count=2)  # no two letters are far enough apart


def test_suffix_glued_on_without_a_space_is_not_split():
    # Known limit: search cleans "ABC,INC." to "abc", but split_suffix keeps it
    # whole. The test-set script only uses names where a suffix was found.
    assert d.split_suffix("ABC,INC.") == ("ABC,INC.", "")
    assert normalize_name("ABC,INC.") == "abc"


def test_replace_word_swaps_a_whole_word():
    fake = d.replace_word("ATLANTIC TILE WORKS LLC", rng())
    assert fake.startswith("ATLANTIC ")  # the first word is kept
    assert fake.endswith(" LLC")
    assert len(fake.split()) == 4
    assert fake != "ATLANTIC TILE WORKS LLC"
    assert d.replace_word("123 45 LLC", rng()) is None
    assert d.replace_word("COPPER LLC", rng()) is None  # no later word to swap


def test_same_seed_same_result():
    assert d.add_typos("GOLDEN NATURE INC.", random.Random(7)) == \
        d.add_typos("GOLDEN NATURE INC.", random.Random(7))
    assert d.invent_name(random.Random(7)) == d.invent_name(random.Random(7))
