# Project notes

Decisions, findings and known limits. This feeds the final write-up.

## 2026-11-23: fixing the basic functions

The raw data was not changed. `register.db` has the same checksum before and after.

### What changed and why

| Area | Problem | Fix |
| --- | --- | --- |
| Git | `data/` was not ignored, and the CSV is over GitHub's 100 MB limit | Ignore the CSV, database and Census cache |
| Name search | A typo in a word's first letter changed the sorted word order and sank the score | Each name keeps the better of `token_sort_ratio` and plain `ratio` |
| Names | "Smith & Co" became "smith and" | Remove an "and" left just before a suffix |
| Names | "Joe's" became "joe s" and did not line up with "Joes" | Remove apostrophes |
| Addresses | Five-digit house, box and unit numbers were read as ZIPs | A ZIP must be at the end and not follow a box or unit word |
| Addresses | Units before the street, or floors like "2nd Floor", broke the street | Remove units, then use the first piece that still has text |
| Addresses | "PO Box", "P.O. Box" and "POB" were different | All become "PO BOX" |
| Clues | "Glantz, Harold" and "Harold Glantz Esq" did not match "HAROLD GLANTZ" | Ignore word order, titles and initials |
| Clues | "Atlantic Beach, NY" did not match "Atlantic Beach" | Compare the city without the state |
| Shared address | Blank addresses were counted as one shared office | Blank addresses are not counted |

JR and SR are kept in person names on purpose. They can be two different people, and a false "same person" is the more dangerous mistake.

### Before and after

Search test: 200 random companies (seed 42), counting the right company in the top 5.

| Check | Before | After |
| --- | --- | --- |
| Exact name | not re-measured | 200/200 |
| Suffix dropped | not re-measured | 200/200 |
| One-letter typo | 190/200 | 198/200 |

Search takes about 0.37 s.

### Known limits

- A typo inside a legal suffix ("COGPORATION") stops the suffix being removed. These are the last 2 typo misses.
- Made-up names can score up to 84.2 ("Bay Ridge Lantern Cafe"), so name score alone cannot justify a match. The agent also needs supporting evidence.
- An address with no commas keeps its city in the street ("123 Main St Brooklyn NY 11201"). Pass only the street line as the `street` clue.
- Misspelled cities in the register ("BROKLYN", "BROOOKLYN", "BKLYN") still count as a city mismatch.
- "13 Avenue" and "13th Avenue" are still treated as different streets.
- The shared-address count uses the street only, not the city, so the same street in two towns is counted together.
- 745 register rows hold only a unit such as "SUITE 200" in the process address, so they have no usable street.
- The Census Geocoder path is still untested.

## Planned rule: don't ignore the legal suffix

**Status: not built yet.** Add the `suffix` flag before or during the MCP tool work, and the final check when building the LangGraph agent (day 5).

### Why

`normalize_name` strips legal suffixes so that search can find different spellings of a name. That is right for finding candidates, but not for deciding the match. After cleaning, 375 groups covering 760 companies have identical names. For example, "101 GILA REALTY INC." (2599798) and "101 GILA REALTY, LLC" (2896947) are separate companies that both become "101 gila realty" and both score 100.

**A name score of 100 does not prove it is the right company.**

### The rule

1. **Claude's prompt:** extract the company name exactly as written, including its suffix, and treat a suffix difference as evidence when comparing candidates.
2. **`search_business`:** keep stripping suffixes to find candidates, then add a `suffix` flag to each candidate's `matches`:
   - `True`: same legal form
   - `False`: different legal form
   - `None`: the document gives no suffix

   Spellings of the same suffix count as equal, such as "L.L.C." and "LLC", or "Inc." and "Incorporated". A name with two legal forms, such as "Fairway Marina INC. LLC", is ambiguous and should not count as a match for either form.
3. **Final code check, after Claude answers:** this can overrule Claude and return "unmatched", but it can never pick a company itself.

| Situation | Result |
| --- | --- |
| Same cleaned name, suffix identifies one candidate, and nothing conflicts | Can match |
| Same cleaned name, no suffix in the document, and no other evidence separates them | Unmatched, list both |
| Same cleaned name, suffix conflicts with the chosen company | Unmatched, unless a non-shared street address or person clearly supports it |
| Only one candidate, but its suffix differs | Lower confidence, and match only with independent evidence |

### Notes for building it

- The suffix alone should not decide a match, because documents often get it wrong or leave it out.
- Supporting evidence must be specific. A city match is weak because 83% of process addresses are in Brooklyn, and a shared agent address says almost nothing about which company it is.
- Choose the confidence penalty from the evaluation results, not by guessing.
- Include near-duplicate pairs in the test set, and report the before and after effect of this rule in the write-up.
