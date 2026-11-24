import pytest
from pydantic import ValidationError

from business_matcher_agent.models import MatchResult

MATCH = {
    "status": "matched",
    "dos_id": "4424185",
    "matched_name": "BUTCHY'S WINE & SPIRITS, INC.",
    "confidence": 0.93,
    "candidates_considered": ["4424185", "5123456"],
    "evidence": "Name matches after removing 'Inc.'; city matches Mount Vernon",
    "model_used": "claude-haiku-5-5",
    "steps_taken": 4,
}
UNMATCHED = {
    "status": "unmatched",
    "confidence": 0.4,
    "candidates_considered": ["3644104", "4202084"],
    "evidence": "Two Division Realty companies; nothing in the document tells them apart",
    "model_used": "claude-haiku-5-5",
    "steps_taken": 3,
}


def test_the_brief_example_is_valid():
    result = MatchResult(**MATCH)
    assert result.model_dump() == MATCH


def test_unmatched_leaves_the_company_empty_but_lists_candidates():
    result = MatchResult(**UNMATCHED)
    assert result.dos_id is None and result.matched_name is None
    assert result.candidates_considered == ["3644104", "4202084"]


@pytest.mark.parametrize("change", [
    {"dos_id": None},                         # matched, but no company
    {"matched_name": None},                   # matched, but no name
    {"dos_id": "9999999"},                    # match not among the candidates
    {"dos_id": "44-24185"},                   # not digits
    {"candidates_considered": ["4424185", "abc"]},
    {"confidence": 1.2},
    {"confidence": -0.1},
    {"status": "maybe"},
    {"evidence": ""},
    {"steps_taken": -1},
    {"confidance": 0.9},                      # misspelled field name
])
def test_bad_matches_are_rejected(change):
    with pytest.raises(ValidationError):
        MatchResult(**(MATCH | change))


def test_unmatched_with_a_company_is_rejected():
    with pytest.raises(ValidationError):
        MatchResult(**(UNMATCHED | {"dos_id": "3644104"}))
