"""Tests against the real Kings register. Run scripts/load_db.py first."""
import pytest

from business_matcher_agent.tools import DB_PATH, get_business, search_business

pytestmark = pytest.mark.skipif(not DB_PATH.exists(), reason="register.db not loaded")

FARWAY = "1562916"


def top_ids(results, n=5):
    return [c["dos_id"] for c in results[:n]]


# --- get_business -------------------------------------------------------------

def test_get_business_returns_every_field():
    company = get_business(FARWAY)
    assert company["Current Entity Name"] == "FARWAY MARINA INC."
    assert "CEO Address 1" in company  # nothing is left out


def test_get_business_unknown_or_bad_id():
    assert get_business("999999999") is None
    assert get_business("1562916; DROP TABLE companies") is None
    assert get_business(" 1562916 ")["DOS ID"] == FARWAY  # stray spaces are fine


# --- search_business ------------------------------------------------------------

def test_exact_name_ranks_first():
    assert search_business("FARWAY MARINA INC.")[0]["dos_id"] == FARWAY


def test_suffix_dropped_still_found():
    assert FARWAY in top_ids(search_business("Farway Marina"))


def test_typo_still_found():
    # The brief's day-2 checkpoint: a misspelled name returns the right company in the top 5.
    assert FARWAY in top_ids(search_business("Farway Marena"))


def test_near_duplicates_both_returned():
    ids = top_ids(search_business("101 Gila Realty"))
    assert {"2599798", "2896947"} <= set(ids)  # the Inc. and the LLC


def test_made_up_name_scores_low():
    assert search_business("Zxqv Unicorn Holdings")[0]["name_score"] < 85


def test_clues_add_flags_but_never_remove_candidates():
    plain = search_business("Farway Marena")
    with_clues = search_business(
        "Farway Marena", city="Atlantic Beach", zip="11509",
        street="1790 Bay Blvd", person="Harold Glantz",
    )
    assert set(top_ids(plain, 10)) == set(top_ids(with_clues, 10))
    farway = next(c for c in with_clues if c["dos_id"] == FARWAY)
    assert farway["matches"] == {"city": True, "zip": True, "street": True, "person": True}


def test_typo_in_first_letter_of_a_word_still_found():
    # The typo changes the alphabetical word order, which sinks token_sort_ratio alone.
    results = search_business("HERON BEAL ESTATE CORP.")
    assert any(c["name"] == "HERON REAL ESTATE CORP." for c in results[:5])


def test_differently_written_clues_still_match():
    farway = next(
        c for c in search_business(
            "Farway Marina", city="Atlantic Beach, NY",
            street="1790 Bay Boulevard, Suite 2", person="Glantz, Harold, Esq.",
        ) if c["dos_id"] == FARWAY
    )
    assert farway["matches"]["city"] is True
    assert farway["matches"]["street"] is True
    assert farway["matches"]["person"] is True


def test_wrong_clues_are_still_flagged_false():
    farway = next(
        c for c in search_business(
            "Farway Marina", city="Buffalo", street="1 Other St", person="Jane Doe",
        ) if c["dos_id"] == FARWAY
    )
    assert farway["matches"]["city"] is False
    assert farway["matches"]["street"] is False
    assert farway["matches"]["person"] is False


def test_missing_clue_is_no_evidence():
    farway = search_business("Farway Marina")[0]
    assert farway["matches"]["zip"] is None


def test_empty_name_returns_nothing():
    assert search_business("") == []


def test_unrelated_name_returns_nothing():
    assert search_business("Qqqqzzzz Xyxyxy") == []


def test_every_result_meets_the_minimum_score():
    assert all(c["name_score"] >= 60 for c in search_business("Zxqv Unicorn Holdings"))