"""Choose the generated test set: which companies, which mistakes, which facts.

Usage:  uv run python scripts/select_test_set.py           # refuses to overwrite
        uv run python scripts/select_test_set.py --force   # rebuild from scratch

Writes two files to data/testset/:
- specs.jsonl:   the facts each document must contain. The document writer
                 (scripts/generate_documents.py, day 6) reads only this file.
- answers.jsonl: the right answer for each document. The agent never sees it.

Companies are picked at random with a fixed seed, so the set can be rebuilt
exactly. They are never filtered by whether our own search finds them, which
would make the test set too easy.
"""
import argparse
import json
import random
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from business_matcher_agent import distortions as d
from business_matcher_agent.normalize import _street_key, normalize_address, normalize_name
from business_matcher_agent.tools import DB_PATH, search_business

SEED = 20261124
OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "testset"

FAKE_MAX_SCORE = 85        # an invented name must score below this against every real company
HARD_FAKE_MAX_SCORE = 92   # a hard fake may be closer, but not typo-close (real typos score ~92+)
CERTIFICATE_HOLDER_TRAPS = 4

DOC_TYPES = ["certificate_cover_letter", "insurer_email", "invoice"]
INSURERS = [  # invented, and checked against the register before use
    "Northlantern Mutual Insurance Company", "Copperleaf Casualty Insurance Co.",
    "Bluewillow Assurance Company", "Granitepoint Insurance Group",
]
BROOKLYN_STREETS = [
    "Flatbush Avenue", "Atlantic Avenue", "Nostrand Avenue", "Ocean Parkway",
    "Kings Highway", "Bedford Avenue", "Court Street", "86th Street",
    "5th Avenue", "Fulton Street", "Coney Island Avenue", "Myrtle Avenue",
]
BROOKLYN_ZIPS = [f"112{n:02d}" for n in range(1, 40) if n not in (2, 27)]


# ---------------------------------------------------------------------------
# The register, and the lookups the selection needs
# ---------------------------------------------------------------------------

class Register:
    def __init__(self) -> None:
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        rows = con.execute(
            'SELECT "DOS ID", "Current Entity Name", "DOS Process Name", '
            '"DOS Process Address 1", "DOS Process City", "DOS Process Zip", "CEO Name" '
            'FROM companies WHERE "Current Entity Name" IS NOT NULL'
        ).fetchall()
        con.close()
        self.companies = [
            {"dos_id": r[0], "name": r[1], "process_name": r[2], "address": r[3],
             "city": r[4], "zip": r[5], "ceo": r[6]}
            for r in rows
        ]
        self.name_counts = Counter(normalize_name(c["name"]) for c in self.companies)
        self.address_counts = Counter(
            _street_key(c["address"]) for c in self.companies if c["address"]
        )
        groups = defaultdict(list)
        for c in self.companies:
            groups[normalize_name(c["name"])].append(c)
        self.twin_pairs = [g for g in groups.values() if len(g) == 2 and _real_twins(*g)]

    def has_twin(self, c: dict) -> bool:
        return self.name_counts[normalize_name(c["name"])] > 1

    def has_own_address(self, c: dict) -> bool:
        """True when the process address is the company's own: legal papers go
        to the company itself, and no other company uses that street address."""
        key = _street_key(c["address"]) if c["address"] else ""
        return bool(key) and self.address_counts[key] == 1 and \
            normalize_name(c["process_name"]) == normalize_name(c["name"])

    def name_points_only_to(self, text: str, c: dict) -> bool:
        """True when no OTHER company has the same cleaned name as `text`."""
        cleaned = normalize_name(text)
        expected = 1 if cleaned == normalize_name(c["name"]) else 0
        return self.name_counts.get(cleaned, 0) == expected

    def best_real_score(self, text: str) -> float:
        """How close the nearest real company name is (100 if it exists exactly)."""
        if self.name_counts.get(normalize_name(text)):
            return 100.0
        results = search_business(text, limit=1)
        return results[0]["name_score"] if results else 0.0


def _real_twins(a: dict, b: dict) -> bool:
    """Same name apart from a different legal form ("INC." vs "LLC").

    Pairs that differ only in punctuation ("#ABC" vs "ABC") or only in how the
    same form is written ("INC." vs "INCORPORATED") are left out.
    """
    def letters(name):
        return re.sub(r"[^A-Z0-9]", "", d.drop_suffix(name).upper())
    form_a, form_b = d.legal_form(a["name"]), d.legal_form(b["name"])
    return letters(a["name"]) == letters(b["name"]) and form_a and form_b and form_a != form_b


class Picker:
    """Hands out random companies, never the same one twice."""

    def __init__(self, register: Register, rng: random.Random) -> None:
        self.register = register
        self.order = list(register.companies)
        rng.shuffle(self.order)
        self.used: set[str] = set()

    def next(self, condition=lambda c: True) -> dict:
        for c in self.order:
            if c["dos_id"] in self.used or self.register.has_twin(c):
                continue  # twins are only used on purpose, in the near-duplicate group
            if not re.search(r"[A-Za-z]{3,}", d.drop_suffix(c["name"])):
                continue  # e.g. "J & V LLC": too short to distort meaningfully
            if condition(c):
                self.used.add(c["dos_id"])
                return c
        raise RuntimeError("No company left that meets the condition")


# ---------------------------------------------------------------------------
# Facts a document shows besides the name
# ---------------------------------------------------------------------------

def zip5(value: str | None) -> str | None:
    match = re.match(r"\s*(\d{5})", value or "")
    return match.group(1) if match else None


def address_facts(c: dict, register: Register, rng: random.Random, mode: str | None = None) -> dict:
    """The client's address as the document shows it.

    The register only knows the company's own address when legal papers go to
    the company itself. Otherwise the address belongs to a lawyer or agent, so
    the document shows no address rather than a misleading one.
    """
    if mode is None:
        mode = rng.choices(["full", "city_zip", "none"], weights=[6, 3, 1])[0] \
            if register.has_own_address(c) else "none"
    return {
        "address_line": c["address"] if mode == "full" else None,
        "city": c["city"] if mode in ("full", "city_zip") else None,
        "zip": zip5(c["zip"]) if mode in ("full", "city_zip") else None,
    }


def fake_brooklyn_address(rng: random.Random, avoid_zip: str | None = None) -> dict:
    return {
        "address_line": f"{rng.randint(10, 2999)} {rng.choice(BROOKLYN_STREETS)}",
        "city": "Brooklyn",
        "zip": rng.choice([z for z in BROOKLYN_ZIPS if z != avoid_zip]),
    }


def contact_for(c: dict, rng: random.Random) -> str | None:
    return c["ceo"] if c["ceo"] and rng.random() < 0.5 else None


def case(distortion, variant, ideal, company, shown_name, *, legal_name=None,
         address=None, contact=None, must_not_contain=(), notes="") -> dict:
    address = address or {"address_line": None, "city": None, "zip": None}
    return {
        "distortion": distortion, "variant": variant, "ideal_outcome": ideal,
        "company": company, "client_name": shown_name, "legal_name_small_print": legal_name,
        **address, "contact": contact, "must_not_contain": list(must_not_contain), "notes": notes,
    }


# ---------------------------------------------------------------------------
# One builder per distortion
# ---------------------------------------------------------------------------

def pick_distorted(picker: Picker, make, condition=lambda c: True):
    """Pick companies until the distorted name still points to that company only."""
    while True:
        c = picker.next(condition)
        shown = make(c)
        if shown and picker.register.name_points_only_to(shown, c):
            return c, shown


def suffix_cases(picker, register, rng):
    cases = []
    for _ in range(4):
        c, shown = pick_distorted(picker, lambda c: d.drop_suffix(c["name"]),
                                  lambda c: d.split_suffix(c["name"])[1] != "")
        cases.append(case("suffix_changed_or_dropped", "dropped", "match", c, shown,
                          address=address_facts(c, register, rng), contact=contact_for(c, rng),
                          must_not_contain=[c["name"]]))
    for _ in range(2):
        # A changed suffix conflicts with the register, so the document also gives
        # the company's own full address as independent evidence.
        c, shown = pick_distorted(picker, lambda c: d.change_suffix(c["name"]),
                                  lambda c: d.split_suffix(c["name"])[1] != "" and register.has_own_address(c))
        cases.append(case("suffix_changed_or_dropped", "changed", "match", c, shown,
                          address=address_facts(c, register, rng, mode="full"),
                          must_not_contain=[c["name"]],
                          notes="legal form differs from the register; full address given as evidence"))
    return cases


def abbreviation_cases(picker, register, rng):
    cases = []
    for _ in range(6):
        c, shown = pick_distorted(picker, lambda c: d.abbreviate(c["name"], rng),
                                  lambda c: d.abbreviate(c["name"], random.Random(0)) is not None)
        cases.append(case("abbreviation", "abbreviated", "match", c, shown,
                          address=address_facts(c, register, rng), contact=contact_for(c, rng),
                          must_not_contain=[c["name"]]))
    return cases


def typo_cases(picker, register, rng):
    cases = []
    for _ in range(7):
        def make(c):
            count = 2 if len(d.drop_suffix(c["name"])) >= 15 and rng.random() < 0.5 else 1
            return d.add_typos(c["name"], rng, count)
        c, shown = pick_distorted(picker, make)
        cases.append(case("typo", "one_or_two_letters", "match", c, shown,
                          address=address_facts(c, register, rng), contact=contact_for(c, rng),
                          must_not_contain=[d.drop_suffix(c["name"])]))
    return cases


def invent_absent_name(register, rng, with_suffix=True, max_score=FAKE_MAX_SCORE):
    while True:
        name = d.invent_name(rng, with_suffix)
        score = register.best_real_score(name)
        if score < max_score:
            return name, score


def trade_name_cases(picker, register, rng):
    cases = []
    for i in range(7):
        c = picker.next()
        trade, score = invent_absent_name(register, rng, with_suffix=False)
        if i < 5:
            cases.append(case("trade_name", "legal_name_in_small_print", "match", c, trade,
                              legal_name=c["name"], address=address_facts(c, register, rng),
                              contact=contact_for(c, rng),
                              notes=f"trade name's closest real company scores {score}"))
        else:
            cases.append(case("trade_name", "trade_name_only", "abstain", c, trade,
                              address=address_facts(c, register, rng, mode="none"),
                              must_not_contain=[d.drop_suffix(c["name"])],
                              notes="nothing in the document links the trade name to the company"))
    return cases


def address_cases(picker, register, rng):
    cases = []
    variants = ["street_missing", "moved", "number_missing", "street_missing", "moved",
                "number_missing", "moved"]
    for variant in variants:
        c = picker.next(lambda c: register.has_own_address(c)
                        and normalize_address(c["address"])["street_number"] is not None)
        real = normalize_address(c["address"])
        if variant == "street_missing":
            address = {"address_line": None, "city": c["city"], "zip": zip5(c["zip"])}
        elif variant == "number_missing":
            address = {"address_line": real["street_name"], "city": c["city"], "zip": zip5(c["zip"])}
        else:  # moved: an invented Brooklyn address, as if the register is out of date
            address = fake_brooklyn_address(rng, avoid_zip=zip5(c["zip"]))
        cases.append(case("old_or_partial_address", variant, "match", c, c["name"],
                          address=address, contact=contact_for(c, rng),
                          must_not_contain=[c["address"]],
                          notes=f"register address: {c['address']}, {c['city']} {zip5(c['zip'])}"))
    return cases


def near_duplicate_cases(picker, register, rng):
    cases = []
    pairs = list(register.twin_pairs)
    rng.shuffle(pairs)
    variants = ["suffix", "suffix", "suffix", "address", "address", "no_clue", "no_clue"]
    for variant in variants:
        for pair in pairs:
            if any(c["dos_id"] in picker.used for c in pair):
                continue
            target, twin = rng.sample(pair, 2)
            if variant == "address" and not register.has_own_address(target):
                continue
            break
        else:
            raise RuntimeError(f"No twin pair left for variant {variant}")
        picker.used.update(c["dos_id"] for c in pair)
        notes = f"twin: {twin['name']} ({twin['dos_id']})"
        if variant == "suffix":  # the exact legal name, suffix included, tells them apart
            cases.append(case("near_duplicate", variant, "match", target, target["name"],
                              must_not_contain=[twin["name"]], notes=notes))
        elif variant == "address":  # no suffix, but the company's own address tells them apart
            cases.append(case("near_duplicate", variant, "match", target, d.drop_suffix(target["name"]),
                              address=address_facts(target, register, rng, mode="full"),
                              must_not_contain=[target["name"], twin["name"]], notes=notes))
        else:  # nothing tells them apart: a careful reader can't know which one
            cases.append(case("near_duplicate", variant, "abstain", target, d.drop_suffix(target["name"]),
                              must_not_contain=[target["name"], twin["name"]],
                              notes=notes + "; no clue separates the twins"))
    return cases


def does_not_exist_cases(picker, register, rng):
    cases = []
    for _ in range(5):
        name, score = invent_absent_name(register, rng)
        address = fake_brooklyn_address(rng) if rng.random() < 0.5 else {
            "address_line": None, "city": "Brooklyn", "zip": None}
        cases.append(case("does_not_exist", "invented", "abstain", None, name, address=address,
                          notes=f"closest real company scores {score}"))
    for _ in range(5):
        while True:
            source = picker.next(lambda c: d.replace_word(c["name"], random.Random(0)) is not None)
            name = d.replace_word(source["name"], rng)
            score = register.best_real_score(name)
            if score < HARD_FAKE_MAX_SCORE:
                break
        cases.append(case("does_not_exist", "one_word_changed", "abstain", None, name,
                          address={"address_line": None, "city": "Brooklyn", "zip": None},
                          notes=f"made from real company {source['name']} ({source['dos_id']}) "
                                f"by changing one word; closest real company scores {score}"))
    return cases


# ---------------------------------------------------------------------------
# Other businesses in the document, and writing the files
# ---------------------------------------------------------------------------

def add_other_parties(cases, picker, register, rng):
    """Every document names an insurer and a certificate holder (usually a landlord).

    A few documents name a REAL register company as the certificate holder, to
    test that the agent matches the insured client, not the first company it sees.
    """
    insurers = [i for i in INSURERS if register.best_real_score(i) < FAKE_MAX_SCORE]
    can_trap = [c for c in cases if c["ideal_outcome"] == "match"]
    traps = {id(c) for c in rng.sample(can_trap, CERTIFICATE_HOLDER_TRAPS)}
    for c in cases:
        c["insurer"] = rng.choice(insurers)
        c["doc_type"] = rng.choice(DOC_TYPES)
        if id(c) in traps:
            holder = picker.next()
            c["certificate_holder"] = holder["name"]
            c["notes"] = (c["notes"] + "; " if c["notes"] else "") + \
                f"certificate holder is a real register company ({holder['dos_id']})"
        else:
            while True:
                holder = f"{rng.choice(d.NAME_STARTS)} {rng.choice(['Realty', 'Plaza Owners', 'Property Management'])} LLC"
                if register.best_real_score(holder) < FAKE_MAX_SCORE:
                    break
            c["certificate_holder"] = holder


def to_spec(doc: str, c: dict) -> dict:
    """What the document writer gets: facts only, never the answer."""
    must_include = [c[k] for k in ("client_name", "legal_name_small_print", "address_line",
                                   "city", "zip", "contact", "insurer", "certificate_holder") if c[k]]
    return {
        "doc": doc, "doc_type": c["doc_type"], "client_name": c["client_name"],
        "legal_name_small_print": c["legal_name_small_print"],
        "address_line": c["address_line"], "city": c["city"], "zip": c["zip"],
        "contact": c["contact"], "insurer": c["insurer"], "certificate_holder": c["certificate_holder"],
        "must_include": must_include, "must_not_contain": c["must_not_contain"],
    }


def to_answer(doc: str, c: dict) -> dict:
    company = c["company"]
    return {
        "doc": doc,
        "expected_dos_id": company["dos_id"] if company else None,
        "register_name": company["name"] if company else None,
        "distortion": c["distortion"], "variant": c["variant"],
        "ideal_outcome": c["ideal_outcome"], "notes": c["notes"],
    }


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="overwrite an existing test set")
    args = parser.parse_args()

    answers_path = OUT_DIR / "answers.jsonl"
    if answers_path.exists() and not args.force:
        raise SystemExit(f"{answers_path} already exists. Use --force to rebuild it.")

    rng = random.Random(SEED)
    register = Register()
    picker = Picker(register, rng)

    cases = []
    for build in (suffix_cases, abbreviation_cases, typo_cases, trade_name_cases,
                  address_cases, near_duplicate_cases, does_not_exist_cases):
        cases += build(picker, register, rng)
    add_other_parties(cases, picker, register, rng)

    rng.shuffle(cases)  # so a document's number never hints at its distortion
    docs = [f"doc_{i:03d}.txt" for i in range(1, len(cases) + 1)]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_jsonl(OUT_DIR / "specs.jsonl", [to_spec(doc, c) for doc, c in zip(docs, cases)])
    write_jsonl(answers_path, [to_answer(doc, c) for doc, c in zip(docs, cases)])

    print(f"{'doc':<12}{'distortion':<27}{'variant':<27}{'ideal':<9}register name -> shown name")
    for doc, c in sorted(zip(docs, cases), key=lambda x: (x[1]["distortion"], x[0])):
        real = c["company"]["name"] if c["company"] else "(none)"
        print(f"{doc:<12}{c['distortion']:<27}{c['variant']:<27}{c['ideal_outcome']:<9}"
              f"{real} -> {c['client_name']}")
    counts = Counter(c["ideal_outcome"] for c in cases)
    print(f"\n{len(cases)} documents: {counts['match']} match, {counts['abstain']} abstain. "
          f"Written to {OUT_DIR}")


if __name__ == "__main__":
    main()
