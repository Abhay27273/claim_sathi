"""VALIDATE node: deterministic check, no LLM call.

Every date must appear in the draft in some recognizable format -- exact
ISO-string equality is too strict, since a letter reads naturally as
"15 March 2026", not the ISO source string "2026-03-15" (found by testing
against a real draft). Text is normalized before comparing -- gpt-oss-120b
systematically writes typographic Unicode punctuation instead of plain ASCII:
U+202F (narrow no-break space) instead of a space, and U+2011 (non-breaking
hyphen) instead of "-" in dates like "01-Jan-2021". Both found by testing
against real drafts, not assumed -- _normalize_text() collapses the whole
class of whitespace/hyphen look-alikes rather than chasing one Unicode
codepoint at a time as each new one turns up.

Clause citations are checked by NUMBER (e.g. "4.2"), not by requiring the
drafted letter to reproduce extracted clause text verbatim. An earlier version
checked the full extracted sentence verbatim and failed every real draft in
testing: the drafting model correctly cites the clause but naturally paraphrases
the surrounding sentence, which is desirable in a letter a human will send, not
a defect to regenerate against. The clause number is short and reliably
reproduced, so it's the thing worth gating on.

On failure, DRAFT regenerates (max 2 attempts) before routing to human review.
"""
import calendar
import re
from datetime import date

_HYPHEN_VARIANTS = "‐‑‒–—―"  # various Unicode dashes -> ASCII "-"


def _normalize_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    return re.sub(f"[{_HYPHEN_VARIANTS}]", "-", text)


def _date_variants(iso_date: str) -> list[str]:
    """Every common way this date could plausibly be written in a formal letter."""
    d = date.fromisoformat(iso_date)
    month_name = calendar.month_name[d.month]
    month_abbr = calendar.month_abbr[d.month]
    return [
        iso_date,  # 2026-03-15
        f"{d.day} {month_name} {d.year}",  # 15 March 2026
        f"{month_name} {d.day}, {d.year}",  # March 15, 2026
        f"{d.day:02d}-{d.month:02d}-{d.year}",  # 15-03-2026
        f"{d.day:02d}/{d.month:02d}/{d.year}",  # 15/03/2026
        f"{d.day:02d}.{d.month:02d}.{d.year}",  # 15.03.2026
        f"{d.day:02d}-{month_abbr}-{d.year}",  # 15-Mar-2026
        f"{d.day:02d} {month_abbr} {d.year}",  # 15 Mar 2026
    ]


def run(state: dict, stage: str) -> dict:
    letter = state["letters"][stage]
    facts = state["extracted_facts"]
    normalized_letter = _normalize_text(letter)
    failures = []

    for date_field in ("policy_start_date", "claim_date", "rejection_date"):
        value = facts.get(date_field)
        if value and not any(
            _normalize_text(variant) in normalized_letter for variant in _date_variants(value)
        ):
            failures.append(f"{date_field} ({value}) not found in draft in any recognized format")

    for clause_number in facts.get("cited_clause_numbers", []):
        if _normalize_text(clause_number) not in normalized_letter:
            failures.append(f"clause number not found in draft: {clause_number}")

    prior_attempt = state.get("validation", {}).get(stage, {}).get("attempt", 0)
    state.setdefault("validation", {})[stage] = {
        "passed": not failures,
        "failures": failures,
        "attempt": prior_attempt + 1,
    }
    return state
