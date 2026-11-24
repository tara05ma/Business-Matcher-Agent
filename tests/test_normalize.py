from business_matcher_agent.normalize import (
    normalize_address,
    normalize_city,
    normalize_name,
    normalize_person,
)


# --- normalize_name ---------------------------------------------------------

def test_name_strips_case_punctuation_and_suffix():
    assert normalize_name("FARWAY MARINA INC.") == "farway marina"
    assert normalize_name("Farway Marina") == "farway marina"


def test_name_strips_dotted_and_repeated_suffixes():
    assert normalize_name("101 GILA REALTY, L.L.C.") == "101 gila realty"
    assert normalize_name("ABC Co., Inc.") == "abc"


def test_name_turns_ampersand_into_and():
    assert normalize_name("J & V LLC") == normalize_name("J and V LLC") == "j and v"


def test_name_keeps_suffix_words_in_the_middle():
    assert normalize_name("COMPANY STORE LLC") == "company store"


def test_name_that_is_only_a_suffix_is_kept_whole():
    assert normalize_name("THE COMPANY") == "the company"


def test_name_empty():
    assert normalize_name(None) == ""
    assert normalize_name("   ") == ""


def test_name_drops_and_left_before_a_suffix():
    assert normalize_name("Smith & Co") == normalize_name("SMITH AND COMPANY") == "smith"
    assert normalize_name("Smith & Sons Inc") == "smith and sons"  # a middle "and" stays


def test_name_apostrophes_do_not_split_words():
    assert normalize_name("Joe's Pizza") == normalize_name("Joes Pizza") == "joes pizza"
    assert normalize_name("Joe’s Pizza") == "joes pizza"  # curly apostrophe


# --- normalize_person and normalize_city -------------------------------------

def test_person_ignores_order_titles_and_initials():
    expected = normalize_person("HAROLD GLANTZ")
    assert normalize_person("Glantz, Harold") == expected
    assert normalize_person("Harold Glantz, Esq.") == expected
    assert normalize_person("Mr. Harold J. Glantz") == expected


def test_person_keeps_jr_because_it_can_be_a_different_person():
    assert normalize_person("John Smith Jr") != normalize_person("John Smith")


def test_person_with_only_a_title_is_empty():
    assert normalize_person("Esq.") == ""


def test_city_ignores_state():
    assert normalize_city("Atlantic Beach, NY") == "ATLANTIC BEACH"
    assert normalize_city("Brooklyn NY") == "BROOKLYN"
    assert normalize_city("New York, NY") == "NEW YORK"
    assert normalize_city(None) == ""


# --- normalize_address -------------------------------------------------------

def test_address_street_spellings_match():
    a = normalize_address("28 LIBERTY ST.")
    b = normalize_address("28 Liberty Street")
    assert a["standard"] == b["standard"] == "28 LIBERTY ST"


def test_address_drops_suite():
    assert normalize_address("28 Liberty Street, Suite 4400")["standard"] == "28 LIBERTY ST"


def test_address_parts():
    result = normalize_address("1790 Bay Blvd., Atlantic Beach NY 11509")
    assert result["street_number"] == "1790"
    assert result["street_name"] == "BAY BLVD"
    assert result["zip"] == "11509"


def test_address_empty():
    assert normalize_address("") is None
    assert normalize_address(None) is None


def test_address_five_digit_house_number_is_not_a_zip():
    result = normalize_address("12345 Bay Parkway, Brooklyn, NY 11204")
    assert result["street_number"] == "12345"
    assert result["zip"] == "11204"

    no_zip = normalize_address("11201 Main Street")
    assert no_zip["street_number"] == "11201"
    assert no_zip["zip"] is None


def test_address_unit_before_the_street():
    assert normalize_address("Suite 200, 100 Main St")["standard"] == "100 MAIN ST"
    assert normalize_address("2nd Floor, 100 Main St")["standard"] == "100 MAIN ST"


def test_address_floor_written_number_first():
    assert normalize_address("123 Main St 2nd Floor")["standard"] == "123 MAIN ST"
    assert normalize_address("546 Fifth Avenue, 6th Floor")["standard"] == "546 FIFTH AVE"


def test_address_unit_joined_to_its_number():
    assert normalize_address("7014 13th Ave Suite210")["standard"] == "7014 13TH AVE"


def test_address_ordinal_street_name_is_kept():
    assert normalize_address("123 5th Fl")["street_name"] == "5TH"


def test_address_po_box_keeps_its_number():
    for spelling in ("PO BOX 80374", "P.O. Box 80374", "POB 80374"):
        result = normalize_address(spelling)
        assert result["standard"] == "PO BOX 80374"
        assert result["zip"] is None


def test_address_unit_number_is_not_a_zip():
    for address in ("2109 Broadway Unit 11131", "1205 Atlantic Ave Ste 16053", "1732 1st Ave #21319"):
        assert normalize_address(address)["zip"] is None


def test_address_florida_zip_is_still_a_zip():
    assert normalize_address("100 Main St, Miami FL 33101")["zip"] == "33101"