"""The agent's read-only tools: get_business and search_business.

normalize_address (the third tool) lives in normalize.py.
"""
import os
import re
import sqlite3
from collections import Counter
from functools import lru_cache
from pathlib import Path

from rapidfuzz import fuzz, process

from business_matcher_agent.normalize import (
    _street_key,
    normalize_city,
    normalize_name,
    normalize_person,
)

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.environ.get("REGISTER_DB", ROOT / "data" / "register.db"))

SHORTLIST = 50              # how many name matches to look at closely
MIN_NAME_SCORE = 60         # below this a name is clearly unrelated and is never returned
SHARED_ADDRESS_LIMIT = 20   # more companies than this at one address = likely an agent's office


def _connect() -> sqlite3.Connection:
    """Open the register read-only, so nothing can ever change it."""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"{DB_PATH} not found. Run scripts/load_db.py first.")
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


# ---------------------------------------------------------------------------
# get_business
# ---------------------------------------------------------------------------

def get_business(dos_id: str) -> dict | None:
    """Return every field of one company, or None if the ID doesn't exist."""
    dos_id = str(dos_id).strip()
    if not dos_id.isdigit():  # IDs are digits only; reject anything else straight away
        return None
    with _connect() as con:
        row = con.execute('SELECT * FROM companies WHERE "DOS ID" = ?', (dos_id,)).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# search_business
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _search_index() -> tuple[list[str], list[str], Counter]:
    """Built once, the first time a search runs (a few seconds).

    Returns the cleaned names, their DOS IDs (same order), and how many
    companies share each process street address.
    """
    with _connect() as con:
        rows = con.execute(
            'SELECT "DOS ID", "Current Entity Name", "DOS Process Address 1" FROM companies'
        ).fetchall()

    names, ids, address_counts = [], [], Counter()
    for dos_id, name, process_address in rows:
        street = _street_key(process_address) if process_address else ""
        if street:  # a blank street is missing data, not one shared office
            address_counts[street] += 1
        if name:  # skip the row with no name: a name search can't find it
            names.append(normalize_name(name))
            ids.append(dos_id)
    return names, ids, address_counts


def warm_up() -> None:
    """Build the search index now, so the first real search isn't slow."""
    _search_index()


def _name_scores(query: str, names: list[str]) -> dict[int, float]:
    """Score register names against the query; returns {position in names: score}.

    token_sort_ratio handles reordered words ("Marina Farway"), but a typo in a
    word's first letter can change the sorted order and sink the score. Plain
    ratio handles that case. Each name keeps the better of its two scores.
    """
    shortlisted = set()
    for scorer in (fuzz.token_sort_ratio, fuzz.ratio):
        hits = process.extract(
            query, names, scorer=scorer, processor=None,
            limit=SHORTLIST, score_cutoff=MIN_NAME_SCORE,
        )
        shortlisted.update(index for _, _, index in hits)

    scores = {
        i: max(fuzz.token_sort_ratio(query, names[i]), fuzz.ratio(query, names[i]))
        for i in shortlisted
    }
    best = sorted(scores, key=scores.get, reverse=True)[:SHORTLIST]
    return {i: scores[i] for i in best}


def _zip5(value: str | None) -> str | None:
    match = re.match(r"\s*(\d{5})", value or "")
    return match.group(1) if match else None


def _compare(doc_value, candidate_values) -> bool | None:
    """True/False if both sides have data; None if either side is missing (no evidence)."""
    candidate_values = [v for v in candidate_values if v]
    if not doc_value or not candidate_values:
        return None
    return doc_value in candidate_values


def search_business(
    name: str,
    city: str | None = None,
    zip: str | None = None,
    street: str | None = None,
    person: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Find the register companies whose names are closest to `name`.

    The name decides the candidates. City, ZIP, street and person never remove
    a candidate; they only add yes/no evidence flags to each one.
    """
    query = normalize_name(name)
    if not query:
        return []
    limit = max(1, min(int(limit), 20))
    names, ids, address_counts = _search_index()

    # 1. Fuzzy-match the cleaned name against every cleaned register name.
    scores = {ids[index]: score for index, score in _name_scores(query, names).items()}
    if not scores:
        return []  # nothing even loosely similar: say so, never pad the list

    # 2. Fetch the shortlisted companies' rows in one query.
    placeholders = ",".join("?" * len(scores))
    with _connect() as con:
        rows = con.execute(
            f'SELECT * FROM companies WHERE "DOS ID" IN ({placeholders})', list(scores)
        ).fetchall()

    # 3. Prepare the document's clues once.
    doc_city = normalize_city(city)
    doc_zip = _zip5(zip)
    doc_street = _street_key(street) if street else None
    doc_person = normalize_person(person)

    # 4. Build a slim result for each candidate, with evidence flags.
    results = []
    for row in rows:
        r = dict(row)
        process_key = _street_key(r["DOS Process Address 1"]) if r["DOS Process Address 1"] else None
        shared_by = address_counts.get(process_key, 0) if process_key else 0
        matches = {
            "city": _compare(doc_city, [normalize_city(r[c]) for c in
                                        ("DOS Process City", "Location City", "CEO City")]),
            "zip": _compare(doc_zip, [_zip5(r[c]) for c in
                                      ("DOS Process Zip", "Location Zip", "CEO Zip")]),
            "street": _compare(doc_street, [_street_key(r[c]) for c in
                                            ("DOS Process Address 1", "Location Address 1") if r[c]]),
            "person": _compare(doc_person, [normalize_person(r[c]) for c in
                                            ("CEO Name", "DOS Process Name", "Location Name")]),
        }
        results.append({
            "dos_id": r["DOS ID"],
            "name": r["Current Entity Name"],
            "entity_type": r["Entity Type"],
            "name_score": round(scores[r["DOS ID"]], 1),
            "process_city": r["DOS Process City"],
            "process_zip": r["DOS Process Zip"],
            "matches": matches,
            "process_address_shared_by": shared_by,
            "shared_address": shared_by > SHARED_ADDRESS_LIMIT,
        })

    # 5. Rank by name score; evidence flags only break ties, they never outrank the name.
    results.sort(key=lambda c: (-c["name_score"], -sum(v is True for v in c["matches"].values())))
    return results[:limit]