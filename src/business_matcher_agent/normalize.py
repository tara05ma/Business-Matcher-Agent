"""Turn names and addresses into a standard form so they can be compared fairly.

Nothing here changes the register. These functions only produce cleaned copies
that are used for comparing.
"""
import json
import re
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Company names
# ---------------------------------------------------------------------------

# Legal suffixes, taken from the most common last words in the Kings register.
NAME_SUFFIXES = {
    "llc", "inc", "incorporated", "corp", "corporation", "ltd", "limited",
    "pllc", "pc", "co", "company", "lp", "llp", "dpc",
}


def normalize_name(name: str | None) -> str:
    """Clean a company name for comparison.

    "FARWAY MARINA, INC." -> "farway marina"
    "J & V Co., Inc."     -> "j and v"
    "Joe's Pizza & Co."   -> "joes pizza"
    """
    if not name:
        return ""
    text = name.lower()
    text = re.sub(r"[.'’]", "", text)      # l.l.c. -> llc, joe's -> joes
    text = text.replace("&", " and ")
    text = re.sub(r"[^\w\s]", " ", text)   # other punctuation -> space
    words = text.split()                    # also collapses extra spaces

    # Strip legal suffixes from the end only, repeatedly ("abc co inc" -> "abc").
    # An "and" left just before a suffix goes too ("smith and co" -> "smith").
    cleaned = list(words)
    while cleaned and cleaned[-1] in NAME_SUFFIXES:
        cleaned.pop()
        if cleaned and cleaned[-1] == "and":
            cleaned.pop()

    # A name that is only a suffix ("THE COMPANY") would be left empty or as just
    # "the": keep it whole instead.
    if not cleaned or cleaned == ["the"]:
        cleaned = words
    return " ".join(cleaned)


# ---------------------------------------------------------------------------
# People and cities
# ---------------------------------------------------------------------------

# Titles and credentials don't change who someone is. JR and SR are kept on
# purpose: they can be two different people, and a false "same person" is the
# dangerous mistake.
PERSON_TITLES = {
    "MR", "MRS", "MS", "MISS", "DR", "PROF",
    "ESQ", "ESQUIRE", "CPA", "MD", "DDS", "PHD",
}


def normalize_person(name: str | None) -> str:
    """Clean a person's name so word order, titles and initials don't matter.

    "Harold Glantz, Esq." -> "GLANTZ HAROLD"
    "Glantz, Harold J."   -> "GLANTZ HAROLD"
    """
    if not name:
        return ""
    text = re.sub(r"[.'’]", "", name.upper())
    words = re.sub(r"[^\w\s]", " ", text).split()
    kept = [w for w in words if w not in PERSON_TITLES and len(w) > 1]
    return " ".join(sorted(kept))


def normalize_city(city: str | None) -> str:
    """Clean a city for comparison: "Atlantic Beach, NY" -> "ATLANTIC BEACH"."""
    if not city:
        return ""
    words = re.sub(r"[^\w\s]", " ", city.split(",")[0].upper()).split()
    if len(words) > 1 and words[-1] == "NY":  # "BROOKLYN NY" -> "BROOKLYN"
        words.pop()
    return " ".join(words)


# ---------------------------------------------------------------------------
# Addresses: layer 1, local rules (always available, offline)
# ---------------------------------------------------------------------------

# Street words -> USPS standard abbreviation, so every spelling ends up the same.
STREET_WORDS = {
    "STREET": "ST", "STR": "ST",
    "AVENUE": "AVE", "AV": "AVE", "AVN": "AVE",
    "BOULEVARD": "BLVD", "BOUL": "BLVD",
    "ROAD": "RD", "DRIVE": "DR", "PLACE": "PL", "LANE": "LN", "COURT": "CT",
    "PARKWAY": "PKWY", "HIGHWAY": "HWY", "TERRACE": "TER", "SQUARE": "SQ",
    "PLAZA": "PLZ", "EXPRESSWAY": "EXPY", "TURNPIKE": "TPKE", "CIRCLE": "CIR",
    "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W",
}

# Unit words: the word and the token after it are removed ("SUITE 202", "APT 3B").
UNIT_WORDS = {"SUITE", "STE", "APT", "APARTMENT", "UNIT", "FL", "FLOOR", "RM", "ROOM", "BLDG"}

FLOOR_WORDS = {"FL", "FLOOR"}
UNIT_WITH_NUMBER_RE = re.compile(r"^(?:SUITE|STE|APT|UNIT|FL|RM|BLDG)\d+\w*$")  # "SUITE210"
ORDINAL_RE = re.compile(r"^\d+(?:ST|ND|RD|TH)$")                                # "2ND"

# A ZIP only counts at the very end, so a five-digit house number is never taken for one.
ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?[\s,]*(?:USA?\.?)?\s*$", re.IGNORECASE)


# Five digits right after one of these are a box or unit number, not a ZIP.
# "FL" is left out because it is also Florida: "MIAMI FL 33101".
NOT_A_ZIP_BEFORE_RE = re.compile(
    r"(?:\b(?:BOX|POB|SUITE|STE|APT|APARTMENT|UNIT|RM|ROOM|FLOOR|BLDG)\.?\s*#?|#)\s*$",
    re.IGNORECASE,
)


def _find_zip(address: str) -> re.Match | None:
    """Find a ZIP at the end of an address, ignoring box and unit numbers."""
    match = ZIP_RE.search(address)
    if match and not NOT_A_ZIP_BEFORE_RE.search(address[:match.start()]):
        return match
    return None


def _clean_street_part(part: str) -> list[str]:
    """Standardise one comma-separated piece, dropping units such as "SUITE 2" or "2ND FLOOR"."""
    text = re.sub(r"\b(?:P\.?\s*O\.?\s*BOX|POB)\b", "PO BOX", part.upper()).replace("#", " # ")
    tokens = re.sub(r"[^\w\s#]", " ", text).split()
    out, skip_next = [], False
    for tok in tokens:
        if skip_next:
            skip_next = False
            continue
        if UNIT_WITH_NUMBER_RE.match(tok):
            continue
        # "2ND FLOOR": the number comes first. With exactly two words so far,
        # as in "123 5TH FL", the ordinal is the street name, so it stays.
        if tok in FLOOR_WORDS and out and ORDINAL_RE.match(out[-1]) and len(out) != 2:
            out.pop()
            continue
        if tok in UNIT_WORDS or tok == "#":
            skip_next = True
            continue
        out.append(STREET_WORDS.get(tok, tok))
    return out


def _street_key(street_line: str) -> str:
    """Standardise the street: "1790 Bay Boulevard, Suite 2" -> "1790 BAY BLVD".

    Uses the first comma-separated piece that is still non-empty once units are
    removed, so "Suite 200, 100 Main St" -> "100 MAIN ST".
    """
    zip_match = _find_zip(street_line)
    if zip_match:
        street_line = street_line[:zip_match.start()]
    for part in street_line.split(","):
        tokens = _clean_street_part(part)
        if tokens:
            return " ".join(tokens)
    return ""


def normalize_address_local(address: str | None) -> dict | None:
    """Standardise an address with simple rules. Returns None for an empty address."""
    if not address or not address.strip():
        return None

    zip_match = _find_zip(address)
    zip_code = zip_match.group(1) if zip_match else None
    street = _street_key(address)

    number_match = re.match(r"^(\d+[A-Z]?(?:-\d+)?)\s", street + " ")
    number = number_match.group(1) if number_match else None
    street_name = street[len(number):].strip() if number else street

    return {
        "standard": ", ".join(p for p in [street, zip_code] if p),
        "street_number": number,
        "street_name": street_name or None,
        "zip": zip_code,
        "source": "local",
    }


# ---------------------------------------------------------------------------
# Addresses: layer 2, US Census Geocoder (optional, online, cached)
# ---------------------------------------------------------------------------

CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "census_cache.json"


def _load_cache() -> dict:
    try:
        return json.loads(CACHE_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _census_lookup(address: str) -> dict | None:
    """Ask the Census Geocoder for a standard address. Cached; returns None on any failure."""
    cache = _load_cache()
    key = address.strip().upper()
    if key in cache:
        return cache[key]

    try:
        resp = requests.get(
            CENSUS_URL,
            params={"address": address, "benchmark": "4", "format": "json"},
            timeout=10,
        )
        resp.raise_for_status()
        matches = resp.json()["result"]["addressMatches"]
    except (requests.RequestException, KeyError, ValueError):
        return None  # network problem or unexpected reply: don't cache, fall back

    result = None
    if matches:
        best = matches[0]
        parts = best.get("addressComponents", {})
        street_line = " ".join(
            p for p in [
                parts.get("fromAddress"), parts.get("preDirection"),
                parts.get("streetName"), parts.get("suffixType"),
                parts.get("suffixDirection"),
            ] if p
        )
        street = _street_key(street_line)
        result = {
            "standard": best.get("matchedAddress"),
            "street_number": parts.get("fromAddress"),
            "street_name": street[len(parts.get("fromAddress", "")):].strip() or None,
            "zip": parts.get("zip"),
            "city": parts.get("city"),
            "source": "census",
        }

    cache[key] = result  # also cache "no match", so we never ask twice
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=1))
    return result


def normalize_address(address: str | None, use_census: bool = False) -> dict | None:
    """Standardise an address so two addresses can be compared part by part.

    Uses the US Census Geocoder when use_census=True and it finds a match;
    otherwise falls back to the local rules. Returns None for an empty address.
    """
    if not address or not address.strip():
        return None
    if use_census:
        census = _census_lookup(address)
        if census:
            return census
    return normalize_address_local(address)

if __name__ == "__main__":
    print(normalize_name("Fairway Marina INC. LLC"))