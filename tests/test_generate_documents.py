"""Tests for the parts of generate_documents.py that don't call the API."""
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "scripts" / "generate_documents.py"
_spec = importlib.util.spec_from_file_location("generate_documents", SCRIPT)
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)

TYPO = {
    "doc": "doc_001.txt", "doc_type": "insurer_email",
    "client_name": "30 SOUTH FOUTX LLC", "legal_name_small_print": None,
    "address_line": None, "city": "Brooklyn", "zip": "11211", "contact": None,
    "insurer": "Northlantern Mutual Insurance Company",
    "certificate_holder": "Silver Plaza Owners LLC",
    "must_include": ["30 SOUTH FOUTX LLC", "Brooklyn",
                     "Northlantern Mutual Insurance Company", "Silver Plaza Owners LLC"],
    "must_not_contain": ["30 SOUTH FOURTH"],
}
GOOD = ("From: claims@northlantern.example\nRe: 30 South Foutx, LLC - renewal\n"
        "Insured is in BROOKLYN, NY 11211. Northlantern Mutual Insurance Company. "
        "Cert holder: Silver Plaza Owners, LLC")


def test_a_good_document_passes():
    assert gen.check_document(GOOD, TYPO) == []


def test_corrected_typo_is_caught_both_ways():
    fixed = GOOD.replace("Foutx", "Fourth")
    problems = gen.check_document(fixed, TYPO)
    assert any("missing required" in p for p in problems)
    assert any("forbidden" in p for p in problems)


def test_forbidden_string_is_caught_despite_case_and_punctuation():
    spec = TYPO | {"must_not_contain": ["EVER AFTER BABY LLC"]}
    assert gen.check_document(GOOD + "\nEver After Baby, L.L.C.", spec)
    assert gen.check_document(GOOD + "\never after baby llc", spec)


def test_forbidden_string_must_be_whole_words():
    spec = TYPO | {"must_not_contain": ["ACME"]}
    assert gen.check_document(GOOD + " ACMEWORKS", spec) == []


def test_prompt_has_the_facts_but_no_answers():
    prompt = gen.build_prompt(TYPO)
    for s in TYPO["must_include"] + TYPO["must_not_contain"]:
        assert s in prompt
    assert "dos" not in prompt.lower()
    assert "Do not give one" not in prompt  # a city is known


def test_prompt_forbids_an_address_when_none_is_known():
    spec = TYPO | {"city": None, "zip": None}
    assert "Do not give one" in gen.build_prompt(spec)


def test_small_print_instruction_only_when_there_is_a_legal_name():
    assert "small print" not in gen.build_prompt(TYPO)
    spec = TYPO | {"legal_name_small_print": "NEW 8 COREY LLC"}
    assert "NEW 8 COREY LLC" in gen.build_prompt(spec)
    assert "small print" in gen.build_prompt(spec)


def test_no_known_contact_means_no_invented_person_at_the_client():
    assert "Do not name anyone who works for the client" in gen.build_prompt(TYPO)
    spec = TYPO | {"contact": "LORENZO MARIN"}
    prompt = gen.build_prompt(spec)
    assert "LORENZO MARIN" in prompt
    assert "Do not name anyone who works for the client" not in prompt


def test_each_document_gets_a_fixed_broker_from_the_list():
    brokers = {gen.broker_for(TYPO | {"doc": f"doc_{n:03}.txt"}) for n in range(1, 51)}
    assert brokers == set(gen.BROKERS)  # all four are used
    assert gen.broker_for(TYPO) == gen.broker_for(TYPO)
    assert gen.broker_for(TYPO) in gen.build_prompt(TYPO)


def test_code_fences_are_removed():
    assert gen._clean("```\nhello\n```") == "hello\n"
    assert gen._clean("```text\nhello\n```\n") == "hello\n"
