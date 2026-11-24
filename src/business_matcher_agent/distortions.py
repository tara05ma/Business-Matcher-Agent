"""Deliberate mistakes for building the test set.

Each function takes a real register name and returns the version a document
might show instead. Randomness comes from a `random.Random` passed in, so the
same seed always gives the same test set.
"""
import random
import re

from business_matcher_agent.normalize import NAME_SUFFIXES

# Common words and the short forms people write in documents.
ABBREVIATIONS = {
    "BROTHERS": "BROS", "MANUFACTURING": "MFG", "MANAGEMENT": "MGMT",
    "ASSOCIATES": "ASSOC", "INTERNATIONAL": "INTL", "SERVICES": "SVCS",
    "SERVICE": "SVC", "CONSTRUCTION": "CONSTR", "DEVELOPMENT": "DEV",
    "CENTER": "CTR", "ENTERPRISES": "ENT", "PROPERTIES": "PROPS",
    "TRANSPORTATION": "TRANSP", "CONTRACTING": "CONTR", "GENERAL": "GEN",
    "EQUIPMENT": "EQUIP", "PRODUCTS": "PRODS", "MEDICAL": "MED",
    "HOLDINGS": "HLDGS", "AVENUE": "AVE", "STREET": "ST", "BROOKLYN": "BKLYN",
}

# Word lists for names that must NOT be real companies (always checked against
# the register before use).
NAME_STARTS = [
    "Golden", "Silver", "Royal", "Liberty", "Empire", "Evergreen", "Bright",
    "Summit", "Union", "Crown", "Maple", "Cedar", "Northstar", "Bluebird",
    "Keystone", "Harbor", "Flatbush", "Prospect", "Gowanus", "Canarsie",
    "Bushwick", "Midwood", "Red Hook", "Bay Ridge", "Ocean Hill",
]
TRADES = [
    "Plumbing", "Bakery", "Auto Repair", "Roofing", "Tile Works", "Catering",
    "Electric", "Hardware", "Dry Cleaners", "Pharmacy", "Deli", "Florist",
    "Contracting", "Movers", "Printing", "Fitness", "Wine & Spirits", "Cafe",
]
# Common words in real company names, used to make believable fakes.
BUSINESS_WORDS = [
    "Realty", "Management", "Group", "Holdings", "Services", "Construction",
    "Trading", "Design", "Consulting", "Media", "Foods", "Motors", "Logistics",
    "Supply", "Imports", "Studio",
]
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _clean_token(token: str) -> str:
    """'L.L.C.,' -> 'llc': the token as normalize_name would compare it."""
    return re.sub(r"[^\w]", "", token.lower())


def split_suffix(name: str) -> tuple[str, str]:
    """Split a legal name into its base and its legal suffix.

    "FARWAY MARINA, INC." -> ("FARWAY MARINA", "INC.")
    "SMITH & CO."         -> ("SMITH", "& CO.")
    A name that is only a suffix keeps everything as its base.
    """
    tokens = name.split()
    suffix: list[str] = []
    while tokens and _clean_token(tokens[-1]) in NAME_SUFFIXES:
        suffix.insert(0, tokens.pop())
        if tokens and _clean_token(tokens[-1]) in {"and", ""}:  # "& CO", "AND CO"
            suffix.insert(0, tokens.pop())
    base = " ".join(tokens).rstrip(" ,")
    if not base or base.lower() == "the":  # same rule as normalize_name
        return name, ""
    return base, " ".join(suffix)


# Suffix word -> legal form. "Co" and "Company" are left out: an LLC can be a
# "company" too, so they don't say which form it is.
LEGAL_FORMS = {
    "inc": "corporation", "incorporated": "corporation", "corp": "corporation",
    "corporation": "corporation", "llc": "llc", "pllc": "pllc", "lp": "lp",
    "llp": "llp", "pc": "pc", "dpc": "pc", "ltd": "limited", "limited": "limited",
}


def legal_form(name: str) -> str | None:
    """ "101 GILA REALTY, L.L.C." -> "llc"; None when the suffix doesn't say."""
    forms = [LEGAL_FORMS.get(_clean_token(t)) for t in split_suffix(name)[1].split()]
    forms = [f for f in forms if f]
    return forms[-1] if forms else None


def drop_suffix(name: str) -> str:
    """ "FARWAY MARINA, INC." -> "FARWAY MARINA" """
    return split_suffix(name)[0]


def change_suffix(name: str) -> str:
    """Swap the legal form: a corporation becomes LLC, anything else becomes Inc."""
    base = split_suffix(name)[0]
    return f"{base} {'LLC' if legal_form(name) == 'corporation' else 'INC.'}"


def _match_case(original: str, replacement: str) -> str:
    return replacement.upper() if original.isupper() else replacement.title()


def abbreviate(name: str, rng: random.Random) -> str | None:
    """Shorten one word: "SMITH BROTHERS PLUMBING INC" -> "SMITH BROS PLUMBING INC".

    Returns None when the name has no word on the list.
    """
    base, suffix = split_suffix(name)
    tokens = base.split()
    choices = [i for i, t in enumerate(tokens)
               if re.sub(r"[^A-Za-z]", "", t).upper() in ABBREVIATIONS]
    if not choices:
        return None
    i = rng.choice(choices)
    word = re.sub(r"[^A-Za-z]", "", tokens[i])
    tokens[i] = tokens[i].replace(word, _match_case(word, ABBREVIATIONS[word.upper()]))
    return " ".join(tokens + ([suffix] if suffix else []))


def add_typos(name: str, rng: random.Random, count: int = 1) -> str:
    """Put `count` one-letter mistakes into the base name (never the suffix).

    Each mistake is a wrong letter, a missing letter, or two letters swapped.
    The mistakes go on different letters at least two apart, so a second
    mistake can never undo the first and the result always differs.
    """
    base, suffix = split_suffix(name)
    chars = list(base)
    letters = [i for i, c in enumerate(chars) if c.isalpha()]
    if not letters:
        raise ValueError(f"{name!r} has no letters to change")

    # Choose the positions first: shuffle the letters, keep each one that is
    # not next to a position already chosen.
    chosen: list[int] = []
    for i in rng.sample(letters, len(letters)):
        if all(abs(i - j) > 1 for j in chosen):
            chosen.append(i)
        if len(chosen) == count:
            break
    if len(chosen) < count:
        raise ValueError(f"{name!r} is too short for {count} separate typos")

    # Work right to left, so deleting a letter never moves a position still to come.
    letters_left = len(letters)
    for i in sorted(chosen, reverse=True):
        kind = rng.choice(["wrong", "missing", "swapped"])
        can_swap = i + 1 < len(chars) and chars[i + 1].isalpha() and chars[i + 1] != chars[i]
        if kind == "missing" and letters_left > 3:
            del chars[i]
            letters_left -= 1
        elif kind == "swapped" and can_swap:
            chars[i], chars[i + 1] = chars[i + 1], chars[i]
        else:
            new = rng.choice([c for c in LETTERS if c != chars[i].upper()])
            chars[i] = new if chars[i].isupper() else new.lower()
    return "".join(chars) + (f" {suffix}" if suffix else "")


def replace_word(name: str, rng: random.Random) -> str | None:
    """Swap one later word for a common business word, to make a believable fake.

    "ATLANTIC TILE WORKS LLC" -> "ATLANTIC TILE TRADING LLC". The first word is
    kept, so the fake still looks like the real company. Returns None when the
    name has no later word of three or more letters.
    """
    base, suffix = split_suffix(name)
    tokens = base.split()
    choices = [i for i, t in enumerate(tokens) if i > 0 and t.isalpha() and len(t) >= 3]
    if not choices:
        return None
    i = rng.choice(choices)
    new = rng.choice([w for w in BUSINESS_WORDS if w.upper() != tokens[i].upper()])
    tokens[i] = _match_case(tokens[i], new)
    return " ".join(tokens + ([suffix] if suffix else []))


def invent_name(rng: random.Random, with_suffix: bool = True) -> str:
    """A believable Brooklyn business name, such as "Canarsie Roofing LLC".

    Not checked here: the caller must confirm it is not in the register.
    """
    parts = [rng.choice(NAME_STARTS), rng.choice(TRADES)]
    if with_suffix:
        parts.append(rng.choice(["LLC", "Inc.", "Corp."]))
    return " ".join(parts)
