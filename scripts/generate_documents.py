"""Write the messy test documents from data/testset/specs.jsonl.

select_test_set.py decided what each document must say. This script asks
Claude to write it as a realistic, messy document, then checks the result:
  - every required string is there (the deliberate mistakes must survive), and
  - no forbidden string is there (for example the company's correct name).
A document that fails the check is sent back with the problems, up to
MAX_ATTEMPTS times. One that still fails is not saved and is listed at the end.

The writer only ever sees specs.jsonl, never the answers.

Run:
    uv run scripts/generate_documents.py --dry-run          # show one prompt, no API call
    uv run --env-file .env scripts/generate_documents.py --limit 2   # try two documents
    uv run --env-file .env scripts/generate_documents.py    # write all missing documents

Needs ANTHROPIC_API_KEY in .env (never commit it).
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPECS = ROOT / "data" / "testset" / "specs.jsonl"
OUT_DIR = ROOT / "data" / "testset" / "docs"
MANIFEST = OUT_DIR / "manifest.jsonl"

MODEL = "claude-haiku-5-5"
MAX_ATTEMPTS = 3
MAX_TOKENS = 4000

# Invented brokers, so Claude doesn't make one up. Each was checked against the
# register on 2026-11-24 and scores at most 78.6 (the limit for invented names is 85).
BROKERS = [
    "Tamberlane Risk Partners",
    "Quillfeather Brokerage Group",
    "Fenmore & Achterberg Brokerage",
    "Okonkwo Pryce Insurance Agency",
]

DOC_TYPES = {
    "certificate_cover_letter": (
        "a cover letter or email from an insurance broker sending a certificate of "
        "insurance to the certificate holder, naming the client as the insured"),
    "insurer_email": (
        "an email, or a short forwarded email thread, between the insurer and a broker "
        "about the client's policy (a renewal, a claim, or a change to the policy)"),
    "invoice": (
        "an invoice or premium bill from the insurer to the client, as plain text "
        "with line items"),
}

SYSTEM = """You write realistic test documents for an insurance company. A matching \
system will later read each document and try to find the client in a register of \
companies, so the documents must look like real, messy paperwork.

Rules:
1. Write exactly one plain-text document of the requested kind. Output only the \
document: no commentary, no markdown, no code fences.
2. REQUIRED strings must appear exactly as written, character for character. Some \
contain deliberate misspellings, abbreviations or missing words. Never correct them.
3. FORBIDDEN strings must not appear anywhere, in any capitalisation or punctuation.
4. Name only the businesses given in the facts: no other brokers, banks, landlords \
or vendors. Refer to anything else generically ("our office", "the landlord"). \
People at the insurer or broker may have invented names. Use email addresses \
ending in .example and 555 phone numbers.
5. Only give the client an address if one is supplied. Never invent a street \
address for the client.
6. Make it messy the way real documents are: email headers, signatures, legal \
disclaimers, reference numbers, uneven spacing, an odd line break. Keep it under \
350 words. The client must still be clearly identifiable as the insured or customer."""


def _norm(text: str) -> str:
    """Compare loosely, like normalize_name: lower case, dots and apostrophes
    removed ("L.L.C." -> "llc"), other punctuation as spaces, single spaces."""
    text = re.sub(r"[.'’]", "", text.lower())
    return " " + " ".join(re.sub(r"[^\w]+", " ", text).split()) + " "


def check_document(text: str, spec: dict) -> list[str]:
    """Problems with a written document; an empty list means it passes.

    Case and punctuation are ignored, so "SMITH BROS" may be written "Smith Bros",
    but a corrected spelling or an added word fails.
    """
    doc = _norm(text)
    problems = [f"missing required string: {s!r}"
                for s in spec["must_include"] if _norm(s) not in doc]
    problems += [f"contains forbidden string: {s!r}"
                 for s in spec["must_not_contain"] if _norm(s) in doc]
    return problems


def broker_for(spec: dict) -> str:
    """The same broker every time for a document: doc_007.txt -> BROKERS[7 % 4]."""
    number = int(re.sub(r"\D", "", spec["doc"]))
    return BROKERS[number % len(BROKERS)]


def build_prompt(spec: dict) -> str:
    """The request for one document. It uses only facts from the spec."""
    lines = [f"Write {DOC_TYPES[spec['doc_type']]}.", "", "Facts:"]
    lines.append(f"- Client (the insured or customer), written as: {spec['client_name']}")
    if spec["legal_name_small_print"]:
        lines.append(
            f"- The client's legal name is {spec['legal_name_small_print']}. Use the "
            "client name above throughout, and show the legal name only once, in small "
            "print (a footer, a 'd/b/a' line or the named-insured line).")
    address = [spec[k] for k in ("address_line", "city", "zip") if spec[k]]
    if address:
        lines.append(f"- Client's address, as far as known: {', '.join(address)}. "
                     "Show only these parts.")
    else:
        lines.append("- The client's address is not known. Do not give one.")
    if spec["contact"]:
        lines.append(f"- Contact person at the client: {spec['contact']}")
    else:
        lines.append("- No contact person at the client is known. Do not name anyone "
                     "who works for the client; address the client by business name only.")
    lines.append(f"- Insurer: {spec['insurer']}")
    lines.append(f"- Broker, if the document needs one: {broker_for(spec)}")
    lines.append(f"- Certificate holder (the landlord, not the client): "
                 f"{spec['certificate_holder']}")
    lines += ["", "REQUIRED strings:", *[f"- {s}" for s in spec["must_include"]]]
    if spec["must_not_contain"]:
        lines += ["", "FORBIDDEN strings:", *[f"- {s}" for s in spec["must_not_contain"]]]
    return "\n".join(lines)


def _clean(text: str) -> str:
    """Remove code fences in case the model adds them anyway."""
    text = re.sub(r"^```[a-z]*\n|\n```$", "", text.strip())
    return text.strip() + "\n"


def write_one(client, spec: dict, model: str) -> dict:
    """Ask Claude for one document, retrying with feedback. Returns a manifest row."""
    messages = [{"role": "user", "content": build_prompt(spec)}]
    row = {"doc": spec["doc"], "model": model, "attempts": 0, "ok": False,
           "problems": [], "input_tokens": 0, "output_tokens": 0}
    for _ in range(MAX_ATTEMPTS):
        row["attempts"] += 1
        response = client.messages.create(
            model=model, max_tokens=MAX_TOKENS, system=SYSTEM, messages=messages)
        row["input_tokens"] += response.usage.input_tokens
        row["output_tokens"] += response.usage.output_tokens
        text = _clean("".join(b.text for b in response.content if b.type == "text"))

        if response.stop_reason != "end_turn":
            problems = [f"stopped early ({response.stop_reason})"]
        else:
            problems = check_document(text, spec)
        row["problems"] = problems
        if not problems:
            (OUT_DIR / spec["doc"]).write_text(text, encoding="utf-8")
            row["ok"] = True
            return row
        messages += [
            {"role": "assistant", "content": text or "(empty)"},
            {"role": "user", "content": "The document has these problems:\n"
             + "\n".join(f"- {p}" for p in problems)
             + "\nRewrite the whole document with them fixed, following every rule."},
        ]
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="print the first prompt and stop; no API call")
    parser.add_argument("--limit", type=int, help="write at most this many documents")
    parser.add_argument("--only", nargs="+", metavar="DOC", help="e.g. doc_005.txt")
    parser.add_argument("--force", action="store_true",
                        help="rewrite documents that already exist")
    parser.add_argument("--model", default=MODEL)
    args = parser.parse_args()

    specs = [json.loads(line) for line in SPECS.read_text(encoding="utf-8").splitlines()]
    if args.only:
        specs = [s for s in specs if s["doc"] in args.only]
    if not args.force:
        specs = [s for s in specs if not (OUT_DIR / s["doc"]).exists()]
    if args.limit is not None:
        specs = specs[:args.limit]
    if not specs:
        print("Nothing to write. Use --force to rewrite existing documents.")
        return

    if args.dry_run:
        print(f"SYSTEM:\n{SYSTEM}\n\nUSER ({specs[0]['doc']}):\n{build_prompt(specs[0])}")
        print(f"\n{len(specs)} document(s) would be written with {args.model}.")
        return

    import anthropic  # only needed for a real run

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    failed = []
    with open(MANIFEST, "a", encoding="utf-8") as manifest:
        for n, spec in enumerate(specs, 1):
            row = write_one(client, spec, args.model)
            manifest.write(json.dumps(row) + "\n")
            manifest.flush()
            status = "ok" if row["ok"] else "FAILED: " + "; ".join(row["problems"])
            print(f"[{n}/{len(specs)}] {spec['doc']}  attempts={row['attempts']}  {status}")
            if not row["ok"]:
                failed.append(spec["doc"])

    print(f"\nWrote {len(specs) - len(failed)} of {len(specs)} to {OUT_DIR}")
    if failed:
        print("Not written (rerun with --only, or fix by hand):", " ".join(failed))
        sys.exit(1)


if __name__ == "__main__":
    main()
