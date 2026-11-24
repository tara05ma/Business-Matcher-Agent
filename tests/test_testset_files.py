"""Checks on the files written by scripts/select_test_set.py.

These read the two JSONL files only, so they are fast and need no database.
They are skipped until the test set has been generated.
"""
import json
from pathlib import Path

import pytest

TESTSET = Path(__file__).parent.parent / "data" / "testset"
ANSWER_FIELDS = {"expected_dos_id", "register_name", "distortion", "variant",
                 "ideal_outcome", "notes"}

if not (TESTSET / "specs.jsonl").exists():
    pytest.skip("test set not generated yet", allow_module_level=True)


def _load(name):
    with open(TESTSET / name, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


specs = _load("specs.jsonl")
answers = _load("answers.jsonl")
answer_for = {a["doc"]: a for a in answers}


def test_both_files_list_the_same_50_documents():
    spec_docs = [s["doc"] for s in specs]
    assert len(spec_docs) == len(set(spec_docs)) == 50
    assert set(spec_docs) == set(answer_for)


def test_specs_never_contain_the_answers():
    for s in specs:
        assert not ANSWER_FIELDS & s.keys(), s["doc"]
        dos_id = answer_for[s["doc"]]["expected_dos_id"]
        if dos_id:
            assert dos_id not in json.dumps(s), s["doc"]


def test_outcome_counts_match_the_plan():
    outcomes = [a["ideal_outcome"] for a in answers]
    assert outcomes.count("match") == 36
    assert outcomes.count("abstain") == 14


def test_every_match_has_a_company_and_every_fake_has_none():
    for a in answers:
        if a["ideal_outcome"] == "match":
            assert a["expected_dos_id"], a["doc"]
        if a["distortion"] == "does_not_exist":
            assert a["expected_dos_id"] is None, a["doc"]


def test_must_include_and_must_not_contain_agree():
    for s in specs:
        assert s["client_name"] in s["must_include"], s["doc"]
        for banned in s["must_not_contain"]:
            assert not any(banned in text for text in s["must_include"]), s["doc"]
